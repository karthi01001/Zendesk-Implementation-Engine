"""Async Zendesk API client: auth, retries on rate limits, and cursor pagination."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from types import TracebackType
from typing import Any

import httpx

from zie import __version__
from zie.zendesk.auth import (
    ApiTokenCredentials,
    OAuthCredentials,
    OAuthTokenProvider,
    make_auth_provider,
)
from zie.zendesk.errors import (
    AuthenticationError,
    ConnectionFailedError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ZendeskAPIError,
)

SleepFn = Callable[[float], Awaitable[None]]

_RETRY_STATUSES = {429, 503}
_TRANSIENT_STATUSES = {500, 502, 504}


class ZendeskClient:
    """One client per Zendesk instance. Use as an async context manager."""

    def __init__(
        self,
        credentials: OAuthCredentials | ApiTokenCredentials,
        *,
        http: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 5,
        max_wait_seconds: float = 60.0,
        sleep: SleepFn = asyncio.sleep,
    ) -> None:
        """Pass `http` to share a client you manage, or `transport` (e.g. a mock) to own one."""
        self.credentials = credentials
        self.base_url = credentials.base_url
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30.0),
            headers={"User-Agent": f"zendesk-implementation-engine/{__version__}"},
        )
        self._auth = make_auth_provider(credentials, self._http)
        self._max_retries = max_retries
        self._max_wait = max_wait_seconds
        self._sleep = sleep

    async def __aenter__(self) -> ZendeskClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    @property
    def granted_scope(self) -> str | None:
        if isinstance(self._auth, OAuthTokenProvider):
            return self._auth.granted_scope
        return None

    def _url(self, path_or_url: str) -> str:
        if path_or_url.startswith("http"):
            # Never send this instance's credentials to another host.
            if not path_or_url.startswith(self.base_url + "/"):
                raise ZendeskAPIError(f"Refusing to call a URL outside {self.base_url}.")
            return path_or_url
        return self.base_url + path_or_url

    async def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> dict[str, Any]:
        url = self._url(path_or_url)
        auth_retried = False
        attempt = 0
        while True:
            headers = {"Accept": "application/json", **await self._auth.auth_headers()}
            try:
                response = await self._http.request(
                    method, url, params=params, json=json, headers=headers
                )
            except httpx.HTTPError as exc:
                if attempt < self._max_retries:
                    attempt += 1
                    await self._sleep(min(2.0**attempt, self._max_wait))
                    continue
                raise ConnectionFailedError(
                    f"Could not reach {self.base_url}: {exc.__class__.__name__}"
                ) from exc

            status = response.status_code
            if status == 401 and not auth_retried and self._auth.invalidate():
                auth_retried = True
                continue
            if status in _RETRY_STATUSES or status in _TRANSIENT_STATUSES:
                if attempt >= self._max_retries:
                    if status in _RETRY_STATUSES:
                        raise RateLimitError(
                            "Zendesk is rate-limiting this account; try again shortly.",
                            status_code=status,
                        )
                    raise ZendeskAPIError(
                        f"Zendesk returned HTTP {status} after {attempt} retries.",
                        status_code=status,
                    )
                attempt += 1
                await self._sleep(self._wait_seconds(response, attempt))
                continue
            if status >= 400:
                raise _error_for(response)
            if status == 204 or not response.content:
                return {}
            data = response.json()
            return data if isinstance(data, dict) else {"data": data}

    def _wait_seconds(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            try:
                return min(max(float(retry_after), 0.0), self._max_wait)
            except ValueError:
                pass
        return min(2.0**attempt, self._max_wait)

    async def get(self, path_or_url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.request("GET", path_or_url, params=params)

    async def paginate(
        self,
        path: str,
        key: str,
        *,
        page_size: int = 100,
        params: dict[str, Any] | None = None,
        cursor: bool = True,
        max_pages: int = 1000,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield every item under `key`, following whichever pagination the endpoint uses.

        With `cursor=True` the first request opts in to cursor pagination (`page[size]`) and
        follows `links.next` while `meta.has_more`. Endpoints without cursor support are read
        with `cursor=False`; if a response still carries an offset `next_page` URL, it is
        followed too.
        """
        next_url: str = path
        first_params: dict[str, Any] = dict(params or {})
        if cursor:
            first_params["page[size]"] = page_size
        next_params: dict[str, Any] | None = first_params
        seen: set[str] = set()
        for _ in range(max_pages):
            data = await self.get(next_url, params=next_params)
            for item in data.get(key) or []:
                yield item
            meta = data.get("meta") or {}
            link = (data.get("links") or {}).get("next")
            offset_next = data.get("next_page")
            if meta.get("has_more") and link:
                candidate = str(link)
            elif isinstance(offset_next, str) and offset_next:
                candidate = offset_next
            else:
                return
            if candidate in seen:  # a page pointing at itself would loop forever
                return
            seen.add(candidate)
            next_url, next_params = candidate, None
        raise ZendeskAPIError(f"Stopped after {max_pages} pages of {path}.")

    async def me(self) -> dict[str, Any]:
        data = await self.get("/api/v2/users/me.json")
        user = data.get("user") or {}
        if user.get("id") is None:
            raise AuthenticationError("Zendesk treated this request as an anonymous user.")
        return dict(user)


def _error_for(response: httpx.Response) -> Exception:
    status = response.status_code
    detail = _describe(response)
    if status == 401:
        return AuthenticationError(f"Zendesk rejected the credentials. {detail}", status_code=401)
    if status == 403:
        return PermissionDeniedError(
            f"The account or OAuth scope is not allowed to do this. {detail}", status_code=403
        )
    if status == 404:
        return NotFoundError(f"Not found: {response.request.url.path}", status_code=404)
    return ZendeskAPIError(f"Zendesk returned HTTP {status}. {detail}", status_code=status)


def _describe(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return ""
    if isinstance(body, dict):
        for key in ("description", "error_description", "error", "details"):
            value = body.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict) and isinstance(value.get("message"), str):
                return str(value["message"])
    return ""
