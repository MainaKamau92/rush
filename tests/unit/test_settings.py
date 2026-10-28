"""Configuration failures are actionable without exposing supplied values."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import Settings


def test_missing_state_directory_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RUSH_STATE_DIR")
    with pytest.raises(ValidationError, match="state_dir"):
        Settings()


def test_relative_directory_is_rejected_without_echoing_input() -> None:
    with pytest.raises(ValidationError) as error:
        Settings(state_dir=Path("private-customer-value"))
    assert "must be an absolute" in str(error.value)
    assert "private-customer-value" not in str(error.value)


def test_unsupported_environment_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="unknown")
