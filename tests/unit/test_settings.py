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


def test_model_secret_is_hidden_and_nonsecure_endpoints_are_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("META_AI_KEY", "private-model-credential")
    settings = Settings()
    assert "private-model-credential" not in repr(settings)
    assert settings.meta_api_key is not None
    assert settings.meta_api_key.get_secret_value() == "private-model-credential"
    with pytest.raises(ValidationError) as error:
        Settings(meta_base_url="http://private-value.example")
    assert "private-value" not in str(error.value)
