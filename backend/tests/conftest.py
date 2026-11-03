"""Shared test helpers. No test talks to a real Zendesk instance."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

import httpx
import pytest

from zie.zendesk.auth import OAuthCredentials
from zie.zendesk.client import ZendeskClient

BASE = "https://acme.zendesk.com"

Reply = httpx.Response | Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@dataclass
class Route:
    replies: list[Reply]
    repeat_last: bool = True
    calls: list[httpx.Request] = field(default_factory=list)

    @property
    def last(self) -> httpx.Request:
        return self.calls[-1]


class FakeZendesk:
    """A tiny programmable Zendesk: register replies per (method, path), inspect calls."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Route] = {}

    def on(self, method: str, path: str, *replies: Reply) -> Route:
        route = Route(list(replies))
        self.routes[(method.upper(), path)] = route
        return route

    def json(self, method: str, path: str, body: object, status: int = 200) -> Route:
        return self.on(method, path, httpx.Response(status, json=body))

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert request.url.host == "acme.zendesk.com", f"unexpected host {request.url.host}"
        route = self.routes.get((request.method, request.url.path))
        if route is None:
            return httpx.Response(404, json={"error": "RecordNotFound"})
        route.calls.append(request)
        index = len(route.calls) - 1
        reply = route.replies[index] if index < len(route.replies) else route.replies[-1]
        return reply(request) if callable(reply) else reply

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def http(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self.transport)

    def client(
        self, creds: OAuthCredentials, sleep: FakeSleep | None = None, retries: int = 3
    ) -> ZendeskClient:
        return ZendeskClient(
            creds, transport=self.transport, sleep=sleep or FakeSleep(), max_retries=retries
        )


@pytest.fixture
def zendesk() -> FakeZendesk:
    return FakeZendesk()


@pytest.fixture
def oauth_creds() -> OAuthCredentials:
    return OAuthCredentials.model_validate(
        {"subdomain": "acme", "client_id": "zie-engine", "client_secret": "s3cret"}
    )


def token_response(token: str = "tok-1", expires_in: int = 1800) -> dict[str, object]:
    return {
        "access_token": token,
        "token_type": "bearer",
        "scope": "read",
        "expires_in": expires_in,
    }


def token(token: str = "tok-1", expires_in: int = 1800) -> httpx.Response:
    return httpx.Response(200, json=token_response(token, expires_in))


class FakeSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
