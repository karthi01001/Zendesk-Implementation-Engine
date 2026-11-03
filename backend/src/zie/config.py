"""Runtime settings from environment variables (prefix ZIE_) or a local `.env` file.

Environment variables win over `.env`. The `.env` file is only for the CLI and scripted
runs; the web UI stores credentials in the OS credential store instead.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, SecretStr

from zie.zendesk.auth import READ_SCOPE, ApiTokenCredentials, OAuthCredentials

ENV_PREFIX = "ZIE_"


def read_env_file(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines; ignores blanks, comments and surrounding quotes."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


class Settings(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8000
    frontend_dist: Path | None = None

    subdomain: str | None = None
    client_id: str | None = None
    client_secret: SecretStr | None = None
    scope: str = READ_SCOPE
    email: str | None = None
    api_token: SecretStr | None = None

    @classmethod
    def load(
        cls, environ: Mapping[str, str] | None = None, env_file: Path | None = Path(".env")
    ) -> Settings:
        merged: dict[str, str] = read_env_file(env_file) if env_file else {}
        merged.update(environ if environ is not None else os.environ)
        fields = {
            name: merged[ENV_PREFIX + name.upper()]
            for name in cls.model_fields
            if merged.get(ENV_PREFIX + name.upper())
        }
        return cls.model_validate(fields)

    def credentials(self) -> OAuthCredentials | ApiTokenCredentials | None:
        if not self.subdomain:
            return None
        if self.client_id and self.client_secret:
            return OAuthCredentials(
                subdomain=self.subdomain,
                client_id=self.client_id,
                client_secret=self.client_secret,
                scope=self.scope,
            )
        if self.email and self.api_token:
            return ApiTokenCredentials(
                subdomain=self.subdomain, email=self.email, api_token=self.api_token
            )
        return None


def get_settings() -> Settings:
    return Settings.load()
