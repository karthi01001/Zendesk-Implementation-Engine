"""Credentials and authentication for the Zendesk API.

OAuth client credentials is the default. Zendesk stopped issuing new API tokens on
27 Oct 2026 and deactivates all remaining ones on 30 Apr 2027, so API tokens are only
a fallback for older accounts.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from collections.abc import Callable
from typing import Annotated, Literal, Protocol

import httpx
from pydantic import BaseModel, Field, SecretStr, field_validator

from zie.zendesk.errors import AuthenticationError, ConnectionFailedError, ZendeskAPIError

_SUBDOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

# Request read-only access unless a step genuinely needs to write (Plan & apply, Phase 4).
READ_SCOPE = "read"
READ_WRITE_SCOPE = "read write"


def normalize_subdomain(value: str) -> str:
    """Accept 'acme', 'acme.zendesk.com' or 'https://acme.zendesk.com/' and return 'acme'."""
    text = value.strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = text.split("/", 1)[0]
    if text.endswith(".zendesk.com"):
        text = text[: -len(".zendesk.com")]
    if not _SUBDOMAIN_RE.fullmatch(text):
        raise ValueError("Enter the Zendesk subdomain, for example 'acme' or 'acme.zendesk.com'.")
    return text


class _BaseCredentials(BaseModel):
    subdomain: str

    @field_validator("subdomain")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return normalize_subdomain(value)

    @property
    def base_url(self) -> str:
        return f"https://{self.subdomain}.zendesk.com"


class OAuthCredentials(_BaseCredentials):
    """A confidential OAuth client using the client-credentials grant."""

    auth_type: Literal["oauth"] = "oauth"
    client_id: str = Field(min_length=1)
    client_secret: SecretStr
    scope: str = READ_SCOPE


class ApiTokenCredentials(_BaseCredentials):
    """Legacy API token (email/token). Works only until 30 Apr 2027."""

    auth_type: Literal["api_token"] = "api_token"
    email: str = Field(min_length=3)
    api_token: SecretStr


Credentials = Annotated[OAuthCredentials | ApiTokenCredentials, Field(discriminator="auth_type")]


class AuthProvider(Protocol):
    async def auth_headers(self) -> dict[str, str]: ...

    def invalidate(self) -> bool:
        """Drop any cached token. Returns True if a retry with fresh auth makes sense."""
        ...


class OAuthTokenProvider:
    """Fetches and caches client-credentials access tokens.

    Zendesk issues no refresh token for this grant, so a new token is requested shortly
    before the current one expires, or after a 401.
    """

    def __init__(
        self,
        credentials: OAuthCredentials,
        http: httpx.AsyncClient,
        *,
        clock: Callable[[], float] = time.monotonic,
        refresh_margin_seconds: float = 60.0,
    ) -> None:
        self._credentials = credentials
        self._http = http
        self._clock = clock
        self._margin = refresh_margin_seconds
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        self.granted_scope: str | None = None

    def _is_valid(self) -> bool:
        return self._token is not None and self._clock() < self._expires_at - self._margin

    async def get_token(self) -> str:
        if self._is_valid():
            assert self._token is not None
            return self._token
        async with self._lock:
            if not self._is_valid():
                await self._fetch()
            assert self._token is not None
            return self._token

    async def _fetch(self) -> None:
        creds = self._credentials
        try:
            response = await self._http.post(
                f"{creds.base_url}/oauth/tokens",
                data={
                    "grant_type": "client_credentials",
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret.get_secret_value(),
                    "scope": creds.scope,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise ConnectionFailedError(
                f"Could not reach {creds.subdomain}.zendesk.com: {exc.__class__.__name__}"
            ) from exc

        if response.status_code in (400, 401, 403):
            raise AuthenticationError(
                _oauth_error_message(response), status_code=response.status_code
            )
        if response.status_code == 404:
            raise AuthenticationError(
                f"No Zendesk instance answered at {creds.subdomain}.zendesk.com.",
                status_code=404,
            )
        if response.status_code >= 400:
            raise ZendeskAPIError(
                f"Token request failed with HTTP {response.status_code}.",
                status_code=response.status_code,
            )

        payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise AuthenticationError("Zendesk returned no access token.")
        self._token = str(token)
        self._expires_at = self._clock() + float(payload.get("expires_in") or 1800)
        self.granted_scope = payload.get("scope")

    async def auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await self.get_token()}"}

    def invalidate(self) -> bool:
        self._token = None
        self._expires_at = 0.0
        return True


class ApiTokenAuth:
    """HTTP Basic auth with '{email}/token:{api_token}'."""

    def __init__(self, credentials: ApiTokenCredentials) -> None:
        raw = f"{credentials.email}/token:{credentials.api_token.get_secret_value()}"
        self._header = "Basic " + base64.b64encode(raw.encode()).decode()

    async def auth_headers(self) -> dict[str, str]:
        return {"Authorization": self._header}

    def invalidate(self) -> bool:
        return False  # Nothing to refresh; a 401 is final.


def make_auth_provider(
    credentials: OAuthCredentials | ApiTokenCredentials, http: httpx.AsyncClient
) -> OAuthTokenProvider | ApiTokenAuth:
    if isinstance(credentials, OAuthCredentials):
        return OAuthTokenProvider(credentials, http)
    return ApiTokenAuth(credentials)


def _oauth_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = body.get("error") if isinstance(body, dict) else None
    description = body.get("error_description") if isinstance(body, dict) else None
    if code == "invalid_client":
        return "Zendesk rejected the OAuth client ID or secret."
    if code == "invalid_scope":
        return "The OAuth client is not allowed to request this scope. Check its allowed scopes."
    if code == "unsupported_grant_type":
        return "This OAuth client cannot use client credentials. Make it a confidential client."
    if description:
        return f"Zendesk rejected the token request: {description}"
    return f"Zendesk rejected the token request (HTTP {response.status_code})."
