from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class ModelReply:
    provider: str
    model_id: str
    text: str
    usage: TokenUsage | None
    rate_limits: dict[str, int]
    status: Literal["completed", "incomplete", "failed", "cancelled"] = "completed"
    resolved_revision: str | None = None
    unsupported_features: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelAccess:
    provider: str
    requested_model: str
    resolved_model: str
    usage: TokenUsage | None
    rate_limits: dict[str, int]
