from __future__ import annotations

from tests.factories import make_snapshot, sample_instance
from zie.dependencies import DependencyGraph, item_key, unused_custom_ticket_fields
from zie.snapshot import Snapshot


def _graph() -> tuple[DependencyGraph, Snapshot]:
    snapshot = make_snapshot(sample_instance())
    return DependencyGraph.build(snapshot), snapshot


def _sources(graph: DependencyGraph, area: str, target_id: str) -> set[str]:
    return {f"{r.source.area}:{r.source.id}" for r in graph.used_by.get((area, target_id), [])}


def test_ticket_fields_are_found_in_rules_views_and_forms() -> None:
    graph, _ = _graph()
    assert _sources(graph, "ticket-fields", "100") == {
        "triggers:800",
        "views:900",
        "ticket-forms:700",
    }
    assert _sources(graph, "ticket-fields", "101") == {"ticket-forms:700", "views:900"}
    assert graph.used_by_count("ticket-fields", "100") == 3
    assert graph.used_by_count("ticket-fields", "102") == 0


def test_groups_brands_and_the_rest() -> None:
    graph, _ = _graph()
    assert _sources(graph, "groups", "10") == {"triggers:800"}
    assert _sources(graph, "groups", "11") == {"automations:801", "views:900", "macros:950"}
    assert _sources(graph, "brands", "5") == {
        "ticket-forms:700",
        "macros:950",
        "sla-policies:960",
        "support-addresses:970",
    }
    assert _sources(graph, "user-fields", "200") == {"triggers:800"}
    assert _sources(graph, "organization-fields", "300") == {"triggers:800"}
    assert _sources(graph, "webhooks", "01HWEB") == {"triggers:800"}
    assert _sources(graph, "trigger-categories", "10026") == {"triggers:800"}
    assert _sources(graph, "dynamic-content", "400") == {"triggers:800"}
    assert _sources(graph, "custom-statuses", "500") == {"automations:801"}
    assert _sources(graph, "schedules", "600") == {"automations:801"}
    assert _sources(graph, "ticket-forms", "700") == {"macros:950"}


def test_tags_come_from_rules_and_dropdown_options() -> None:
    graph, _ = _graph()
    tags = {t.tag: t.used_by for t in graph.tags()}
    assert tags["product_shoes"] == 2  # the trigger condition and the Product field option
    assert tags["product_hats"] == 1
    assert tags["routed"] == 1
    assert tags["shoes_team"] == 1
    assert tags["vip"] == 1
    assert graph.tags()[0].tag == "product_shoes"


def test_broken_references_point_at_missing_items() -> None:
    graph, _ = _graph()
    broken = graph.broken()
    assert len(broken) == 1
    assert broken[0].source.name == "Route shoe tickets"
    assert broken[0].target.area == "groups"
    assert broken[0].target.id == "999"
    assert broken[0].target.missing is True


def test_references_to_unread_areas_are_not_called_broken() -> None:
    areas = sample_instance()
    del areas["groups"]
    graph = DependencyGraph.build(make_snapshot(areas, unavailable=("groups",)))
    assert graph.broken() == []


def test_item_view_lists_uses_with_context() -> None:
    graph, snapshot = _graph()
    key = item_key(snapshot, "triggers", "800")
    assert key is not None and key.name == "Route shoe tickets"
    deps = graph.for_item(key)
    contexts = {(r.target.area, r.context) for r in deps.uses}
    assert ("ticket-fields", "condition (all)") in contexts
    assert ("organization-fields", "condition (any)") in contexts
    assert ("groups", "action") in contexts
    assert ("trigger-categories", "category") in contexts
    assert ("dynamic-content", "placeholder") in contexts
    assert deps.used_by == []
    product = next(r for r in deps.uses if r.target.id == "100")
    assert product.target.name == "Product"
    assert product.detail == "is product_shoes"


def test_unused_custom_ticket_fields_skip_system_fields() -> None:
    graph, snapshot = _graph()
    unused = unused_custom_ticket_fields(snapshot, graph)
    assert [f.name for f in unused] == ["Legacy code", "VIP"]


def test_same_reference_twice_in_one_item_is_counted_once() -> None:
    graph, _ = _graph()
    # The view references group 11 as a restriction and as a condition.
    contexts = sorted(r.context for r in graph.used_by[("groups", "11")] if r.source.id == "900")
    assert contexts == ["condition (all)", "restricted to"]
    assert graph.used_by_count("groups", "11") == 3


def test_unused_flag_respects_system_fields_and_incomplete_reads() -> None:
    graph, _ = _graph()
    fields = {i["id"]: i for i in sample_instance()["ticket-fields"]}
    assert graph.is_unused("ticket-fields", fields[102]) is True
    assert graph.is_unused("ticket-fields", fields[100]) is False
    assert graph.is_unused("ticket-fields", fields[1]) is False  # system field: never "unused"
    assert graph.is_unused("triggers", {"id": 800}) is None

    areas = sample_instance()
    del areas["macros"]
    partial = DependencyGraph.build(make_snapshot(areas, unavailable=("macros",)))
    assert partial.incomplete_areas == ["Macros"]
    assert partial.is_unused("ticket-fields", fields[102]) is None


def test_empty_webhook_id_is_not_a_reference() -> None:
    areas = sample_instance()
    areas["triggers"][0]["actions"] = [{"field": "notification_webhook", "value": ["", "{}"]}]
    graph = DependencyGraph.build(make_snapshot(areas))
    assert all(r.target.area != "webhooks" for r in graph.references)
