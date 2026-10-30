from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Acceptance:
    outcome: Literal["queued", "duplicate_delivery", "already_active", "ignored"]
    job_id: str | None = None


@dataclass(frozen=True)
class Receipt:
    status_code: int
    message: str
    job_id: str | None = None
