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
class ToolCall:
    call_id: str
    name: str
    arguments: str


@dataclass(frozen=True)
class ToolReply:
    """
    One turn of a tool conversation: the calls the model made, any text, and
    the output items to send back so a stateless provider can continue.
    """

    provider: str
    model_id: str
    text: str
    calls: tuple[ToolCall, ...]
    items: tuple[dict[str, object], ...]
    usage: TokenUsage | None
    status: Literal["completed", "incomplete", "failed", "cancelled"] = "completed"
    cached_tokens: int | None = None
    resolved_revision: str | None = None


@dataclass(frozen=True)
class ModelAccess:
    provider: str
    requested_model: str
    resolved_model: str
    usage: TokenUsage | None
    rate_limits: dict[str, int]
