from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from tests.conftest import FakeSleep, FakeZendesk, token
from zie.readers.areas import AREAS, AREAS_BY_KEY
from zie.snapshot import SnapshotStore, SnapshotSummary, item_rows, take_snapshot
from zie.zendesk.auth import OAuthCredentials
from zie.zendesk.client import ZendeskClient
from zie.zendesk.errors import AuthenticationError

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 11, 2, 10, 30, 0, tzinfo=UTC)


def _client(creds: OAuthCredentials, zendesk: FakeZendesk) -> ZendeskClient:
    return ZendeskClient(creds, transport=zendesk.transport, sleep=FakeSleep(), max_retries=1)


async def test_snapshot_reports_status_per_area(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/groups", {"groups": [{"id": 1, "name": "Support"}]})
    zendesk.json("GET", "/api/v2/macros", {"macros": [{"id": 1}, {"id": 2}]})
    zendesk.json(
        "GET",
        "/api/v2/custom_roles",
        {"error": "Forbidden", "description": "Not on your plan"},
        status=403,
    )
    zendesk.on("GET", "/api/v2/views", httpx.Response(500))
    # Every other area is unregistered, so the fake answers 404 (not available).

    async with _client(oauth_creds, zendesk) as client:
        snapshot = await take_snapshot(client, now=NOW)

    assert snapshot.id == "20261102T103000Z"
    assert snapshot.subdomain == "acme"
    assert [a.key for a in snapshot.areas] == [a.key for a in AREAS]

    groups = snapshot.area("groups")
    assert groups is not None and groups.status == "ok" and groups.count == 1
    macros = snapshot.area("macros")
    assert macros is not None and macros.count == 2

    roles = snapshot.area("custom-roles")
    assert roles is not None and roles.status == "unavailable"
    assert "Enterprise plan or above" in (roles.message or "")

    views = snapshot.area("views")
    assert views is not None and views.status == "error"
    assert "500" in (views.message or "")

    brands = snapshot.area("brands")
    assert brands is not None and brands.status == "unavailable"

    summary = SnapshotSummary.of(snapshot)
    assert summary.areas_ok == 2
    assert summary.areas_total == 21
    assert summary.total_items == 3
    assert not hasattr(summary.areas[0], "items")


async def test_authentication_failure_aborts_the_snapshot(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.json("POST", "/oauth/tokens", {"error": "invalid_client"}, status=401)
    async with _client(oauth_creds, zendesk) as client:
        with pytest.raises(AuthenticationError):
            await take_snapshot(client, areas=[AREAS_BY_KEY["groups"]])


async def test_store_saves_and_returns_latest(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk, tmp_path: Path
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/groups", {"groups": [{"id": 1, "name": "Support"}]})
    store = SnapshotStore(tmp_path)
    assert store.latest("acme") is None

    async with _client(oauth_creds, zendesk) as client:
        older = await take_snapshot(
            client, areas=[AREAS_BY_KEY["groups"]], now=datetime(2026, 11, 1, tzinfo=UTC)
        )
        newer = await take_snapshot(client, areas=[AREAS_BY_KEY["groups"]], now=NOW)
    store.save(older)
    path = store.save(newer)

    assert path == tmp_path / "acme" / "20261102T103000Z.json"
    assert store.ids("acme") == ["20261102T103000Z", "20261101T000000Z"]
    latest = store.latest("acme")
    assert latest is not None and latest.id == newer.id
    assert latest.area("groups") == newer.area("groups")
    assert store.load("acme", "../../etc/passwd") is None


def test_item_rows_summarise_items() -> None:
    rows = item_rows(
        AREAS_BY_KEY["triggers"],
        [{"id": 7, "title": "Notify requester", "active": True, "updated_at": "2026-10-01"}],
    )
    assert rows[0].model_dump() == {
        "id": "7",
        "name": "Notify requester",
        "active": True,
        "updated_at": "2026-10-01",
        "used_by": None,
        "unused": None,
        "raw": {"id": 7, "title": "Notify requester", "active": True, "updated_at": "2026-10-01"},
    }


async def test_store_writes_summary_sidecars_and_caches(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk, tmp_path: Path
) -> None:
    zendesk.on("POST", "/oauth/tokens", token())
    zendesk.json("GET", "/api/v2/groups", {"groups": [{"id": 1, "name": "Support"}]})
    store = SnapshotStore(tmp_path)
    async with _client(oauth_creds, zendesk) as client:
        snapshot = await take_snapshot(client, areas=[AREAS_BY_KEY["groups"]], now=NOW)
    store.save(snapshot)
    assert (tmp_path / "acme" / "20261102T103000Z.summary.json").is_file()
    assert store.ids("acme") == ["20261102T103000Z"]  # sidecars are not snapshots
    assert store.load("acme", snapshot.id) is store.load("acme", snapshot.id)  # cached

    fresh = SnapshotStore(tmp_path)  # a new process: summaries come from the sidecar
    (tmp_path / "acme" / "20261102T103000Z.json").write_text("{broken", encoding="utf-8")
    summaries = fresh.summaries("acme")
    assert [s.id for s in summaries] == ["20261102T103000Z"]
    assert summaries[0].total_items == 1
