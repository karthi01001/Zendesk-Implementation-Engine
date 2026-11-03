"""Small, realistic snapshots for tests, built without calling Zendesk."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from zie.readers.areas import AREAS_BY_KEY
from zie.snapshot import AreaResult, Snapshot


def make_snapshot(
    areas: dict[str, list[dict[str, Any]]],
    *,
    snapshot_id: str = "20261103T090000Z",
    unavailable: tuple[str, ...] = (),
) -> Snapshot:
    results = [
        AreaResult(
            key=key,
            label=AREAS_BY_KEY[key].label,
            section=AREAS_BY_KEY[key].section,
            status="ok",
            count=len(items),
            items=items,
        )
        for key, items in areas.items()
    ]
    results += [
        AreaResult(
            key=key,
            label=AREAS_BY_KEY[key].label,
            section=AREAS_BY_KEY[key].section,
            status="unavailable",
            message="Not available on this account.",
        )
        for key in unavailable
    ]
    taken_at = datetime.strptime(snapshot_id, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return Snapshot(
        id=snapshot_id,
        subdomain="acme",
        taken_at=taken_at,
        engine_version="test",
        areas=results,
    )


def sample_instance() -> dict[str, list[dict[str, Any]]]:
    """One of every kind of reference the dependency index understands."""
    return {
        "ticket-fields": [
            {"id": 1, "title": "Subject", "type": "subject", "removable": False, "active": True},
            {
                "id": 100,
                "title": "Product",
                "type": "tagger",
                "removable": True,
                "active": True,
                "custom_field_options": [
                    {"name": "Shoes", "value": "product_shoes"},
                    {"name": "Hats", "value": "product_hats"},
                ],
            },
            {"id": 101, "title": "Order number", "type": "text", "removable": True, "active": True},
            {"id": 102, "title": "Legacy code", "type": "text", "removable": True, "active": False},
            {"id": 103, "title": "VIP", "type": "checkbox", "tag": "vip", "removable": True},
        ],
        "groups": [{"id": 10, "name": "Tier 1"}, {"id": 11, "name": "Billing"}],
        "brands": [{"id": 5, "name": "Main brand"}],
        "user-fields": [{"id": 200, "key": "plan", "title": "Plan"}],
        "organization-fields": [{"id": 300, "key": "region", "title": "Region"}],
        "webhooks": [{"id": "01HWEB", "name": "Slack alerts", "status": "active"}],
        "trigger-categories": [{"id": "10026", "name": "Routing"}],
        "dynamic-content": [{"id": 400, "name": "Greeting", "placeholder": "{{dc.greeting}}"}],
        "custom-statuses": [{"id": 500, "agent_label": "Waiting on vendor", "active": True}],
        "schedules": [{"id": 600, "name": "EU hours"}],
        "ticket-forms": [
            {
                "id": 700,
                "name": "Default form",
                "active": True,
                "ticket_field_ids": [1, 100, 101],
                "restricted_brand_ids": [5],
                "agent_conditions": [
                    {
                        "parent_field_id": 100,
                        "value": "product_shoes",
                        "child_fields": [{"id": 101, "is_required": True}],
                    }
                ],
            }
        ],
        "triggers": [
            {
                "id": 800,
                "title": "Route shoe tickets",
                "active": True,
                "category_id": "10026",
                "conditions": {
                    "all": [
                        {"field": "custom_fields_100", "operator": "is", "value": "product_shoes"},
                        {"field": "user.custom_fields.plan", "operator": "is", "value": "gold"},
                    ],
                    "any": [
                        {
                            "field": "organization.custom_fields.region",
                            "operator": "is",
                            "value": "emea",
                        }
                    ],
                },
                "actions": [
                    {"field": "group_id", "value": "10"},
                    {"field": "set_tags", "value": "routed shoes_team"},
                    {"field": "notification_webhook", "value": ["01HWEB", "{}"]},
                    {"field": "comment_value", "value": "{{dc.greeting}}, we are on it"},
                    {"field": "group_id", "value": "999"},
                ],
            }
        ],
        "automations": [
            {
                "id": 801,
                "title": "Close stale vendor tickets",
                "active": False,
                "conditions": {
                    "all": [
                        {"field": "custom_status_id", "operator": "is", "value": "500"},
                        {"field": "schedule_id", "operator": "is", "value": "600"},
                    ]
                },
                "actions": [{"field": "notification_group", "value": ["11", "Subject", "Body"]}],
            }
        ],
        "views": [
            {
                "id": 900,
                "title": "Billing queue",
                "active": True,
                "restriction": {"type": "Group", "ids": [11]},
                "conditions": {"all": [{"field": "group_id", "operator": "is", "value": 11}]},
                "execution": {
                    "columns": [{"id": "subject"}, {"id": 101, "title": "Order number"}],
                    "group_by": "100",
                    "sort_by": "created_at",
                },
            }
        ],
        "macros": [
            {
                "id": 950,
                "title": "Assign to billing",
                "active": True,
                "restriction": {"type": "Group", "id": 11},
                "actions": [
                    {"field": "group_id", "value": "11"},
                    {"field": "brand_id", "value": "5"},
                    {"field": "ticket_form_id", "value": "700"},
                ],
            }
        ],
        "sla-policies": [
            {
                "id": 960,
                "title": "Gold",
                "filter": {"all": [{"field": "brand_id", "operator": "is", "value": 5}], "any": []},
                "policy_metrics": [{"priority": "high", "metric": "first_reply_time"}],
            }
        ],
        "support-addresses": [{"id": 970, "email": "help@acme.test", "brand_id": 5}],
    }
