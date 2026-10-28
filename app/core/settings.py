"""Deployment settings; team policy and credentials are not inferred from source."""

from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Explicit, validated settings shared by API and CLI."""

    model_config = SettingsConfigDict(env_prefix="RUSH_", hide_input_in_errors=True)

    state_dir: Path
    environment: Literal["development", "test", "production"] = "development"

    @field_validator("state_dir")
    @classmethod
    def require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("RUSH_STATE_DIR must be an absolute directory")
        return value

    @property
    def database_path(self) -> Path:
        return self.state_dir / "rush.sqlite3"
