from dataclasses import dataclass
from typing import Literal

SourceKind = Literal["ticket", "guideline"]


@dataclass(frozen=True)
class SourceTool:
    name: str
    required_inputs: tuple[str, ...]
    accepted_inputs: tuple[str, ...]
    read_only: bool | None
    destructive: bool | None


@dataclass(frozen=True)
class ToolCall:
    tool: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class ToolOutput:
    text: str
    is_error: bool


@dataclass(frozen=True)
class SourceEvidence:
    source: str
    kind: SourceKind
    tool: str
    reference_sha256: str
    content_sha256: str
    characters: int
    retrieved_at: str


@dataclass(frozen=True)
class CredentialStatus:
    method: Literal["api_token", "oauth"]
    credential_available: bool
    registered: bool
    scope: str | None
    refresh_available: bool
    expires_in_seconds: int | None
