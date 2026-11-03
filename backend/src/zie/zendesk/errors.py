"""Errors raised by the Zendesk client. Messages are safe to show in the UI (no secrets)."""

from __future__ import annotations


class ZendeskError(Exception):
    """Base class for every error the Zendesk client raises."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthenticationError(ZendeskError):
    """Zendesk rejected the credentials (bad client ID/secret, revoked token, wrong subdomain)."""


class PermissionDeniedError(ZendeskError):
    """Credentials are valid but lack the role or OAuth scope for this request."""


class NotFoundError(ZendeskError):
    """The subdomain or resource does not exist."""


class RateLimitError(ZendeskError):
    """Zendesk kept answering 429/503 after every allowed retry."""


class ZendeskAPIError(ZendeskError):
    """Any other unexpected response from Zendesk."""


class ConnectionFailedError(ZendeskError):
    """The instance could not be reached at all (DNS, TLS, timeout)."""
