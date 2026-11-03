from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

pytest.importorskip("fastapi")

from tests.conftest import FakeSleep, FakeZendesk, token
from zie.api.app import create_app
from zie.config import Settings
from zie.snapshot import SnapshotStore
from zie.store import AppState, MemoryCredentialStore
from zie.zendesk.client import ZendeskClient

pytestmark = pytest.mark.anyio

ME = {"user": {"id": 7, "name": "ZIE Service", "email": "zie@acme.test", "role": "admin"}}
CONNECT = {
    "subdomain": "https://acme.zendesk.com/",
    "auth_type": "oauth",
    "client_id": "zie-engine",
    "client_secret": "s3cret",
}


@pytest.fixture
def store() -> MemoryCredentialStore:
    return MemoryCredentialStore()


@pytest.fixture
def state(tmp_path: Path) -> AppState:
    return AppState(tmp_path)


@pytest.fixture
async def api(
    store: MemoryCredentialStore, state: AppState, zendesk: FakeZendesk, tmp_path: Path
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(
        store=store,
        state=state,
        client_factory=lambda creds: ZendeskClient(
            creds, transport=zendesk.transport, sleep=FakeSleep()
        ),
        settings=Settings(frontend_dist=tmp_path / "no-ui"),
        snapshots=SnapshotStore(tmp_path / "snapshots"),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
        yield client


async def test_health(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/health")
    assert response.json()["status"] == "ok"


async def test_rejects_foreign_host_header(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/health", headers={"Host": "attacker.example.com"})
    assert response.status_code == 400


async def test_no_connection_yet(api: httpx.AsyncClient) -> None:
    assert (await api.get("/api/connection")).json() == {
        "active": False,
        "subdomain": None,
        "auth_type": None,
        "scope": None,
    }
    assert (await api.get("/api/config/groups")).status_code == 409


async def test_test_connection_does_not_save(
    api: httpx.AsyncClient, zendesk: FakeZendesk, store: MemoryCredentialStore
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/users/me.json", ME)
    response = await api.post("/api/connection/test", json=CONNECT)
    assert response.status_code == 200
    body = response.json()
    assert body["subdomain"] == "acme"
    assert body["is_admin"] is True
    assert body["warnings"] == []
    assert store.load("acme") is None


async def test_areas_are_listed_in_order(api: httpx.AsyncClient) -> None:
    areas = (await api.get("/api/areas")).json()
    assert len(areas) == 21
    assert areas[0] == {
        "key": "account-settings",
        "label": "Account settings",
        "section": "Account",
        "plan_note": None,
    }


async def test_connect_read_everything_and_browse(
    api: httpx.AsyncClient, zendesk: FakeZendesk, store: MemoryCredentialStore, state: AppState
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/users/me.json", ME)
    zendesk.json(
        "GET",
        "/api/v2/groups",
        {"groups": [{"id": 1, "name": "Support", "deleted": False}], "meta": {}},
    )
    # Other areas are not registered on the fake, so they come back as "unavailable".

    assert (await api.post("/api/connection", json=CONNECT)).status_code == 200
    assert state.active_subdomain == "acme"
    saved = store.load("acme")
    assert saved is not None and saved.auth_type == "oauth"

    active = (await api.get("/api/connection")).json()
    assert active == {"active": True, "subdomain": "acme", "auth_type": "oauth", "scope": "read"}
    assert "s3cret" not in str(active)

    assert (await api.get("/api/snapshots/latest")).json() == {"snapshot": None}
    assert (await api.get("/api/config/groups")).status_code == 409

    summary = (await api.post("/api/snapshots")).json()
    assert summary["subdomain"] == "acme"
    assert summary["areas_total"] == 21
    assert summary["areas_ok"] == 1
    assert summary["total_items"] == 1

    latest = (await api.get("/api/snapshots/latest")).json()["snapshot"]
    assert latest["id"] == summary["id"]

    groups = (await api.get("/api/config/groups")).json()
    assert groups["status"] == "ok"
    assert groups["count"] == 1
    assert groups["items"][0]["name"] == "Support"
    assert groups["items"][0]["active"] is True
    assert groups["items"][0]["raw"]["id"] == 1

    brands = (await api.get("/api/config/brands")).json()
    assert brands["status"] == "unavailable"
    assert brands["items"] == []

    assert (await api.get("/api/config/not-an-area")).status_code == 404

    assert (await api.delete("/api/connection")).status_code == 204
    assert store.load("acme") is None
    assert (await api.get("/api/connection")).json()["active"] is False


async def test_bad_secret_returns_readable_401(
    api: httpx.AsyncClient, zendesk: FakeZendesk, store: MemoryCredentialStore
) -> None:
    zendesk.json("POST", "/oauth/tokens", {"error": "invalid_client"}, status=401)
    response = await api.post("/api/connection", json=CONNECT)
    assert response.status_code == 401
    assert "client ID or secret" in response.json()["detail"]
    assert store.load("acme") is None


async def test_invalid_subdomain_is_422(api: httpx.AsyncClient) -> None:
    response = await api.post("/api/connection/test", json={**CONNECT, "subdomain": "not a domain"})
    assert response.status_code == 422
    assert "subdomain" in response.json()["detail"]


async def test_missing_secret_is_422(api: httpx.AsyncClient) -> None:
    response = await api.post("/api/connection/test", json={**CONNECT, "client_secret": ""})
    assert response.status_code == 422


async def test_dependencies_compare_and_reports(
    api: httpx.AsyncClient, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/users/me.json", ME)
    zendesk.json("GET", "/api/v2/groups", {"groups": [{"id": 1, "name": "Support"}]})
    zendesk.on(
        "GET",
        "/api/v2/triggers",
        httpx.Response(
            200,
            json={
                "triggers": [
                    {
                        "id": 9,
                        "title": "Route to support",
                        "active": True,
                        "conditions": {"all": [], "any": []},
                        "actions": [
                            {"field": "group_id", "value": "1"},
                            {"field": "set_tags", "value": "routed"},
                        ],
                    }
                ]
            },
        ),
        httpx.Response(
            200,
            json={
                "triggers": [
                    {
                        "id": 9,
                        "title": "Route to support",
                        "active": False,
                        "conditions": {"all": [], "any": []},
                        "actions": [{"field": "group_id", "value": "1"}],
                    }
                ]
            },
        ),
    )
    assert (await api.post("/api/connection", json=CONNECT)).status_code == 200
    assert (await api.get("/api/snapshots/compare")).status_code == 409
    first = (await api.post("/api/snapshots")).json()

    groups = (await api.get("/api/config/groups")).json()
    assert groups["items"][0]["used_by"] == 1
    # Macros, views and other source areas are not on the fake, so "unused" is unknown.
    assert groups["items"][0]["unused"] is None
    triggers = (await api.get("/api/config/triggers")).json()
    assert triggers["items"][0]["used_by"] is None

    deps = (await api.get("/api/dependencies/groups/1")).json()
    assert [r["source"]["name"] for r in deps["used_by"]] == ["Route to support"]
    uses = (await api.get("/api/dependencies/triggers/9")).json()["uses"]
    assert {r["target"]["area"] for r in uses} == {"groups", "tags"}
    assert (await api.get("/api/dependencies/tags/routed")).json()["used_by"][0]["context"] == (
        "action"
    )
    assert (await api.get("/api/dependencies/groups/404")).status_code == 404
    assert (await api.get("/api/tags")).json() == [{"tag": "routed", "used_by": 1}]

    summary = (await api.get("/api/dependencies/summary")).json()
    assert summary["broken"] == []
    assert "Macros" in summary["incomplete_areas"]
    assert summary["snapshot_id"] == first["id"]

    docx = await api.get("/api/reports/current-state")
    assert docx.status_code == 200
    assert docx.headers["content-disposition"].startswith('attachment; filename="zendesk-')
    assert docx.content[:2] == b"PK"  # a zip container, as every .docx is
    page = await api.get("/api/reports/current-state", params={"format": "html"})
    assert "Route to support" in page.text

    # A second read a moment later can be compared with the first.
    await asyncio.sleep(1.1)  # snapshot ids have one-second resolution
    second = (await api.post("/api/snapshots")).json()
    snapshots = (await api.get("/api/snapshots")).json()
    assert [s["id"] for s in snapshots] == [second["id"], first["id"]]
    diff = (await api.get("/api/snapshots/compare")).json()
    assert (diff["base_id"], diff["target_id"]) == (first["id"], second["id"])
    trigger_diff = next(a for a in diff["areas"] if a["key"] == "triggers")
    paths = [c["path"] for c in trigger_diff["changed"][0]["changes"]]
    assert paths == ["actions[1]", "active"]
