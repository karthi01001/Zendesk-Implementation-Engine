"""FastAPI backend for the local web app. Binds to localhost only; secrets never leave it."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from zie import __version__
from zie.compare import SnapshotDiff, compare_snapshots
from zie.config import Settings, get_settings
from zie.connection import ConnectionInfo, check_connection
from zie.dependencies import (
    TAGS,
    TARGET_AREAS,
    DependencyGraph,
    ItemDependencies,
    ItemKey,
    Reference,
    TagUsage,
    item_key,
    unused_custom_ticket_fields,
)
from zie.readers.areas import AREAS_BY_KEY, AreaInfo, area_infos
from zie.report import build_report, render_docx, render_html, report_filename
from zie.snapshot import (
    ItemRow,
    Snapshot,
    SnapshotStore,
    SnapshotSummary,
    item_rows,
    take_snapshot,
)
from zie.store import AppState, CredentialStore, KeyringCredentialStore
from zie.zendesk.auth import READ_SCOPE, ApiTokenCredentials, OAuthCredentials
from zie.zendesk.client import ZendeskClient
from zie.zendesk.errors import (
    AuthenticationError,
    ConnectionFailedError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ZendeskError,
)

ClientFactory = Callable[[OAuthCredentials | ApiTokenCredentials], ZendeskClient]

_REPO_FRONTEND_DIST = Path(__file__).resolve().parents[4] / "frontend" / "dist"


class ConnectRequest(BaseModel):
    subdomain: str
    auth_type: Literal["oauth", "api_token"] = "oauth"
    client_id: str | None = None
    client_secret: str | None = None
    scope: str = READ_SCOPE
    email: str | None = None
    api_token: str | None = None

    def to_credentials(self) -> OAuthCredentials | ApiTokenCredentials:
        if self.auth_type == "oauth":
            if not self.client_id or not self.client_secret:
                raise HTTPException(422, "Enter the OAuth client ID and secret.")
            return OAuthCredentials.model_validate(
                {
                    "subdomain": self.subdomain,
                    "client_id": self.client_id.strip(),
                    "client_secret": self.client_secret.strip(),
                    "scope": self.scope,
                }
            )
        if not self.email or not self.api_token:
            raise HTTPException(422, "Enter the admin email and API token.")
        return ApiTokenCredentials.model_validate(
            {
                "subdomain": self.subdomain,
                "email": self.email.strip(),
                "api_token": self.api_token.strip(),
            }
        )


class ActiveConnection(BaseModel):
    active: bool
    subdomain: str | None = None
    auth_type: Literal["oauth", "api_token"] | None = None
    scope: str | None = None


class LatestSnapshot(BaseModel):
    snapshot: SnapshotSummary | None = None


class DependencySummary(BaseModel):
    snapshot_id: str
    references: int
    tags: int
    broken: list[Reference]
    unused_ticket_fields: list[ItemKey]
    #: Areas that were not read; while non-empty, unused items cannot be determined.
    incomplete_areas: list[str]


class AreaData(BaseModel):
    key: str
    label: str
    section: str
    plan_note: str | None = None
    snapshot_id: str
    taken_at: datetime
    status: Literal["ok", "unavailable", "error"]
    message: str | None = None
    count: int
    items: list[ItemRow]


def _status_for(exc: ZendeskError) -> int:
    if isinstance(exc, AuthenticationError):
        return 401
    if isinstance(exc, PermissionDeniedError):
        return 403
    if isinstance(exc, NotFoundError):
        return 404
    if isinstance(exc, RateLimitError):
        return 429
    if isinstance(exc, ConnectionFailedError):
        return 504
    return 502


def create_app(
    *,
    store: CredentialStore | None = None,
    state: AppState | None = None,
    client_factory: ClientFactory | None = None,
    settings: Settings | None = None,
    snapshots: SnapshotStore | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    credential_store: CredentialStore = store or KeyringCredentialStore()
    app_state = state or AppState()
    snapshot_store = snapshots or SnapshotStore()
    reading = asyncio.Lock()
    graphs: dict[str, DependencyGraph] = {}

    def graph_for(snapshot: Snapshot) -> DependencyGraph:
        if snapshot.id not in graphs:
            graphs.clear()  # keep only the snapshot in use
            graphs[snapshot.id] = DependencyGraph.build(snapshot)
        return graphs[snapshot.id]

    def load_snapshot(snapshot_id: str | None = None) -> Snapshot:
        subdomain = _active().subdomain
        snapshot = (
            snapshot_store.load(subdomain, snapshot_id)
            if snapshot_id
            else snapshot_store.latest(subdomain)
        )
        if snapshot is None:
            raise HTTPException(
                409 if snapshot_id is None else 404,
                "Nothing has been read yet. Click 'Read everything' first."
                if snapshot_id is None
                else f"Snapshot {snapshot_id} was not found.",
            )
        return snapshot

    make_client: ClientFactory = client_factory or (lambda creds: ZendeskClient(creds))

    app = FastAPI(title="Zendesk Implementation Engine", version=__version__)
    # Only answer requests addressed to this machine (blocks DNS-rebinding tricks).
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )

    @app.exception_handler(ZendeskError)
    async def _zendesk_error(_: Request, exc: ZendeskError) -> JSONResponse:
        return JSONResponse(
            status_code=_status_for(exc),
            content={"detail": exc.message, "kind": type(exc).__name__},
        )

    def _credentials(body: ConnectRequest) -> OAuthCredentials | ApiTokenCredentials:
        try:
            return body.to_credentials()
        except ValidationError as exc:
            first = exc.errors()[0]
            message = str(first.get("msg", "Invalid input")).removeprefix("Value error, ")
            raise HTTPException(422, message) from exc

    def _active() -> OAuthCredentials | ApiTokenCredentials:
        subdomain = app_state.active_subdomain
        if not subdomain:
            raise HTTPException(409, "No Zendesk instance is connected yet.")
        creds = credential_store.load(subdomain)
        if creds is None:
            raise HTTPException(409, f"Credentials for {subdomain} are missing. Connect again.")
        return creds

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.post("/api/connection/test")
    async def test_connection(body: ConnectRequest) -> ConnectionInfo:
        async with make_client(_credentials(body)) as client:
            return await check_connection(client)

    @app.post("/api/connection")
    async def connect(body: ConnectRequest) -> ConnectionInfo:
        creds = _credentials(body)
        async with make_client(creds) as client:
            info = await check_connection(client)
        credential_store.save(creds)
        app_state.set_active_subdomain(creds.subdomain)
        return info

    @app.get("/api/connection")
    async def active_connection() -> ActiveConnection:
        subdomain = app_state.active_subdomain
        creds = credential_store.load(subdomain) if subdomain else None
        if creds is None:
            return ActiveConnection(active=False)
        scope = creds.scope if isinstance(creds, OAuthCredentials) else None
        return ActiveConnection(
            active=True, subdomain=creds.subdomain, auth_type=creds.auth_type, scope=scope
        )

    @app.delete("/api/connection", status_code=204)
    async def disconnect() -> Response:
        subdomain = app_state.active_subdomain
        if subdomain:
            credential_store.delete(subdomain)
        app_state.clear_active_subdomain()
        return Response(status_code=204)

    @app.get("/api/areas")
    async def areas() -> list[AreaInfo]:
        return area_infos()

    @app.post("/api/snapshots")
    async def read_everything() -> SnapshotSummary:
        creds = _active()
        if reading.locked():
            raise HTTPException(409, "A read is already running. Wait for it to finish.")
        async with reading:
            async with make_client(creds) as client:
                snapshot = await take_snapshot(client)
            snapshot_store.save(snapshot)
            graphs.clear()  # a read within the same second reuses the snapshot id
        return SnapshotSummary.of(snapshot)

    @app.get("/api/snapshots/latest")
    async def latest_snapshot() -> LatestSnapshot:
        snapshot = snapshot_store.latest(_active().subdomain)
        return LatestSnapshot(snapshot=SnapshotSummary.of(snapshot) if snapshot else None)

    @app.get("/api/config/{area_key}")
    async def area_data(area_key: str) -> AreaData:
        spec = AREAS_BY_KEY.get(area_key)
        if spec is None:
            raise HTTPException(404, f"Unknown configuration area '{area_key}'.")
        snapshot = load_snapshot()
        result = snapshot.area(area_key)
        if result is None:
            raise HTTPException(
                409, f"The latest read has no '{spec.label}'. Click 'Read everything' again."
            )
        graph = graph_for(snapshot)
        return AreaData(
            key=spec.key,
            label=spec.label,
            section=spec.section,
            plan_note=spec.plan_note,
            snapshot_id=snapshot.id,
            taken_at=snapshot.taken_at,
            status=result.status,
            message=result.message,
            count=result.count,
            items=item_rows(
                spec,
                result.items,
                (lambda iid: graph.used_by_count(area_key, iid))
                if area_key in TARGET_AREAS
                else None,
                (lambda item: graph.is_unused(area_key, item))
                if area_key in TARGET_AREAS
                else None,
            ),
        )

    @app.get("/api/snapshots")
    async def snapshot_list() -> list[SnapshotSummary]:
        return snapshot_store.summaries(_active().subdomain)

    @app.get("/api/snapshots/compare")
    async def snapshot_compare(
        base: str | None = Query(default=None), target: str | None = Query(default=None)
    ) -> SnapshotDiff:
        ids = snapshot_store.ids(_active().subdomain)  # newest first
        target_id = target or (ids[0] if ids else None)
        # Default base: the read just before the target.
        base_id = base or next((i for i in ids if target_id and i < target_id), None)
        if not target_id or not base_id:
            raise HTTPException(409, "Read the instance at least twice to compare.")
        return compare_snapshots(load_snapshot(base_id), load_snapshot(target_id))

    @app.get("/api/dependencies/summary")
    async def dependency_summary() -> DependencySummary:
        snapshot = load_snapshot()
        graph = graph_for(snapshot)
        return DependencySummary(
            snapshot_id=snapshot.id,
            references=len(graph.references),
            tags=len(graph.tags()),
            broken=graph.broken(),
            unused_ticket_fields=unused_custom_ticket_fields(snapshot, graph),
            incomplete_areas=graph.incomplete_areas,
        )

    @app.get("/api/tags")
    async def tags() -> list[TagUsage]:
        return graph_for(load_snapshot()).tags()

    @app.get("/api/dependencies/{area_key}/{item_id:path}")
    async def dependencies(area_key: str, item_id: str) -> ItemDependencies:
        if area_key != TAGS and area_key not in AREAS_BY_KEY:
            raise HTTPException(404, f"Unknown configuration area '{area_key}'.")
        snapshot = load_snapshot()
        key = item_key(snapshot, area_key, item_id)
        if key is None:
            raise HTTPException(404, f"No item {item_id} in {area_key} in the latest read.")
        return graph_for(snapshot).for_item(key)

    @app.get("/api/reports/current-state")
    async def current_state_report(
        format: Literal["docx", "html"] = Query(default="docx"),
        snapshot: str | None = Query(default=None),
    ) -> Response:
        source = load_snapshot(snapshot)
        graph = graph_for(source)
        # Building a large report takes a moment; keep the server responsive meanwhile.
        report = await asyncio.to_thread(build_report, source, graph)
        if format == "html":
            return Response(
                await asyncio.to_thread(render_html, report),
                media_type="text/html; charset=utf-8",
                headers={
                    "Content-Disposition": f'inline; filename="{report_filename(report, "html")}"'
                },
            )
        return Response(
            await asyncio.to_thread(render_docx, report),
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={
                "Content-Disposition": f'attachment; filename="{report_filename(report, "docx")}"'
            },
        )

    dist = settings.frontend_dist or _REPO_FRONTEND_DIST
    if (dist / "index.html").exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="ui")

    return app
