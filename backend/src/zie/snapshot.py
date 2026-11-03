"""Read every configuration area into one snapshot, with a per-area coverage status.

Snapshots hold the customer's configuration, so they are stored outside the repo in the
user data folder (on Windows: %LOCALAPPDATA%\\zendesk-implementation-engine\\snapshots).
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from platformdirs import user_data_path
from pydantic import BaseModel

from zie import __version__
from zie.readers.areas import AREAS, AreaSpec, item_active, item_id, item_name, read_area
from zie.zendesk.client import ZendeskClient
from zie.zendesk.errors import (
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    ZendeskError,
)

AreaStatus = Literal["ok", "unavailable", "error"]


class AreaResult(BaseModel):
    key: str
    label: str
    section: str
    status: AreaStatus
    count: int = 0
    message: str | None = None
    duration_ms: int = 0
    items: list[dict[str, Any]] = []


class AreaSummary(BaseModel):
    key: str
    label: str
    section: str
    status: AreaStatus
    count: int
    message: str | None = None
    duration_ms: int


class Snapshot(BaseModel):
    id: str
    subdomain: str
    taken_at: datetime
    engine_version: str
    areas: list[AreaResult]

    def area(self, key: str) -> AreaResult | None:
        return next((a for a in self.areas if a.key == key), None)


class SnapshotSummary(BaseModel):
    id: str
    subdomain: str
    taken_at: datetime
    engine_version: str
    areas_ok: int
    areas_total: int
    total_items: int
    areas: list[AreaSummary]

    @classmethod
    def of(cls, snapshot: Snapshot) -> SnapshotSummary:
        return cls(
            id=snapshot.id,
            subdomain=snapshot.subdomain,
            taken_at=snapshot.taken_at,
            engine_version=snapshot.engine_version,
            areas_ok=sum(1 for a in snapshot.areas if a.status == "ok"),
            areas_total=len(snapshot.areas),
            total_items=sum(a.count for a in snapshot.areas),
            areas=[AreaSummary(**a.model_dump(exclude={"items"})) for a in snapshot.areas],
        )


class ItemRow(BaseModel):
    """One item as the explorer shows it: a few common fields plus the raw Zendesk object."""

    id: str
    name: str
    active: bool | None = None
    updated_at: str | None = None
    used_by: int | None = None
    #: True/False when known; None when the area cannot be "used" or coverage is incomplete.
    unused: bool | None = None
    raw: dict[str, Any]


def item_rows(
    spec: AreaSpec,
    items: list[dict[str, Any]],
    used_by: Callable[[str], int] | None = None,
    unused: Callable[[dict[str, Any]], bool | None] | None = None,
) -> list[ItemRow]:
    return [
        ItemRow(
            id=item_id(item),
            name=item_name(spec, item),
            active=item_active(spec, item),
            updated_at=str(item["updated_at"]) if item.get("updated_at") else None,
            used_by=used_by(item_id(item)) if used_by else None,
            unused=unused(item) if unused else None,
            raw=item,
        )
        for item in items
    ]


async def _read_one(client: ZendeskClient, spec: AreaSpec, gate: asyncio.Semaphore) -> AreaResult:
    started = time.perf_counter()
    status: AreaStatus = "ok"
    message: str | None = None
    items: list[dict[str, Any]] = []
    async with gate:
        try:
            items = await read_area(client, spec)
        except AuthenticationError:
            raise  # credentials stopped working: fail the whole snapshot loudly
        except (PermissionDeniedError, NotFoundError):
            status = "unavailable"
            message = "Not available on this account" + (
                f" ({spec.plan_note})." if spec.plan_note else " or not enabled."
            )
        except ZendeskError as exc:
            status, message = "error", exc.message
    return AreaResult(
        key=spec.key,
        label=spec.label,
        section=spec.section,
        status=status,
        count=len(items),
        message=message,
        duration_ms=int((time.perf_counter() - started) * 1000),
        items=items,
    )


async def take_snapshot(
    client: ZendeskClient,
    *,
    areas: list[AreaSpec] | None = None,
    concurrency: int = 4,
    now: datetime | None = None,
) -> Snapshot:
    """Read every area (a few at a time, to stay well inside the rate limit)."""
    taken_at = now or datetime.now(UTC)
    gate = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(*(_read_one(client, spec, gate) for spec in areas or AREAS))
    return Snapshot(
        id=taken_at.strftime("%Y%m%dT%H%M%SZ"),
        subdomain=client.credentials.subdomain,
        taken_at=taken_at,
        engine_version=__version__,
        areas=list(results),
    )


_ID_RE = re.compile(r"^\d{8}T\d{6}Z$")


class SnapshotStore:
    """One JSON file per snapshot under <root>/<subdomain>/."""

    CACHE_SIZE = 3

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or user_data_path("zendesk-implementation-engine", appauthor=False) / (
            "snapshots"
        )
        # Saved snapshots never change on disk except through save(), so parsed copies of the
        # few most recently used ones are kept in memory.
        self._cache: dict[tuple[str, str], Snapshot] = {}

    def _remember(self, snapshot: Snapshot) -> None:
        key = (snapshot.subdomain, snapshot.id)
        self._cache.pop(key, None)
        self._cache[key] = snapshot
        while len(self._cache) > self.CACHE_SIZE:
            self._cache.pop(next(iter(self._cache)))

    def _dir(self, subdomain: str) -> Path:
        return self.root / subdomain

    def save(self, snapshot: Snapshot) -> Path:
        directory = self._dir(snapshot.subdomain)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{snapshot.id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)
        self._write_summary(SnapshotSummary.of(snapshot))
        self._remember(snapshot)
        return path

    def _summary_path(self, subdomain: str, snapshot_id: str) -> Path:
        return self._dir(subdomain) / f"{snapshot_id}.summary.json"

    def _write_summary(self, summary: SnapshotSummary) -> None:
        self._summary_path(summary.subdomain, summary.id).write_text(
            summary.model_dump_json(), encoding="utf-8"
        )

    def ids(self, subdomain: str) -> list[str]:
        directory = self._dir(subdomain)
        if not directory.is_dir():
            return []
        return sorted(
            (p.stem for p in directory.glob("*.json") if _ID_RE.fullmatch(p.stem)), reverse=True
        )

    def load(self, subdomain: str, snapshot_id: str) -> Snapshot | None:
        if not _ID_RE.fullmatch(snapshot_id):
            return None
        cached = self._cache.get((subdomain, snapshot_id))
        if cached is not None:
            self._remember(cached)
            return cached
        path = self._dir(subdomain) / f"{snapshot_id}.json"
        if not path.is_file():
            return None
        snapshot = Snapshot.model_validate(json.loads(path.read_text(encoding="utf-8")))
        self._remember(snapshot)
        return snapshot

    def summaries(self, subdomain: str, limit: int = 50) -> list[SnapshotSummary]:
        """Newest first. Unreadable files are skipped."""
        found: list[SnapshotSummary] = []
        for snapshot_id in self.ids(subdomain)[:limit]:
            sidecar = self._summary_path(subdomain, snapshot_id)
            try:
                if sidecar.is_file():
                    found.append(SnapshotSummary.model_validate_json(sidecar.read_text("utf-8")))
                    continue
                snapshot = self.load(subdomain, snapshot_id)  # older reads have no sidecar yet
            except (OSError, ValueError):
                continue
            if snapshot is not None:
                summary = SnapshotSummary.of(snapshot)
                self._write_summary(summary)
                found.append(summary)
        return found

    def latest(self, subdomain: str) -> Snapshot | None:
        for snapshot_id in self.ids(subdomain):
            snapshot = self.load(subdomain, snapshot_id)
            if snapshot is not None:
                return snapshot
        return None
