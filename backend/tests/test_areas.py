from __future__ import annotations

import httpx
import pytest

from tests.conftest import BASE, FakeZendesk, token
from zie.readers.areas import (
    AREAS,
    AREAS_BY_KEY,
    SECTIONS,
    item_active,
    item_id,
    item_name,
    read_area,
)
from zie.zendesk.auth import OAuthCredentials


def test_registry_is_consistent() -> None:
    keys = [a.key for a in AREAS]
    assert len(keys) == len(set(keys)) == 21
    for area in AREAS:
        assert area.section in SECTIONS
        assert area.path.startswith("/api/v2/")
        assert area.pagination in ("cursor", "none")


def test_names_follow_each_area_convention() -> None:
    assert item_name(AREAS_BY_KEY["groups"], {"id": 1, "name": "Billing"}) == "Billing"
    assert item_name(AREAS_BY_KEY["ticket-fields"], {"id": 2, "title": "Priority"}) == "Priority"
    statuses = AREAS_BY_KEY["custom-statuses"]
    assert item_name(statuses, {"id": 3, "agent_label": "Awaiting vendor"}) == "Awaiting vendor"
    apps = AREAS_BY_KEY["apps"]
    assert item_name(apps, {"id": 4, "settings": {"name": "Jira"}}) == "Jira"
    assert item_name(apps, {"id": 5, "app_id": 99}) == "99"
    assert item_name(AREAS_BY_KEY["views"], {"id": 6}) == "6"


def test_active_flags() -> None:
    assert item_active(AREAS_BY_KEY["macros"], {"active": False}) is False
    assert item_active(AREAS_BY_KEY["webhooks"], {"status": "active"}) is True
    assert item_active(AREAS_BY_KEY["webhooks"], {"status": "inactive"}) is False
    assert item_active(AREAS_BY_KEY["groups"], {"deleted": False}) is True
    assert item_active(AREAS_BY_KEY["schedules"], {"name": "x"}) is None
    assert item_active(AREAS_BY_KEY["views"], {"title": "no flag"}) is None


def test_item_id_prefers_id_then_key() -> None:
    assert item_id({"id": 12}) == "12"
    assert item_id({"key": "car"}) == "car"
    assert item_id({}) == ""


@pytest.mark.anyio
async def test_cursor_area_sends_page_size(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    route = zendesk.json("GET", "/api/v2/macros", {"macros": [{"id": 1, "title": "Close"}]})
    async with zendesk.client(oauth_creds) as client:
        items = await read_area(client, AREAS_BY_KEY["macros"])
    assert items == [{"id": 1, "title": "Close"}]
    assert route.last.url.params["page[size]"] == "100"


@pytest.mark.anyio
async def test_unpaginated_area_sends_no_page_size_and_follows_next_page(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    route = zendesk.on(
        "GET",
        "/api/v2/slas/policies",
        httpx.Response(
            200,
            json={
                "sla_policies": [{"id": 1, "title": "Gold"}],
                "next_page": f"{BASE}/api/v2/slas/policies?page=2",
            },
        ),
        httpx.Response(
            200, json={"sla_policies": [{"id": 2, "title": "Silver"}], "next_page": None}
        ),
    )
    async with zendesk.client(oauth_creds) as client:
        items = await read_area(client, AREAS_BY_KEY["sla-policies"])
    assert [i["title"] for i in items] == ["Gold", "Silver"]
    assert "page[size]" not in route.calls[0].url.params
    assert route.calls[1].url.params["page"] == "2"


@pytest.mark.anyio
async def test_page_pointing_at_itself_does_not_loop(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    self_link = f"{BASE}/api/v2/custom_roles?page=1"
    route = zendesk.json(
        "GET", "/api/v2/custom_roles", {"custom_roles": [{"id": 1}], "next_page": self_link}
    )
    async with zendesk.client(oauth_creds) as client:
        items = await read_area(client, AREAS_BY_KEY["custom-roles"])
    assert len(route.calls) == 2  # first page, then the self link once
    assert len(items) == 2


@pytest.mark.anyio
async def test_account_settings_become_one_row_per_section(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json(
        "GET",
        "/api/v2/account/settings",
        {"settings": {"tickets": {"comments_public_by_default": True}, "lotus": {"x": 1}}},
    )
    async with zendesk.client(oauth_creds) as client:
        rows = await read_area(client, AREAS_BY_KEY["account-settings"])
    assert rows == [
        {"id": "tickets", "name": "tickets", "comments_public_by_default": True},
        {"id": "lotus", "name": "lotus", "x": 1},
    ]
