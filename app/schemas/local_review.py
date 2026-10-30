from typing import Literal

from app.schemas.investigation import InvestigationReport
from app.schemas.model_review import Disclosure
from app.schemas.review import (
    Contract,
    EvidenceRef,
    FindingDraft,
    ReviewRecord,
    Text,
    VersionPin,
)


class ContextFile(Contract):
    kind: Literal["ticket", "guideline"]
    reference: Text
    text: Text


class LocalReviewRequest(Contract):
    run_id: Text
    repository: Text
    head: Text
    target: Text | None = None
    base: Text | None = None
    disclosure: Disclosure = "private"
    context: tuple[ContextFile, ...] = ()
    rules: Text | None = None


class WithdrawnProposal(Contract):
    skill: VersionPin
    finding: FindingDraft[EvidenceRef]
    by: Literal["critique", "host"]
    reason: Text


class ReviewOutcome(Contract):
    record: ReviewRecord
    investigation: InvestigationReport
    withdrawn: tuple[WithdrawnProposal, ...] = ()
