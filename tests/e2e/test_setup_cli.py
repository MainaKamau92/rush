"""The same public entry point initializes, checks and backs up real state."""

import json
import sys
from pathlib import Path

import pytest

from app.cli import main


def invoke(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["rush", *args])
    return main()


def test_fresh_install_and_backup_flow(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert invoke(monkeypatch, "health") == 1
    assert "State operation failed" in capsys.readouterr().err
    assert invoke(monkeypatch, "migrate") == 0
    assert json.loads(capsys.readouterr().out) == {"name": "rush", "schema_version": 1}
    assert invoke(monkeypatch, "health") == 0
    assert json.loads(capsys.readouterr().out)["schema_version"] == 1
    assert invoke(monkeypatch, "backup", str(tmp_path / "backup.sqlite3")) == 0
    assert json.loads(capsys.readouterr().out)["backup"] == "complete"


def test_cli_configuration_failure_does_not_echo_private_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("RUSH_STATE_DIR", "private-customer-value")
    assert invoke(monkeypatch, "health") == 2
    result = capsys.readouterr()
    assert "RUSH_STATE_DIR" in result.err
    assert "private-customer-value" not in result.err
