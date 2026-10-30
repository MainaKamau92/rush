from typing import Literal

from pydantic import AwareDatetime

from app.schemas.investigation import InvestigationReport
from app.schemas.model_review import Disclosure
from app.schemas.review import (
    Contract,
    Positive,
    ReviewRecord,
    Text,
    WithdrawnFinding,
)


class ContextFile(Contract):
    kind: Literal["ticket", "guideline"]
    reference: Text
    text: Text


class LocalReviewRequest(Contract):
    run_id: Text
    repository: Text
    pull_request: Positive | None = None
    head: Text
    target: Text | None = None
    base: Text | None = None
    disclosure: Disclosure = "private"
    context: tuple[ContextFile, ...] = ()
    rules: Text | None = None
    exceptions: Text | None = None
    approvers: tuple[Text, ...] = ()
    review_time: AwareDatetime | None = None
    allow_cached_policy: bool = False
    ticket_references: tuple[Text, ...] = ()
    pull_request_text: str | None = None
    live_guidelines: bool = False

    @property
    def live_context(self) -> bool:
        return bool(
            self.ticket_references or self.pull_request_text or self.live_guidelines
        )


class ReviewOutcome(Contract):
    record: ReviewRecord
    investigation: InvestigationReport
    withheld: Text | None = None

    @property
    def withdrawn(self) -> tuple[WithdrawnFinding, ...]:
        return self.record.progress.result.withdrawn
