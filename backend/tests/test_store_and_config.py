from __future__ import annotations

from pathlib import Path

from zie.config import Settings, read_env_file
from zie.store import AppState, MemoryCredentialStore, credentials_from_json, credentials_to_json
from zie.zendesk.auth import ApiTokenCredentials, OAuthCredentials


def test_credentials_round_trip_keeps_secret(oauth_creds: OAuthCredentials) -> None:
    restored = credentials_from_json(credentials_to_json(oauth_creds))
    assert isinstance(restored, OAuthCredentials)
    assert restored.client_secret.get_secret_value() == "s3cret"
    assert restored.scope == "read"


def test_memory_store_is_keyed_by_subdomain(oauth_creds: OAuthCredentials) -> None:
    store = MemoryCredentialStore()
    store.save(oauth_creds)
    loaded = store.load("acme")
    assert loaded is not None and loaded.auth_type == "oauth"
    store.delete("acme")
    assert store.load("acme") is None
    store.delete("acme")  # deleting twice is fine


def test_api_token_round_trip() -> None:
    creds = ApiTokenCredentials.model_validate(
        {"subdomain": "acme", "email": "a@acme.test", "api_token": "t0k"}
    )
    restored = credentials_from_json(credentials_to_json(creds))
    assert isinstance(restored, ApiTokenCredentials)
    assert restored.api_token.get_secret_value() == "t0k"


def test_app_state_persists_active_subdomain(tmp_path: Path) -> None:
    state = AppState(tmp_path / "zie")
    assert state.active_subdomain is None
    state.set_active_subdomain("acme")
    assert AppState(tmp_path / "zie").active_subdomain == "acme"
    state.clear_active_subdomain()
    assert state.active_subdomain is None


def test_app_state_survives_corrupt_file(tmp_path: Path) -> None:
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    assert AppState(tmp_path).active_subdomain is None


def test_env_file_parsing(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nZIE_SUBDOMAIN=pdi-nagarro6612\nexport ZIE_CLIENT_ID='zie-engine'\n"
        'ZIE_CLIENT_SECRET="abc=123"\n\nBROKEN LINE\n',
        encoding="utf-8",
    )
    assert read_env_file(env) == {
        "ZIE_SUBDOMAIN": "pdi-nagarro6612",
        "ZIE_CLIENT_ID": "zie-engine",
        "ZIE_CLIENT_SECRET": "abc=123",
    }


def test_settings_build_oauth_credentials_and_env_wins(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("ZIE_SUBDOMAIN=from-file\nZIE_CLIENT_ID=id\nZIE_CLIENT_SECRET=x\n", "utf-8")
    settings = Settings.load({"ZIE_SUBDOMAIN": "pdi-nagarro6612.zendesk.com"}, env)
    creds = settings.credentials()
    assert isinstance(creds, OAuthCredentials)
    assert creds.subdomain == "pdi-nagarro6612"
    assert creds.scope == "read"


def test_settings_without_secrets_give_no_credentials() -> None:
    assert Settings.load({"ZIE_SUBDOMAIN": "acme"}, None).credentials() is None
    assert Settings.load({}, None).port == 8000
