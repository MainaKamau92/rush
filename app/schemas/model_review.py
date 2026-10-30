from typing import Annotated, Literal, Self

from pydantic import Field, TypeAdapter, field_validator, model_validator

from app.schemas.investigation import InvestigationReport, ReadRequest
from app.schemas.review import (
    HOST_LIMITATIONS,
    Contract,
    EvidenceRef,
    FindingDraft,
    LimitationCode,
    ModelCapabilities,
    NonNegative,
    Positive,
    ReviewResult,
    Text,
    VersionPin,
)

Capability = Literal["repo.read_snippet", "repo.find_symbol"]
Feature = Literal["native_tool_calls", "native_structured_output"]
Disclosure = Literal["public", "internal", "private"]


class ModelRequest(Contract):
    model_id: Text
    prompt: Text
    max_output_tokens: Positive
    instructions: Text | None = None


class ReviewPermissions(Contract):
    runtime: tuple[Capability, ...] = ()
    repository: tuple[Capability, ...] = ()
    skill: tuple[Capability, ...] = ()
    allowed_disclosures: tuple[Disclosure, ...] = ("public",)

    @property
    def effective(self) -> frozenset[Capability]:
        return (
            frozenset(self.runtime) & frozenset(self.repository) & frozenset(self.skill)
        )


class ReviewTask(Contract):
    skill: VersionPin
    instructions: Text
    permissions: ReviewPermissions = Field(default_factory=ReviewPermissions)
    code_disclosure: Disclosure = "private"
    required_features: tuple[Feature, ...] = ()


class ModelLimitation(Contract):
    code: LimitationCode
    reason: Text
    source_id: Text | None = None

    @field_validator("code")
    @classmethod
    def model_codes_only(cls, value: str) -> str:
        if value in HOST_LIMITATIONS:
            raise ValueError("This limitation is reported only by rush itself")
        return value


class QuestionAnswer(Contract):
    question_id: Text
    answer: Text
    evidence_ids: Annotated[tuple[Text, ...], Field(min_length=1, max_length=16)]


class RequestContext(Contract):
    kind: Literal["request_context"]
    requests: Annotated[tuple[ReadRequest, ...], Field(min_length=1, max_length=16)]
    answers: tuple[QuestionAnswer, ...] = ()


class EvidenceSelection(Contract):
    source_id: Text
    start: Positive
    end: Positive


class Candidates(Contract):
    kind: Literal["candidates"]
    findings: Annotated[
        tuple[FindingDraft[EvidenceSelection], ...], Field(min_length=1, max_length=32)
    ]
    limitations: tuple[ModelLimitation, ...] = ()
    answers: tuple[QuestionAnswer, ...] = ()


class Done(Contract):
    kind: Literal["done"]
    limitations: tuple[ModelLimitation, ...] = ()
    answers: tuple[QuestionAnswer, ...] = ()


ReviewStep = Annotated[RequestContext | Candidates | Done, Field(discriminator="kind")]
REVIEW_STEP = TypeAdapter[ReviewStep](ReviewStep)


class CritiqueVerdict(Contract):
    candidate: NonNegative
    verdict: Literal["keep", "withdraw", "question"]
    reason: Text
    question: Text | None = None

    @model_validator(mode="after")
    def question_when_unresolved(self) -> Self:
        if (self.verdict == "question") != (self.question is not None):
            raise ValueError("Only a question verdict states the open question")
        return self


class Critique(Contract):
    kind: Literal["critique"]
    verdicts: Annotated[tuple[CritiqueVerdict, ...], Field(min_length=1, max_length=96)]


CRITIQUE = TypeAdapter[Critique](Critique)


class Proposal(Contract):
    skill: VersionPin
    finding: FindingDraft[EvidenceRef]
    verdict: CritiqueVerdict | None = None


class ModelReviewReport(Contract):
    run_id: Text
    status: Literal["ready", "partial", "failed", "cancelled"]
    reason: Text
    capabilities: ModelCapabilities | None
    effective_permissions: tuple[Capability, ...]
    investigation: InvestigationReport
    result: ReviewResult
    proposals: tuple[Proposal, ...] = ()
