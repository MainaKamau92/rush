from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

References = Annotated[frozenset[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RUSH_", hide_input_in_errors=True)
    state_dir: Path
    environment: Literal["development", "test", "production"] = "development"
    meta_api_key: SecretStr | None = Field(
        default=None, validation_alias="META_AI_KEY", repr=False
    )
    meta_base_url: str = "https://api.meta.ai/v1"
    model_timeout_seconds: float = Field(default=30, gt=0, le=60)
    clickup_mcp_url: str = "https://mcp.clickup.com/mcp"
    clickup_workspace_id: str | None = None
    clickup_api_token: SecretStr | None = Field(
        default=None, validation_alias="CLICK_UP_API_TOKEN", repr=False
    )
    mcp_credentials_dir: Path | None = None
    approved_tickets: References = frozenset()
    approved_guidelines: References = frozenset()
    source_timeout_seconds: float = Field(default=30, gt=0, le=120)
    source_disclosure: Literal["public", "internal", "private"] = "private"

    @field_validator("meta_base_url", "clickup_mcp_url")
    @classmethod
    def require_secure_endpoint(cls, value: str) -> str:
        endpoint = urlsplit(value)
        if (
            endpoint.scheme != "https"
            or not endpoint.hostname
            or endpoint.username is not None
            or endpoint.password is not None
            or endpoint.query
            or endpoint.fragment
        ):
            raise ValueError("Endpoint must be HTTPS without credentials or query")
        return value.rstrip("/")

    @field_validator("approved_tickets", "approved_guidelines", mode="before")
    @classmethod
    def split_references(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("state_dir", "mcp_credentials_dir")
    @classmethod
    def require_absolute_path(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("Configured directories must be an absolute path")
        return value

    @property
    def database_path(self) -> Path:
        return self.state_dir / "rush.sqlite3"
