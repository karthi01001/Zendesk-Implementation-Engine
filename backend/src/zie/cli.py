"""`zie` command line: start the app, check a connection, export a configuration area.

zie serve                 start the local web app on http://127.0.0.1:8000
zie auth test             authenticate and show who the engine acts as
zie snapshot              read every area, save a snapshot, print the coverage table
zie snapshot groups       print one area live as YAML (or --format json)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Coroutine, Sequence
from typing import Any

import yaml

from zie import __version__
from zie.config import get_settings
from zie.connection import check_connection
from zie.readers.areas import AREAS, AREAS_BY_KEY, read_area
from zie.snapshot import SnapshotStore, take_snapshot
from zie.store import AppState, KeyringCredentialStore
from zie.zendesk.auth import ApiTokenCredentials, OAuthCredentials
from zie.zendesk.client import ZendeskClient
from zie.zendesk.errors import ZendeskError


class CliError(Exception):
    """A problem to report on stderr with a non-zero exit code."""


def resolve_credentials() -> OAuthCredentials | ApiTokenCredentials:
    """Use ZIE_* settings from the environment or .env first, then the app's active connection."""
    from_env = get_settings().credentials()
    if from_env:
        return from_env
    subdomain = AppState().active_subdomain
    stored = KeyringCredentialStore().load(subdomain) if subdomain else None
    if stored:
        return stored
    raise CliError(
        "No credentials found. Connect in the app, or set ZIE_SUBDOMAIN, ZIE_CLIENT_ID and "
        "ZIE_CLIENT_SECRET in backend/.env."
    )


async def _auth_test() -> None:
    async with ZendeskClient(resolve_credentials()) as client:
        info = await check_connection(client)
    print(f"Connected to {info.subdomain}.zendesk.com")
    print(f"  Acting as: {info.user_name} <{info.user_email}> (role: {info.role})")
    print(f"  Auth: {info.auth_type}; scope: {info.granted_scope or 'n/a'}")
    for warning in info.warnings:
        print(f"  Warning: {warning}")


async def _snapshot_all() -> None:
    async with ZendeskClient(resolve_credentials()) as client:
        snapshot = await take_snapshot(client)
    path = SnapshotStore().save(snapshot)
    width = max(len(a.label) for a in snapshot.areas)
    print(f"Read {snapshot.subdomain}.zendesk.com at {snapshot.taken_at:%Y-%m-%d %H:%M} UTC")
    for area in snapshot.areas:
        detail = f"{area.count} items" if area.status == "ok" else (area.message or "")
        print(f"  {area.label:<{width}}  {area.status:<11}  {detail}")
    ok = sum(1 for a in snapshot.areas if a.status == "ok")
    print(f"{ok} of {len(snapshot.areas)} areas read. Saved to {path}")


async def _snapshot_area(key: str, fmt: str) -> None:
    spec = AREAS_BY_KEY[key]
    async with ZendeskClient(resolve_credentials()) as client:
        items = await read_area(client, spec)
    data = {key: items}
    if fmt == "json":
        print(json.dumps(data, indent=2))
    else:
        print(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), end="")


def _serve(host: str | None, port: int | None, reload: bool) -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "zie.api.app:create_app",
        factory=True,
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="zie", description="Zendesk Implementation Engine")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="Start the local web app.")
    serve.add_argument("--host", help="Interface to bind (default 127.0.0.1).")
    serve.add_argument("--port", type=int, help="Port (default 8000).")
    serve.add_argument("--reload", action="store_true", help="Reload on code changes.")

    auth = commands.add_parser("auth", help="Check the connection to a Zendesk instance.")
    auth.add_subparsers(dest="auth_command", required=True).add_parser(
        "test", help="Authenticate and show who the engine acts as."
    )

    snapshot = commands.add_parser(
        "snapshot", help="Read every area (no argument) or print one area live."
    )
    snapshot.add_argument("area", nargs="?", choices=[a.key for a in AREAS], metavar="AREA")
    snapshot.add_argument("--format", choices=["yaml", "json"], default="yaml")
    return parser


def _run(coro: Coroutine[Any, Any, None]) -> None:
    asyncio.run(coro)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "serve":
            _serve(args.host, args.port, args.reload)
        elif args.command == "auth":
            _run(_auth_test())
        elif args.command == "snapshot":
            _run(_snapshot_area(args.area, args.format) if args.area else _snapshot_all())
    except (CliError, ZendeskError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
