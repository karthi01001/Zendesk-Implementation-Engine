"""Every Zendesk Support configuration area the engine reads, and one generic reader for them.

Endpoint facts (path, items key, pagination, plan notes) were checked against Zendesk's API
reference on 2 Nov 2026. Areas whose docs describe no pagination are read with a single
request; a returned offset `next_page` is still followed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from zie.zendesk.client import ZendeskClient

Pagination = Literal["cursor", "none"]


@dataclass(frozen=True)
class AreaSpec:
    key: str
    label: str
    section: str
    path: str
    items_key: str
    pagination: Pagination = "cursor"
    single_object: bool = False
    name_fields: tuple[str, ...] = ("name", "title", "raw_title")
    active_field: str | None = "active"
    active_value: Any = True
    plan_note: str | None = None


SECTIONS = ["Account", "People", "Tickets", "Business rules", "Content and integrations"]

AREAS: list[AreaSpec] = [
    AreaSpec(
        key="account-settings",
        label="Account settings",
        section="Account",
        path="/api/v2/account/settings",
        items_key="settings",
        pagination="none",
        single_object=True,
        active_field=None,
    ),
    AreaSpec(
        key="brands",
        label="Brands",
        section="Account",
        path="/api/v2/brands",
        items_key="brands",
    ),
    AreaSpec(
        key="support-addresses",
        label="Support addresses",
        section="Account",
        path="/api/v2/recipient_addresses",
        items_key="recipient_addresses",
        name_fields=("email", "name"),
        active_field=None,
    ),
    AreaSpec(
        key="groups",
        label="Groups",
        section="People",
        path="/api/v2/groups",
        items_key="groups",
        active_field="deleted",
        active_value=False,
    ),
    AreaSpec(
        key="custom-roles",
        label="Custom roles",
        section="People",
        path="/api/v2/custom_roles",
        items_key="custom_roles",
        pagination="none",
        active_field=None,
        plan_note="Enterprise plan or above",
    ),
    AreaSpec(
        key="user-fields",
        label="User fields",
        section="People",
        path="/api/v2/user_fields",
        items_key="user_fields",
        name_fields=("title", "raw_title", "key"),
    ),
    AreaSpec(
        key="organization-fields",
        label="Organization fields",
        section="People",
        path="/api/v2/organization_fields",
        items_key="organization_fields",
        name_fields=("title", "raw_title", "key"),
    ),
    AreaSpec(
        key="ticket-fields",
        label="Ticket fields",
        section="Tickets",
        path="/api/v2/ticket_fields",
        items_key="ticket_fields",
        name_fields=("title", "raw_title"),
    ),
    AreaSpec(
        key="ticket-forms",
        label="Ticket forms",
        section="Tickets",
        path="/api/v2/ticket_forms",
        items_key="ticket_forms",
        name_fields=("name", "raw_name", "display_name"),
        plan_note="Suite Growth or above, or Support Enterprise",
    ),
    AreaSpec(
        key="custom-statuses",
        label="Custom statuses",
        section="Tickets",
        path="/api/v2/custom_statuses",
        items_key="custom_statuses",
        pagination="none",
        name_fields=("agent_label", "raw_agent_label"),
        plan_note="Custom ticket statuses must be activated",
    ),
    AreaSpec(
        key="views",
        label="Views",
        section="Business rules",
        path="/api/v2/views",
        items_key="views",
        name_fields=("title", "raw_title"),
    ),
    AreaSpec(
        key="macros",
        label="Macros",
        section="Business rules",
        path="/api/v2/macros",
        items_key="macros",
        name_fields=("title", "raw_title"),
    ),
    AreaSpec(
        key="triggers",
        label="Triggers",
        section="Business rules",
        path="/api/v2/triggers",
        items_key="triggers",
        name_fields=("title", "raw_title"),
    ),
    AreaSpec(
        key="trigger-categories",
        label="Trigger categories",
        section="Business rules",
        path="/api/v2/trigger_categories",
        items_key="trigger_categories",
        active_field=None,
        plan_note="Trigger categories must be enabled",
    ),
    AreaSpec(
        key="automations",
        label="Automations",
        section="Business rules",
        path="/api/v2/automations",
        items_key="automations",
        name_fields=("title", "raw_title"),
    ),
    AreaSpec(
        key="sla-policies",
        label="SLA policies",
        section="Business rules",
        path="/api/v2/slas/policies",
        items_key="sla_policies",
        pagination="none",
        name_fields=("title",),
        active_field=None,
        plan_note="Support Professional or Suite Growth and above",
    ),
    AreaSpec(
        key="schedules",
        label="Schedules",
        section="Business rules",
        path="/api/v2/business_hours/schedules",
        items_key="schedules",
        pagination="none",
        active_field=None,
    ),
    AreaSpec(
        key="dynamic-content",
        label="Dynamic content",
        section="Content and integrations",
        path="/api/v2/dynamic_content/items",
        items_key="items",
        name_fields=("name", "placeholder"),
        active_field=None,
        plan_note="Professional plan and above",
    ),
    AreaSpec(
        key="webhooks",
        label="Webhooks",
        section="Content and integrations",
        path="/api/v2/webhooks",
        items_key="webhooks",
        active_field="status",
        active_value="active",
    ),
    AreaSpec(
        key="apps",
        label="Installed apps",
        section="Content and integrations",
        path="/api/v2/apps/installations",
        items_key="installations",
        pagination="none",
        name_fields=("settings.name", "app_id"),
        active_field="enabled",
    ),
    AreaSpec(
        key="custom-objects",
        label="Custom objects",
        section="Content and integrations",
        path="/api/v2/custom_objects",
        items_key="custom_objects",
        pagination="none",
        name_fields=("title", "raw_title", "key"),
        active_field=None,
    ),
]

AREAS_BY_KEY: dict[str, AreaSpec] = {area.key: area for area in AREAS}


class AreaInfo(BaseModel):
    key: str
    label: str
    section: str
    plan_note: str | None = None


def area_infos() -> list[AreaInfo]:
    return [
        AreaInfo(key=a.key, label=a.label, section=a.section, plan_note=a.plan_note) for a in AREAS
    ]


def _lookup(item: dict[str, Any], dotted: str) -> Any:
    value: Any = item
    for part in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def item_id(item: dict[str, Any]) -> str:
    for field in ("id", "key"):
        value = item.get(field)
        if value not in (None, ""):
            return str(value)
    return ""


def item_name(spec: AreaSpec, item: dict[str, Any]) -> str:
    for field in spec.name_fields:
        value = _lookup(item, field)
        if value not in (None, ""):
            return str(value)
    return item_id(item) or "(unnamed)"


def item_active(spec: AreaSpec, item: dict[str, Any]) -> bool | None:
    if spec.active_field is None or spec.active_field not in item:
        return None
    return bool(item.get(spec.active_field) == spec.active_value)


def _settings_to_items(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """Account settings is one object of sections; show each section as a row."""
    rows: list[dict[str, Any]] = []
    for section, values in settings.items():
        body = values if isinstance(values, dict) else {"value": values}
        rows.append({"id": section, "name": section, **body})
    return rows


async def read_area(client: ZendeskClient, spec: AreaSpec) -> list[dict[str, Any]]:
    """Return every raw item of one area. Raises ZendeskError subclasses on failure."""
    if spec.single_object:
        data = await client.get(spec.path)
        value = data.get(spec.items_key) or {}
        return _settings_to_items(value) if isinstance(value, dict) else []
    return [
        item
        async for item in client.paginate(
            spec.path, spec.items_key, cursor=spec.pagination == "cursor"
        )
    ]
