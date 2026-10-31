from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from app.schemas.policy import PolicyScope
from app.schemas.review import (
    Contract,
    Digest,
    ModelConfiguration,
    NonNegative,
    Positive,
    RuleRef,
    Text,
    VersionPin,
)
from app.schemas.skill import Category

EVALUATION_VERSION: Literal[2] = 2
# Learned rules live in their own namespace so they can't replace a file rule.
RuleId = Annotated[str, Field(pattern=r"^learned\.[a-z0-9][a-z0-9.-]{2,72}$")]


class LearningExamples(Contract):
    violating: tuple[Text, ...] = ()
    acceptable: tuple[Text, ...] = ()


class LearningDraft(Contract):
    """
    The exact proposed rule. It has no permission fields, so a proposal can
    never widen what tools may do or where results are published.
    """

    rule_id: RuleId
    statement: Text
    rationale: Text
    category: Category
    owner: Text
    scope: PolicyScope
    source: Text
    examples: LearningExamples = LearningExamples()
    waivable: bool = True


class CaseResult(Contract):
    case: Text
    purpose: Literal["proposal", "skill_regression"] = "proposal"
    expected: Literal["violating", "acceptable"]
    status: Literal["passed", "failed", "incomplete"]
    rule_findings: NonNegative
    run_status: Text


class LearningEvaluation(Contract):
    evaluator_version: Literal[2] | None = None
    content_sha256: Digest
    rule: RuleRef
    skill: VersionPin
    model: ModelConfiguration
    cases: tuple[CaseResult, ...]
    passed: bool
    evaluated_at: AwareDatetime


class LearningProposal(Contract):
    id: Text
    revision: Positive
    draft: LearningDraft
    content_sha256: Digest
    status: Literal["proposed", "evaluated", "approved"]
    proposer: Text
    evaluation: LearningEvaluation | None = None
    approved_by: Text | None = None
    approved_at: AwareDatetime | None = None
    approval_channel: Literal["github", "cli"] | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
