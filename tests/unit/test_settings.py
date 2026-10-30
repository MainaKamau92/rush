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
    assert "must be absolute" in str(error.value)
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


def test_github_reviews_are_enabled_only_with_every_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUSH_REVIEW_RULES_FILE", "")
    assert Settings().review_rules_file is None
    assert not Settings().github_enabled
    monkeypatch.setenv("RUSH_GITHUB_APP_ID", "123")
    monkeypatch.setenv("RUSH_GITHUB_PRIVATE_KEY_FILE", "/run/secrets/github-app.pem")
    monkeypatch.setenv("RUSH_GITHUB_REPOSITORIES", "Lantern/Demo, lantern/api")
    monkeypatch.setenv("RUSH_GITHUB_WEBHOOK_SECRET", "")
    assert not Settings().github_enabled
    monkeypatch.setenv("RUSH_GITHUB_WEBHOOK_SECRET", "private-webhook-secret")
    settings = Settings()
    assert settings.github_enabled
    assert settings.github_repositories == {"lantern/demo", "lantern/api"}
    assert "private-webhook-secret" not in repr(settings)
    assert settings.mirrors_dir == settings.state_dir / "repositories"
    monkeypatch.setenv("RUSH_GITHUB_REPOSITORIES", "lantern")
    with pytest.raises(ValidationError, match="OWNER/NAME"):
        Settings()
    monkeypatch.setenv("RUSH_GITHUB_REPOSITORIES", "lantern/demo")
    monkeypatch.setenv("RUSH_GITHUB_API_URL", "http://api.github.test")
    with pytest.raises(ValidationError, match="HTTPS"):
        Settings()
