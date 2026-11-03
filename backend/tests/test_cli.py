from __future__ import annotations

import pytest

from zie import cli


def test_parser_knows_the_phase_0_commands() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["serve", "--port", "9000"]).port == 9000
    assert parser.parse_args(["auth", "test"]).auth_command == "test"
    assert parser.parse_args(["snapshot", "groups", "--format", "json"]).format == "json"
    assert parser.parse_args(["snapshot"]).area is None
    assert parser.parse_args(["snapshot", "ticket-fields"]).area == "ticket-fields"


def test_missing_credentials_exit_cleanly(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: object
) -> None:
    monkeypatch.chdir(str(tmp_path))
    monkeypatch.setattr(cli.AppState, "active_subdomain", property(lambda self: None))
    for key in ("ZIE_SUBDOMAIN", "ZIE_CLIENT_ID", "ZIE_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    assert cli.main(["auth", "test"]) == 1
    assert "No credentials found" in capsys.readouterr().err
