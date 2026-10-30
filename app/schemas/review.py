from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
)

from app.models.review import ReviewStatus

Text = Annotated[str, Field(min_length=1, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Commit = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
Positive = Annotated[int, Field(gt=0)]
NonNegative = Annotated[int, Field(ge=0)]


class Contract(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )


class ReviewLimits(Contract):
    changed_files: Positive = 20
    changed_lines: Positive = 500
    additional_files: NonNegative = 8
    snippet_reads: NonNegative = 16
    relationship_depth: NonNegative = 2
    mcp_calls: NonNegative = 6
    scoped_searches: NonNegative = 1
    model_calls: Positive = 12
    source_bytes: Positive = 131072
    wall_seconds: Positive = 180


class ModelConfiguration(Contract):
    task: Literal["review", "critique", "clarification"]
    provider: Literal["meta"] = "meta"
    model_id: Text
    adapter_version: Text
    resolved_revision: Text | None = None
    max_output_tokens: Positive


class ModelCapabilities(Contract):
    provider: Text
    model_id: Text
    adapter_version: Text
    native_tool_calls: bool
    native_structured_output: bool
    max_input_tokens: Positive | None = None
    resolved_revision: Text | None = None


class ReviewSettings(Contract):
    schema_version: Literal[1] = 1
    mode: Literal["advisory", "required"] = "advisory"
    severity_threshold: Literal["high", "medium", "low"] = "high"
    models: Annotated[tuple[ModelConfiguration, ...], Field(min_length=1)]
    limits: ReviewLimits = Field(default_factory=ReviewLimits)

    @model_validator(mode="after")
    def unique_model_tasks(self) -> Self:
        tasks = [model.task for model in self.models]
        if len(tasks) != len(set(tasks)) or "review" not in tasks:
            raise ValueError("Select one model per task, including the review task")
        return self


class RuleRef(Contract):
    id: Text
    version: Text


class VersionPin(Contract):
    id: Text
    version: Text
    digest: Digest


class SourceSnapshot(Contract):
    id: Text
    kind: Literal["code", "ticket", "guideline", "policy"]
    reference: Text
    workspace: Text | None = None
    revision: Text | None = None
    content_sha256: Digest
    retrieved_at: AwareDatetime
    disclosure: Literal["public", "internal", "private"] = "private"
    excerpt: str | None = None


class ReviewInputs(Contract):
    schema_version: Literal[1] = 1
    repository: Text
    pull_request: Positive | None = None
    target_sha: Commit
    merge_base_sha: Commit
    head_sha: Commit
    policy_sha: Commit
    memory_revision: Text
    settings: ReviewSettings
    rules: tuple[VersionPin, ...] = ()
    skills: Annotated[tuple[VersionPin, ...], Field(min_length=1)]
    sources: tuple[SourceSnapshot, ...] = ()
    scope_manifest_sha256: Digest | None = None
    exceptions: tuple[VersionPin, ...] = ()
    review_time: AwareDatetime | None = None
    policy_record: Text | None = None

    @model_validator(mode="after")
    def unique_snapshot_identities(self) -> Self:
        for items in (self.rules, self.skills, self.sources, self.exceptions):
            ids = [item.id for item in items]
            if len(ids) != len(set(ids)):
                raise ValueError("Rule, skill and source IDs must be unique per kind")
        return self


class DiffAnchor(Contract):
    path: Text
    side: Literal["LEFT", "RIGHT"]
    line: Positive
    hunk_id: Text


class EvidenceRef(Contract):
    source_id: Text
    revision: Text | None = None
    content_sha256: Digest
    start: Positive
    end: Positive

    @model_validator(mode="after")
    def ordered_range(self) -> Self:
        if self.end < self.start:
            raise ValueError("Evidence end must not precede its start")
        return self


class FindingDraft[Evidence](Contract):
    rule_ref: RuleRef | None = None
    category: Literal[
        "correctness",
        "regression",
        "compatibility",
        "architecture",
        "completeness",
        "security",
    ]
    severity: Literal["high", "medium", "low"]
    anchor: DiffAnchor
    problem: Text
    consequence: Text
    trigger_scenario: Text
    causal_path: Annotated[tuple[Evidence, ...], Field(min_length=1)]
    evidence: Annotated[tuple[Evidence, ...], Field(min_length=1)]
    assumptions: tuple[Text, ...] = ()
    remediation: Text


class Finding(FindingDraft[EvidenceRef]):
    id: Text
    fingerprint: Text
    run_id: Text
    skill: VersionPin
    verification: Literal["code_inspected", "execution_verified"]
    disposition: Literal[
        "open", "accepted", "dismissed", "withdrawn", "resolved", "needs_recheck"
    ] = "open"


HOST_LIMITATIONS = ("guideline_changed", "policy_not_applied")
LimitationCode = Literal[
    "missing_ticket",
    "access_denied",
    "rate_limited",
    "content_truncated",
    "guideline_changed",
    "conflicting_sources",
    "missing_context",
    "budget",
    "unresolved_question",
    "required_skill_unsupported",
    "scope_excluded",
    "policy_conflict",
    "policy_not_applied",
]


class Limitation(Contract):
    code: LimitationCode
    reason: Text
    source_id: Text | None = None
    affects_completeness: bool = True


class ReviewUsage(Contract):
    model_calls: NonNegative = 0
    input_tokens: NonNegative | None = None
    output_tokens: NonNegative | None = None
    source_bytes: NonNegative = 0


class ModelAttempt(Contract):
    requested_model: ModelConfiguration
    resolved_provider: Text | None = None
    resolved_model: Text | None = None
    resolved_revision: Text | None = None
    repair: bool = False
    status: Literal[
        "received",
        "accepted",
        "invalid",
        "failed",
        "timeout",
        "cancelled",
        "incomplete",
        "unsupported",
        "identity_mismatch",
    ]
    input_tokens: NonNegative | None = None
    output_tokens: NonNegative | None = None
    total_tokens: NonNegative | None = None
    response_sha256: Digest | None = None
    unsupported_features: tuple[Text, ...] = ()


class WithdrawnFinding(Contract):
    skill: VersionPin
    finding: FindingDraft[EvidenceRef]
    by: Literal["critique", "host"]
    reason: Text


class WaivedFinding(Contract):
    finding: Finding
    exception_id: Text
    reason: Text


class ReviewResult(Contract):
    findings: tuple[Finding, ...] = ()
    waived: tuple[WaivedFinding, ...] = ()
    withdrawn: tuple[WithdrawnFinding, ...] = ()
    candidate_findings: tuple[FindingDraft[EvidenceRef], ...] = ()
    model_capabilities: ModelCapabilities | None = None
    model_attempts: tuple[ModelAttempt, ...] = ()
    context_sources: tuple[SourceSnapshot, ...] = ()
    instructions_sha256: Digest | None = None
    unsupported_features: tuple[Text, ...] = ()
    limitations: tuple[Limitation, ...] = ()
    usage: ReviewUsage = Field(default_factory=ReviewUsage)


class RunEvent(Contract):
    status: ReviewStatus
    reason: Text
    at: AwareDatetime


class ReviewProgress(Contract):
    events: Annotated[tuple[RunEvent, ...], Field(min_length=1)]
    result: ReviewResult = Field(default_factory=ReviewResult)


class ReviewRecord(Contract):
    schema_version: Literal[1] = 1
    id: Text
    inputs: ReviewInputs
    progress: ReviewProgress

    @property
    def status(self) -> ReviewStatus:
        return self.progress.events[-1].status

    @property
    def revision(self) -> int:
        return len(self.progress.events) - 1
