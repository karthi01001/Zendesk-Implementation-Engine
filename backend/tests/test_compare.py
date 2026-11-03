from __future__ import annotations

import copy

from tests.factories import make_snapshot, sample_instance
from zie.compare import compare_snapshots, diff_values


def test_diff_values_reports_leaf_paths() -> None:
    before = {"title": "A", "conditions": {"all": [{"field": "status", "value": "open"}]}}
    after = {"title": "B", "conditions": {"all": [{"field": "status", "value": "pending"}]}}
    changes = diff_values(before, after)
    assert [(c.path, c.before, c.after) for c in changes] == [
        ("conditions.all[0].value", "open", "pending"),
        ("title", "A", "B"),
    ]


def test_diff_values_handles_added_removed_and_list_growth() -> None:
    changes = diff_values(
        {"a": 1, "tags": ["x"], "gone": True}, {"a": 1, "tags": ["x", "y"], "new": 2}
    )
    assert [(c.path, c.before, c.after) for c in changes] == [
        ("gone", True, None),
        ("new", None, 2),
        ("tags[1]", None, "y"),
    ]


def test_updated_at_and_url_are_ignored() -> None:
    assert diff_values({"updated_at": "1", "url": "a"}, {"updated_at": "2", "url": "b"}) == []


def test_compare_finds_added_removed_and_changed_items() -> None:
    base_areas = sample_instance()
    target_areas = copy.deepcopy(base_areas)
    target_areas["groups"].append({"id": 12, "name": "Escalations"})
    target_areas["macros"] = []
    target_areas["triggers"][0]["active"] = False
    target_areas["triggers"][0]["updated_at"] = "2026-11-03T10:00:00Z"
    target_areas["views"][0]["updated_at"] = "2026-11-03T10:00:00Z"  # not a real change

    base = make_snapshot(base_areas, snapshot_id="20261102T090000Z")
    target = make_snapshot(target_areas, snapshot_id="20261103T090000Z")
    diff = compare_snapshots(base, target)

    assert (diff.added, diff.removed, diff.changed) == (1, 1, 1)
    by_key = {a.key: a for a in diff.areas}
    assert [i.name for i in by_key["groups"].added] == ["Escalations"]
    assert [i.name for i in by_key["macros"].removed] == ["Assign to billing"]
    trigger = by_key["triggers"].changed[0]
    assert trigger.name == "Route shoe tickets"
    assert [(c.path, c.before, c.after) for c in trigger.changes] == [("active", True, False)]
    assert by_key["views"].changed == []


def test_areas_that_were_not_read_are_reported_by_status_only() -> None:
    areas = sample_instance()
    groups = areas.pop("groups")
    base = make_snapshot(areas, snapshot_id="20261102T090000Z", unavailable=("groups",))
    target = make_snapshot({**areas, "groups": groups}, snapshot_id="20261103T090000Z")
    diff = compare_snapshots(base, target)
    groups_diff = next(a for a in diff.areas if a.key == "groups")
    assert (groups_diff.base_status, groups_diff.target_status) == ("unavailable", "ok")
    assert groups_diff.added == []
    brands = next(a for a in diff.areas if a.key == "brands")
    assert (brands.base_status, brands.target_status) == ("ok", "ok")
    webhooks_missing = next(a for a in diff.areas if a.key == "apps")
    assert (webhooks_missing.base_status, webhooks_missing.target_status) == (None, None)
