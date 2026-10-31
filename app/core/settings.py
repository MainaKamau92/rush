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
    github_app_id: str | None = None
    github_private_key_file: Path | None = None
    github_webhook_secret: SecretStr | None = Field(default=None, repr=False)
    github_repositories: References = frozenset()
    github_api_url: str = "https://api.github.com"
    github_git_url: str = "https://github.com"
    review_skills_dir: Path | None = None
    review_rules_file: Path | None = None
    review_exceptions_file: Path | None = None
    review_approvers: References = frozenset()
    review_disclosure: Literal["public", "internal", "private"] = "private"
    github_audience: Literal["private", "public"] = "public"
    explain_complexity: Literal["plain", "technical"] = "plain"
    explain_verbosity: Literal["short", "detailed"] = "short"

    @field_validator(
        "meta_base_url", "clickup_mcp_url", "github_api_url", "github_git_url"
    )
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

    @field_validator(
        "approved_tickets",
        "approved_guidelines",
        "github_repositories",
        "review_approvers",
        mode="before",
    )
    @classmethod
    def split_references(cls, value: object) -> object:
        if isinstance(value, str):
            return frozenset(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator(
        "github_app_id",
        "github_private_key_file",
        "review_skills_dir",
        "review_rules_file",
        "review_exceptions_file",
        mode="before",
    )
    @classmethod
    def blank_is_unset(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("github_repositories")
    @classmethod
    def normalize_repositories(cls, value: frozenset[str]) -> frozenset[str]:
        if any(item.count("/") != 1 or " " in item for item in value):
            raise ValueError("Repositories must be OWNER/NAME")
        return frozenset(item.lower() for item in value)

    @field_validator(
        "state_dir",
        "mcp_credentials_dir",
        "github_private_key_file",
        "review_skills_dir",
        "review_rules_file",
        "review_exceptions_file",
    )
    @classmethod
    def require_absolute_path(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("Configured paths must be absolute")
        return value

    @property
    def database_path(self) -> Path:
        return self.state_dir / "rush.sqlite3"

    @property
    def mirrors_dir(self) -> Path:
        return self.state_dir / "repositories"

    @property
    def github_enabled(self) -> bool:
        return bool(
            self.github_app_id
            and self.github_private_key_file
            and self.github_webhook_secret
            and self.github_webhook_secret.get_secret_value()
            and self.github_repositories
        )
