from pathlib import Path

import pytest

from app.core.settings import Settings
from app.db.migrate import migrate


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("RUSH_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("RUSH_ENVIRONMENT", "test")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(state_dir=tmp_path / "state", environment="test")


@pytest.fixture
def initialized(settings: Settings) -> Settings:
    migrate(settings.database_path)
    return settings
