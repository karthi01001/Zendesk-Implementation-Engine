"""Compare two snapshots of the same instance: what was added, removed or changed, per area. # test """

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from zie.readers.areas import AREAS, item_id, item_name
from zie.snapshot import AreaStatus, Snapshot

# Fields that change without anyone changing the configuration.
IGNORED_FIELDS = {"updated_at", "url"}
MAX_CHANGES_PER_ITEM = 50
MAX_VALUE_CHARS = 300


class ItemRef(BaseModel):
    id: str
    name: str


class FieldChange(BaseModel):
    path: str
    before: Any = None
    after: Any = None


class ChangedItem(ItemRef):
    changes: list[FieldChange]
    truncated: bool = False


class AreaDiff(BaseModel):
    key: str
    label: str
    section: str
    base_status: AreaStatus | None
    target_status: AreaStatus | None
    added: list[ItemRef] = []
    removed: list[ItemRef] = []
    changed: list[ChangedItem] = []


class SnapshotDiff(BaseModel):
    subdomain: str
    base_id: str
    target_id: str
    base_taken_at: datetime
    target_taken_at: datetime
    added: int
    removed: int
    changed: int
    areas: list[AreaDiff]


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_VALUE_CHARS:
        return value[:MAX_VALUE_CHARS] + "…"
    if isinstance(value, (dict, list)):
        text = repr(value)
        if len(text) > MAX_VALUE_CHARS:
            return text[:MAX_VALUE_CHARS] + "…"
    return value


def diff_values(before: Any, after: Any, path: str = "") -> list[FieldChange]:
    """Leaf-level differences between two JSON values; lists are compared position by position."""
    if isinstance(before, dict) and isinstance(after, dict):
        changes: list[FieldChange] = []
        for key in sorted(set(before) | set(after), key=str):
            if not path and key in IGNORED_FIELDS:
                continue
            sub = f"{path}.{key}" if path else str(key)
            if key not in before:
                changes.append(FieldChange(path=sub, before=None, after=_clip(after[key])))
            elif key not in after:
                changes.append(FieldChange(path=sub, before=_clip(before[key]), after=None))
            else:
                changes.extend(diff_values(before[key], after[key], sub))
        return changes
    if isinstance(before, list) and isinstance(after, list):
        changes = []
        for index in range(max(len(before), len(after))):
            sub = f"{path}[{index}]"
            if index >= len(before):
                changes.append(FieldChange(path=sub, before=None, after=_clip(after[index])))
            elif index >= len(after):
                changes.append(FieldChange(path=sub, before=_clip(before[index]), after=None))
            else:
                changes.extend(diff_values(before[index], after[index], sub))
        return changes
    if before != after:
        return [FieldChange(path=path or "(value)", before=_clip(before), after=_clip(after))]
    return []


def compare_snapshots(base: Snapshot, target: Snapshot) -> SnapshotDiff:
    areas: list[AreaDiff] = []
    for spec in AREAS:
        old = base.area(spec.key)
        new = target.area(spec.key)
        diff = AreaDiff(
            key=spec.key,
            label=spec.label,
            section=spec.section,
            base_status=old.status if old else None,
            target_status=new.status if new else None,
        )
        if old is None or new is None or old.status != "ok" or new.status != "ok":
            areas.append(diff)  # cannot compare items; the status change itself is shown
            continue
        before = {item_id(i): i for i in old.items}
        after = {item_id(i): i for i in new.items}
        for key in after.keys() - before.keys():
            diff.added.append(ItemRef(id=key, name=item_name(spec, after[key])))
        for key in before.keys() - after.keys():
            diff.removed.append(ItemRef(id=key, name=item_name(spec, before[key])))
        for key in before.keys() & after.keys():
            changes = diff_values(before[key], after[key])
            if changes:
                diff.changed.append(
                    ChangedItem(
                        id=key,
                        name=item_name(spec, after[key]),
                        changes=changes[:MAX_CHANGES_PER_ITEM],
                        truncated=len(changes) > MAX_CHANGES_PER_ITEM,
                    )
                )
        diff.added.sort(key=lambda i: i.name.lower())
        diff.removed.sort(key=lambda i: i.name.lower())
        diff.changed.sort(key=lambda i: i.name.lower())
        areas.append(diff)
    return SnapshotDiff(
        subdomain=target.subdomain,
        base_id=base.id,
        target_id=target.id,
        base_taken_at=base.taken_at,
        target_taken_at=target.taken_at,
        added=sum(len(a.added) for a in areas),
        removed=sum(len(a.removed) for a in areas),
        changed=sum(len(a.changed) for a in areas),
        areas=areas,
    )
