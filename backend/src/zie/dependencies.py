"""Who uses what: references between configuration items, built from one snapshot.

Reference formats follow Zendesk's Conditions and Actions references and the API docs for
views, macros, SLA policies and ticket forms (checked 3 Nov 2026):

- custom ticket fields: `custom_fields_<id>` (conditions, actions); dropdown values are tags
- user / organization fields: `user.custom_fields.<key>`, `requester.custom_fields.<key>`,
  `organization.custom_fields.<key>` (by key)
- `group_id`, `brand_id`, `ticket_form_id`, `custom_status_id`; `current_tags` / `set_tags` /
  `remove_tags` (space-separated); `notification_webhook` [webhook id, body];
  `notification_group` [group id | "group_id", subject, body]
- views: `restriction` {type: Group, id, ids}; `execution.columns[].id` numeric for custom fields;
  `execution.group_by` / `sort_by` a title or a custom field id
- triggers: `category_id` (string); ticket forms: `ticket_field_ids`, `restricted_brand_ids`,
  `agent_conditions` / `end_user_conditions` (parent_field_id, child_fields[].id)
- dynamic content: `{{dc.<name>}}` placeholders anywhere in text

Schedule fields are not named in the docs, so any field containing "schedule" with a numeric
value is treated as a schedule reference (best effort).
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from zie.readers.areas import AREAS_BY_KEY, item_id, item_name
from zie.snapshot import Snapshot

TAGS = "tags"

_CUSTOM_FIELD = re.compile(r"^custom_fields_(\d+)$")
_LOOKUP_FIELD = re.compile(r"ticket_fields?_(\d+)")
_PERSON_FIELD = re.compile(r"^(user|requester|organization)\.custom_fields\.(.+)$")
_DC = re.compile(r"\{\{\s*dc\.([A-Za-z0-9_.-]+)\s*\}\}")
_DIGITS = re.compile(r"^\d+$")

# Areas whose items refer to others. "Unused" is only trustworthy when all of them were read.
SOURCE_AREAS = ("triggers", "automations", "macros", "views", "sla-policies", "ticket-forms")

# Areas whose items can be referenced by others (they get a "used by" count).
TARGET_AREAS = {
    "ticket-fields",
    "user-fields",
    "organization-fields",
    "groups",
    "brands",
    "ticket-forms",
    "custom-statuses",
    "schedules",
    "webhooks",
    "trigger-categories",
    "dynamic-content",
}


class ItemKey(BaseModel):
    area: str
    id: str
    name: str
    label: str
    missing: bool = False


class Reference(BaseModel):
    source: ItemKey
    target: ItemKey
    context: str
    detail: str | None = None


class ItemDependencies(BaseModel):
    item: ItemKey
    uses: list[Reference]
    used_by: list[Reference]


class TagUsage(BaseModel):
    tag: str
    used_by: int


@dataclass
class _Raw:
    target_area: str
    target_id: str
    context: str
    detail: str | None = None


def _ids(value: Any) -> list[str]:
    """Numeric ids from a value that may be an int, a digit string or a list of those."""
    values = value if isinstance(value, list) else [value]
    found: list[str] = []
    for v in values:
        text = str(v).strip() if v is not None and not isinstance(v, bool) else ""
        if _DIGITS.fullmatch(text):
            found.append(text)
    return found


def _tags(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    tags: list[str] = []
    for v in values:
        if isinstance(v, str):
            tags.extend(t for t in re.split(r"[\s,]+", v) if t)
    return tags


def _describe(entry: dict[str, Any]) -> str | None:
    operator = entry.get("operator")
    value = entry.get("value")
    if isinstance(value, list):
        value = ", ".join(str(v) for v in value[:2]) + ("…" if len(value) > 2 else "")
    text = " ".join(str(p) for p in (operator, value) if p not in (None, ""))
    return text[:120] or None


def _entries(block: Any, context: str) -> Iterator[tuple[dict[str, Any], str]]:
    """Yield (entry, context) from a conditions object ({all, any}) or a list of entries."""
    if isinstance(block, dict):
        for part in ("all", "any"):
            for entry in block.get(part) or []:
                if isinstance(entry, dict):
                    yield entry, f"{context} ({part})"
    elif isinstance(block, list):
        for entry in block:
            if isinstance(entry, dict):
                yield entry, context


class _Index:
    """Lookups built from the snapshot: names, field types, keys and placeholders."""

    def __init__(self, snapshot: Snapshot) -> None:
        self.items: dict[str, dict[str, dict[str, Any]]] = {}
        self.ok_areas: set[str] = set()
        for result in snapshot.areas:
            if result.status == "ok":
                self.ok_areas.add(result.key)
            self.items[result.key] = {item_id(i): i for i in result.items if item_id(i)}
        self.field_types = {
            fid: str(f.get("type") or "") for fid, f in self.items.get("ticket-fields", {}).items()
        }
        self.by_key: dict[str, dict[str, str]] = {
            area: {str(f.get("key")): fid for fid, f in self.items.get(area, {}).items()}
            for area in ("user-fields", "organization-fields")
        }
        self.by_placeholder: dict[str, str] = {}
        for did, item in self.items.get("dynamic-content", {}).items():
            match = _DC.search(str(item.get("placeholder") or ""))
            if match:
                self.by_placeholder[match.group(1)] = did

    def key_for(self, area: str, item: dict[str, Any]) -> ItemKey:
        spec = AREAS_BY_KEY[area]
        return ItemKey(area=area, id=item_id(item), name=item_name(spec, item), label=spec.label)

    def target(self, area: str, target_id: str) -> ItemKey:
        if area == TAGS:
            return ItemKey(area=TAGS, id=target_id, name=target_id, label="Tags")
        spec = AREAS_BY_KEY[area]
        item = self.items.get(area, {}).get(target_id)
        if item is None:
            # Only call it broken when the area itself was read; otherwise we cannot know.
            return ItemKey(
                area=area,
                id=target_id,
                name=f"{spec.label} {target_id}",
                label=spec.label,
                missing=area in self.ok_areas,
            )
        return ItemKey(area=area, id=target_id, name=item_name(spec, item), label=spec.label)


def _entry_refs(index: _Index, entry: dict[str, Any], context: str) -> Iterator[_Raw]:
    name = str(entry.get("field") or "")
    value = entry.get("value")
    detail = _describe(entry)

    if match := _CUSTOM_FIELD.fullmatch(name):
        fid = match.group(1)
        yield _Raw("ticket-fields", fid, context, detail)
        if index.field_types.get(fid) in ("tagger", "multiselect"):
            for tag in _tags(value):
                yield _Raw(TAGS, tag, context, f"value of field {fid}")
        return
    if match := _PERSON_FIELD.fullmatch(name):
        area = "organization-fields" if match.group(1) == "organization" else "user-fields"
        key = match.group(2)
        yield _Raw(area, index.by_key[area].get(key, key), context, detail)
        return
    if match := _LOOKUP_FIELD.search(name):
        yield _Raw("ticket-fields", match.group(1), context, detail)
        return
    if name in ("current_tags", "set_tags", "remove_tags"):
        for tag in _tags(value):
            yield _Raw(TAGS, tag, context, name.replace("_", " "))
        return
    simple = {
        "group_id": "groups",
        "brand_id": "brands",
        "ticket_form_id": "ticket-forms",
        "custom_status_id": "custom-statuses",
    }
    if name in simple:
        for target_id in _ids(value):
            yield _Raw(simple[name], target_id, context, detail)
        return
    if name == "notification_webhook" and isinstance(value, list) and value:
        if value[0] not in (None, ""):
            yield _Raw("webhooks", str(value[0]), context, "notify webhook")
        return
    if name == "notification_group" and isinstance(value, list) and value:
        for target_id in _ids(value[0]):
            yield _Raw("groups", target_id, context, "notify group")
        return
    if "schedule" in name:
        for target_id in _ids(value):
            yield _Raw("schedules", target_id, context, detail)


def _restriction_refs(item: dict[str, Any]) -> Iterator[_Raw]:
    restriction = item.get("restriction")
    if isinstance(restriction, dict) and restriction.get("type") == "Group":
        ids = set(_ids(restriction.get("ids") or [])) | set(_ids(restriction.get("id")))
        for target_id in sorted(ids):
            yield _Raw("groups", target_id, "restricted to")


def _view_columns(item: dict[str, Any]) -> Iterator[_Raw]:
    execution = item.get("execution") or {}
    if not isinstance(execution, dict):
        return
    for column in execution.get("columns") or []:
        if isinstance(column, dict):
            cid = column.get("id")
            if isinstance(cid, int) or (isinstance(cid, str) and _DIGITS.fullmatch(cid)):
                yield _Raw("ticket-fields", str(cid), "column")
            elif isinstance(cid, str) and (m := _CUSTOM_FIELD.fullmatch(cid)):
                yield _Raw("ticket-fields", m.group(1), "column")
    for key, label in (("group_by", "group by"), ("sort_by", "sort by")):
        for target_id in _ids(execution.get(key)):
            yield _Raw("ticket-fields", target_id, label)


def _dc_refs(index: _Index, item: Any) -> Iterator[_Raw]:
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, str):
            found.update(_DC.findall(value))
        elif isinstance(value, dict):
            for v in value.values():
                walk(v)
        elif isinstance(value, list):
            for v in value:
                walk(v)

    walk(item)
    for name in sorted(found):
        yield _Raw("dynamic-content", index.by_placeholder.get(name, name), "placeholder")


def _refs_for(index: _Index, area: str, item: dict[str, Any]) -> Iterator[_Raw]:
    if area in ("triggers", "automations"):
        for entry, ctx in _entries(item.get("conditions"), "condition"):
            yield from _entry_refs(index, entry, ctx)
        for entry, ctx in _entries(item.get("actions"), "action"):
            yield from _entry_refs(index, entry, ctx)
        if area == "triggers" and item.get("category_id") not in (None, ""):
            yield _Raw("trigger-categories", str(item["category_id"]), "category")
    elif area == "views":
        for entry, ctx in _entries(item.get("conditions"), "condition"):
            yield from _entry_refs(index, entry, ctx)
        yield from _restriction_refs(item)
        yield from _view_columns(item)
    elif area == "macros":
        for entry, ctx in _entries(item.get("actions"), "action"):
            yield from _entry_refs(index, entry, ctx)
        yield from _restriction_refs(item)
    elif area == "sla-policies":
        for entry, ctx in _entries(item.get("filter"), "applies when"):
            yield from _entry_refs(index, entry, ctx)
    elif area == "ticket-forms":
        for target_id in _ids(item.get("ticket_field_ids") or []):
            yield _Raw("ticket-fields", target_id, "form field")
        for target_id in _ids(item.get("restricted_brand_ids") or []):
            yield _Raw("brands", target_id, "available in brand")
        for key in ("agent_conditions", "end_user_conditions"):
            who = "agents" if key == "agent_conditions" else "end users"
            for condition in item.get(key) or []:
                if not isinstance(condition, dict):
                    continue
                for target_id in _ids(condition.get("parent_field_id")):
                    yield _Raw("ticket-fields", target_id, f"conditional parent ({who})")
                for child in condition.get("child_fields") or []:
                    if isinstance(child, dict):
                        for target_id in _ids(child.get("id")):
                            yield _Raw("ticket-fields", target_id, f"conditional child ({who})")
    elif area == "ticket-fields":
        for option in item.get("custom_field_options") or []:
            if isinstance(option, dict) and option.get("value"):
                yield _Raw(TAGS, str(option["value"]), "option tag", str(option.get("name") or ""))
        if item.get("type") == "checkbox" and item.get("tag"):
            yield _Raw(TAGS, str(item["tag"]), "checkbox tag")
    elif area == "support-addresses":
        for target_id in _ids(item.get("brand_id")):
            yield _Raw("brands", target_id, "brand")

    if area not in ("dynamic-content", "account-settings"):
        yield from _dc_refs(index, item)


@dataclass
class DependencyGraph:
    references: list[Reference]
    used_by: dict[tuple[str, str], list[Reference]] = field(default_factory=dict)
    uses: dict[tuple[str, str], list[Reference]] = field(default_factory=dict)
    # Labels of source areas that were not read; while any are missing, "unused" is unknown.
    incomplete_areas: list[str] = field(default_factory=list)

    @classmethod
    def build(cls, snapshot: Snapshot) -> DependencyGraph:
        index = _Index(snapshot)
        references: list[Reference] = []
        for result in snapshot.areas:
            if result.key not in AREAS_BY_KEY:
                continue
            for item in result.items:
                source = index.key_for(result.key, item)
                seen: set[tuple[str, str, str]] = set()
                for raw in _refs_for(index, result.key, item):
                    dedupe = (raw.target_area, raw.target_id, raw.context)
                    if dedupe in seen:
                        continue
                    seen.add(dedupe)
                    references.append(
                        Reference(
                            source=source,
                            target=index.target(raw.target_area, raw.target_id),
                            context=raw.context,
                            detail=raw.detail,
                        )
                    )
        used_by: dict[tuple[str, str], list[Reference]] = defaultdict(list)
        uses: dict[tuple[str, str], list[Reference]] = defaultdict(list)
        for ref in references:
            used_by[(ref.target.area, ref.target.id)].append(ref)
            uses[(ref.source.area, ref.source.id)].append(ref)
        incomplete = [AREAS_BY_KEY[key].label for key in SOURCE_AREAS if key not in index.ok_areas]
        return cls(
            references=references,
            used_by=dict(used_by),
            uses=dict(uses),
            incomplete_areas=incomplete,
        )

    @property
    def complete(self) -> bool:
        return not self.incomplete_areas

    def is_unused(self, area: str, item: dict[str, Any]) -> bool | None:
        """True/False when we can tell; None when an area that could refer to it was not read.

        System ticket fields (removable = false) are never reported as unused.
        """
        if area not in TARGET_AREAS or not self.complete:
            return None
        if area == "ticket-fields" and not item.get("removable"):
            return False
        return self.used_by_count(area, item_id(item)) == 0

    def used_by_count(self, area: str, target_id: str) -> int:
        """How many distinct items use this one (an item using it twice counts once)."""
        refs = self.used_by.get((area, target_id), [])
        return len({(r.source.area, r.source.id) for r in refs})

    def for_item(self, item: ItemKey) -> ItemDependencies:
        key = (item.area, item.id)
        return ItemDependencies(
            item=item, uses=self.uses.get(key, []), used_by=self.used_by.get(key, [])
        )

    def broken(self) -> list[Reference]:
        return [r for r in self.references if r.target.missing]

    def tags(self) -> list[TagUsage]:
        counts = [
            TagUsage(tag=target_id, used_by=self.used_by_count(TAGS, target_id))
            for (area, target_id) in self.used_by
            if area == TAGS
        ]
        return sorted(counts, key=lambda t: (-t.used_by, t.tag))


def unused_custom_ticket_fields(snapshot: Snapshot, graph: DependencyGraph) -> list[ItemKey]:
    """Custom (removable) ticket fields no rule, view, macro, SLA or form refers to."""
    result = snapshot.area("ticket-fields")
    if result is None or result.status != "ok" or not graph.complete:
        return []
    spec = AREAS_BY_KEY["ticket-fields"]
    return [
        ItemKey(area=spec.key, id=item_id(item), name=item_name(spec, item), label=spec.label)
        for item in result.items
        if graph.is_unused("ticket-fields", item)
    ]


def item_key(snapshot: Snapshot, area: str, target_id: str) -> ItemKey | None:
    if area == TAGS:
        return ItemKey(area=TAGS, id=target_id, name=target_id, label="Tags")
    result = snapshot.area(area)
    spec = AREAS_BY_KEY.get(area)
    if result is None or spec is None:
        return None
    for item in result.items:
        if item_id(item) == target_id:
            return ItemKey(area=area, id=target_id, name=item_name(spec, item), label=spec.label)
    return None
