"""Where credentials and local app state live.

Secrets go to the operating system's credential store (Windows Credential Manager,
macOS Keychain, Secret Service on Linux) through `keyring`. They are never written to
disk in plain text and never sent back to the browser.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Protocol

import keyring
import keyring.errors
from platformdirs import user_data_path
from pydantic import TypeAdapter

from zie.zendesk.auth import ApiTokenCredentials, Credentials, OAuthCredentials

KEYRING_SERVICE = "zendesk-implementation-engine"

_credentials_adapter: TypeAdapter[OAuthCredentials | ApiTokenCredentials] = TypeAdapter(Credentials)


def credentials_to_json(credentials: OAuthCredentials | ApiTokenCredentials) -> str:
    data = credentials.model_dump()
    if isinstance(credentials, OAuthCredentials):
        data["client_secret"] = credentials.client_secret.get_secret_value()
    else:
        data["api_token"] = credentials.api_token.get_secret_value()
    return json.dumps(data)


def credentials_from_json(raw: str) -> OAuthCredentials | ApiTokenCredentials:
    return _credentials_adapter.validate_json(raw)


class CredentialStore(Protocol):
    def save(self, credentials: OAuthCredentials | ApiTokenCredentials) -> None: ...

    def load(self, subdomain: str) -> OAuthCredentials | ApiTokenCredentials | None: ...

    def delete(self, subdomain: str) -> None: ...


class KeyringCredentialStore:
    """Stores one credential set per subdomain in the OS credential store."""

    def save(self, credentials: OAuthCredentials | ApiTokenCredentials) -> None:
        keyring.set_password(
            KEYRING_SERVICE, credentials.subdomain, credentials_to_json(credentials)
        )

    def load(self, subdomain: str) -> OAuthCredentials | ApiTokenCredentials | None:
        raw = keyring.get_password(KEYRING_SERVICE, subdomain)
        return credentials_from_json(raw) if raw else None

    def delete(self, subdomain: str) -> None:
        with contextlib.suppress(keyring.errors.PasswordDeleteError):
            keyring.delete_password(KEYRING_SERVICE, subdomain)


class MemoryCredentialStore:
    """In-memory store for tests."""

    def __init__(self) -> None:
        self._items: dict[str, str] = {}

    def save(self, credentials: OAuthCredentials | ApiTokenCredentials) -> None:
        self._items[credentials.subdomain] = credentials_to_json(credentials)

    def load(self, subdomain: str) -> OAuthCredentials | ApiTokenCredentials | None:
        raw = self._items.get(subdomain)
        return credentials_from_json(raw) if raw else None

    def delete(self, subdomain: str) -> None:
        self._items.pop(subdomain, None)


class AppState:
    """Small non-secret state: which instance is active. Stored as JSON in the user data dir."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or user_data_path(
            "zendesk-implementation-engine", appauthor=False
        )
        self.path = self.directory / "state.json"

    def _read(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write(self, data: dict[str, str]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    @property
    def active_subdomain(self) -> str | None:
        return self._read().get("active_subdomain")

    def set_active_subdomain(self, subdomain: str) -> None:
        data = self._read()
        data["active_subdomain"] = subdomain
        self._write(data)

    def clear_active_subdomain(self) -> None:
        data = self._read()
        data.pop("active_subdomain", None)
        self._write(data)
