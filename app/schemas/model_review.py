from typing import Annotated, Literal

from pydantic import Field, TypeAdapter

from app.schemas.investigation import InvestigationReport, ReadRequest
from app.schemas.review import (
    Contract,
    FindingDraft,
    LimitationCode,
    ModelCapabilities,
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


class ModelReviewReport(Contract):
    run_id: Text
    status: Literal["ready", "partial", "failed", "cancelled"]
    reason: Text
    capabilities: ModelCapabilities | None
    effective_permissions: tuple[Capability, ...]
    investigation: InvestigationReport
    result: ReviewResult
