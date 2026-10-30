from typing import Literal

ReviewStatus = Literal[
    "queued",
    "preparing",
    "reviewing",
    "validating",
    "publishing",
    "completed",
    "partial",
    "failed",
    "superseded",
    "cancelled",
    "skipped",
]

NEXT_STATUS: dict[ReviewStatus, ReviewStatus] = {
    "queued": "preparing",
    "preparing": "reviewing",
    "reviewing": "validating",
    "validating": "publishing",
    "publishing": "completed",
}
TERMINAL_STATUSES = frozenset(
    {"completed", "partial", "failed", "superseded", "cancelled", "skipped"}
)
