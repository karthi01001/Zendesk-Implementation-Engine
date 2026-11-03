from __future__ import annotations

import base64
from urllib.parse import parse_qs

import httpx
import pytest

from tests.conftest import FakeZendesk, token
from zie.zendesk.auth import (
    ApiTokenAuth,
    ApiTokenCredentials,
    OAuthCredentials,
    OAuthTokenProvider,
    normalize_subdomain,
)
from zie.zendesk.errors import AuthenticationError


@pytest.mark.parametrize(
    "raw",
    [
        "acme",
        "ACME",
        " acme.zendesk.com ",
        "https://acme.zendesk.com/",
        "https://acme.zendesk.com/agent/dashboard",
    ],
)
def test_normalize_subdomain_accepts_common_forms(raw: str) -> None:
    assert normalize_subdomain(raw) == "acme"


def test_normalize_subdomain_keeps_hyphens_and_digits() -> None:
    assert normalize_subdomain("pdi-nagarro6612.zendesk.com") == "pdi-nagarro6612"


@pytest.mark.parametrize("raw", ["", "-acme", "acme_corp", "acme.example.com", "a b"])
def test_normalize_subdomain_rejects_invalid(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_subdomain(raw)


@pytest.mark.anyio
async def test_token_request_is_form_encoded_and_read_only(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    route = zendesk.on("POST", "/oauth/tokens", token())
    async with zendesk.http() as http:
        provider = OAuthTokenProvider(oauth_creds, http)
        assert await provider.auth_headers() == {"Authorization": "Bearer tok-1"}

    request = route.last
    assert request.headers["content-type"] == "application/x-www-form-urlencoded"
    assert parse_qs(request.content.decode()) == {
        "grant_type": ["client_credentials"],
        "client_id": ["zie-engine"],
        "client_secret": ["s3cret"],
        "scope": ["read"],
    }
    assert provider.granted_scope == "read"


@pytest.mark.anyio
async def test_token_is_cached_until_close_to_expiry(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    now = [1000.0]
    route = zendesk.on("POST", "/oauth/tokens", token("tok-1"), token("tok-2"))
    async with zendesk.http() as http:
        provider = OAuthTokenProvider(oauth_creds, http, clock=lambda: now[0])
        assert await provider.get_token() == "tok-1"
        now[0] += 1700  # 100 s left: more than the 60 s margin, keep it
        assert await provider.get_token() == "tok-1"
        now[0] += 50  # 50 s left: inside the margin, renew
        assert await provider.get_token() == "tok-2"
    assert len(route.calls) == 2


@pytest.mark.anyio
async def test_invalid_client_gives_clear_message(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.json("POST", "/oauth/tokens", {"error": "invalid_client"}, status=401)
    async with zendesk.http() as http:
        with pytest.raises(AuthenticationError, match="client ID or secret"):
            await OAuthTokenProvider(oauth_creds, http).get_token()


@pytest.mark.anyio
async def test_invalid_scope_gives_clear_message(
    oauth_creds: OAuthCredentials, zendesk: FakeZendesk
) -> None:
    zendesk.json("POST", "/oauth/tokens", {"error": "invalid_scope"}, status=400)
    async with zendesk.http() as http:
        with pytest.raises(AuthenticationError, match="allowed scopes"):
            await OAuthTokenProvider(oauth_creds, http).get_token()


@pytest.mark.anyio
async def test_unknown_subdomain_is_reported(oauth_creds: OAuthCredentials) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(404, text="Not found"))
    ) as http:
        with pytest.raises(AuthenticationError, match=r"acme\.zendesk\.com"):
            await OAuthTokenProvider(oauth_creds, http).get_token()


@pytest.mark.anyio
async def test_api_token_uses_basic_auth() -> None:
    creds = ApiTokenCredentials.model_validate(
        {"subdomain": "acme", "email": "admin@acme.test", "api_token": "abc123"}
    )
    headers = await ApiTokenAuth(creds).auth_headers()
    expected = base64.b64encode(b"admin@acme.test/token:abc123").decode()
    assert headers == {"Authorization": f"Basic {expected}"}


def test_secrets_are_masked_in_repr_and_json(oauth_creds: OAuthCredentials) -> None:
    assert "s3cret" not in repr(oauth_creds)
    assert "s3cret" not in oauth_creds.model_dump_json()
