from __future__ import annotations

import httpx
import pytest

from tests.conftest import BASE, FakeSleep, FakeZendesk, token
from zie.connection import check_connection
from zie.readers.groups import read_groups
from zie.zendesk.auth import ApiTokenCredentials, OAuthCredentials
from zie.zendesk.client import ZendeskClient
from zie.zendesk.errors import (
    AuthenticationError,
    PermissionDeniedError,
    RateLimitError,
    ZendeskAPIError,
)

pytestmark = pytest.mark.anyio

ME = {"user": {"id": 7, "name": "ZIE Service", "email": "zie@acme.test", "role": "admin"}}


async def test_sends_bearer_token(oauth_creds: OAuthCredentials, zendesk: FakeZendesk) -> None:
    zendesk.on("POST", "/oauth/tokens", token("tok-1"))
    route = zendesk.json("GET", "/api/v2/users/me.json", ME)
    async with zendesk.client(oauth_creds) as client:
        me = await client.me()
    assert me["name"] == "ZIE Service"
    assert route.last.headers["authorization"] == "Bearer tok-1"
    assert route.last.headers["user-agent"].startswith("zendesk-implementation-engine/")


async def test_token_is_reused_across_requests(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    tokens = zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/users/me.json", ME)
    async with zendesk.client(oauth_creds) as client:
        await client.me()
        await client.me()
    assert len(tokens.calls) == 1


async def test_retries_429_using_retry_after(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.on(
        "GET",
        "/api/v2/groups",
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(200, json={"groups": [], "meta": {"has_more": False}}),
    )
    sleep = FakeSleep()
    async with zendesk.client(oauth_creds, sleep) as client:
        assert await client.get("/api/v2/groups") == {"groups": [], "meta": {"has_more": False}}
    assert sleep.calls == [7.0]


async def test_gives_up_after_max_retries(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    route = zendesk.on("GET", "/api/v2/groups", httpx.Response(429, headers={"Retry-After": "1"}))
    sleep = FakeSleep()
    async with zendesk.client(oauth_creds, sleep, retries=2) as client:
        with pytest.raises(RateLimitError):
            await client.get("/api/v2/groups")
    assert len(route.calls) == 3
    assert sleep.calls == [1.0, 1.0]


async def test_server_errors_back_off_then_succeed(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.on(
        "GET",
        "/api/v2/groups",
        httpx.Response(502),
        httpx.Response(200, json={"groups": []}),
    )
    sleep = FakeSleep()
    async with zendesk.client(oauth_creds, sleep) as client:
        await client.get("/api/v2/groups")
    assert sleep.calls == [2.0]


async def test_refreshes_token_once_on_401(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token("old"), token("new"))
    route = zendesk.on(
        "GET",
        "/api/v2/users/me.json",
        httpx.Response(401, json={"error": "invalid_token"}),
        httpx.Response(200, json=ME),
    )
    async with zendesk.client(oauth_creds) as client:
        await client.me()
    assert [c.headers["authorization"] for c in route.calls] == ["Bearer old", "Bearer new"]


async def test_second_401_is_an_authentication_error(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/users/me.json", {"error": "invalid_token"}, status=401)
    async with zendesk.client(oauth_creds) as client:
        with pytest.raises(AuthenticationError):
            await client.me()


async def test_403_is_permission_denied(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/groups", {"error": "Forbidden"}, status=403)
    async with zendesk.client(oauth_creds) as client:
        with pytest.raises(PermissionDeniedError):
            await client.get("/api/v2/groups")


async def test_anonymous_user_is_rejected(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/users/me.json", {"user": {"id": None, "name": "Anonymous"}})
    async with zendesk.client(oauth_creds) as client:
        with pytest.raises(AuthenticationError):
            await client.me()


async def test_pagination_follows_next_links(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    page2 = f"{BASE}/api/v2/groups?page%5Bafter%5D=abc&page%5Bsize%5D=100"
    route = zendesk.on(
        "GET",
        "/api/v2/groups",
        httpx.Response(
            200,
            json={
                "groups": [{"id": 1, "name": "Tier 1"}, {"id": 2, "name": "Tier 2"}],
                "meta": {"has_more": True, "after_cursor": "abc"},
                "links": {"next": page2},
            },
        ),
        httpx.Response(
            200,
            json={
                "groups": [{"id": 3, "name": "Billing", "default": True}],
                "meta": {"has_more": False},
                "links": {"next": None},
            },
        ),
    )
    async with zendesk.client(oauth_creds) as client:
        groups = await read_groups(client)
    assert [g.name for g in groups] == ["Tier 1", "Tier 2", "Billing"]
    assert groups[2].default is True
    first, second = route.calls
    assert first.url.params["page[size]"] == "100"
    assert second.url.params["page[after]"] == "abc"


async def test_refuses_to_follow_links_to_other_hosts(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json(
        "GET",
        "/api/v2/groups",
        {
            "groups": [{"id": 1, "name": "Tier 1"}],
            "meta": {"has_more": True},
            "links": {"next": "https://evil.example.com/steal"},
        },
    )
    async with zendesk.client(oauth_creds) as client:
        with pytest.raises(ZendeskAPIError, match="outside"):
            await read_groups(client)


async def test_check_connection_reports_admin(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/users/me.json", ME)
    async with zendesk.client(oauth_creds) as client:
        info = await check_connection(client)
    assert info.subdomain == "acme"
    assert info.is_admin is True
    assert info.granted_scope == "read"
    assert info.warnings == []


async def test_check_connection_warns_for_agents_and_api_tokens(zendesk: FakeZendesk) -> None:
    creds = ApiTokenCredentials.model_validate(
        {"subdomain": "acme", "email": "agent@acme.test", "api_token": "abc"}
    )
    zendesk.json("GET", "/api/v2/users/me.json", {"user": {"id": 9, "name": "A", "role": "agent"}})
    async with ZendeskClient(creds, transport=zendesk.transport, sleep=FakeSleep()) as client:
        info = await check_connection(client)
    assert info.is_admin is False
    assert len(info.warnings) == 2
    assert "30 Apr 2027" in info.warnings[1]
