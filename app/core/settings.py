from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUSH_", hide_input_in_errors=True)
    state_dir: Path
    environment: Literal["development", "test", "production"] = "development"
    meta_api_key: SecretStr | None = Field(
        default=None, validation_alias="META_AI_KEY", repr=False
    )
    meta_base_url: str = "https://api.meta.ai/v1"
    model_timeout_seconds: float = Field(default=30, gt=0, le=60)

    @field_validator("meta_base_url")
    @classmethod
    def require_secure_model_endpoint(cls, value: str) -> str:
        endpoint = urlsplit(value)
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError(
                "Model endpoint must be HTTPS without credentials or query"
            )
        return value.rstrip("/")

    @field_validator("state_dir")
    @classmethod
    def require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("RUSH_STATE_DIR must be an absolute directory")
        return value

    @property
    def database_path(self) -> Path:
        return self.state_dir / "rush.sqlite3"
