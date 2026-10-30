from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, field_validator, model_validator

from app.schemas.model_review import Capability, Disclosure
from app.schemas.review import (
    Contract,
    Digest,
    LimitationCode,
    NonNegative,
    Positive,
    RuleRef,
    Text,
    VersionPin,
)

FileName = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")]
SkillId = Annotated[
    str, Field(pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$", max_length=100)
]
Version = Annotated[str, Field(pattern=r"^\d{1,4}\.\d{1,4}\.\d{1,4}$")]
Category = Literal[
    "correctness",
    "regression",
    "compatibility",
    "architecture",
    "completeness",
    "security",
]


class SkillScope(Contract):
    paths: Annotated[tuple[Text, ...], Field(min_length=1, max_length=20)]

    @field_validator("paths")
    @classmethod
    def relative_patterns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for pattern in value:
            parts = pattern.split("/")
            if (
                len(pattern) > 200
                or pattern.startswith("/")
                or any(part in {"", ".", ".."} for part in parts)
                or any(character in pattern for character in "\\\0[]{}")
            ):
                raise ValueError("Scope paths must be relative glob patterns")
        return value


class SkillPermissions(Contract):
    capabilities: tuple[Capability, ...] = ()


class SkillManifest(Contract):
    schema_version: Literal[1]
    id: SkillId
    version: Version
    description: Text
    scope: SkillScope
    instructions: FileName
    examples: FileName
    rule_ids: tuple[Text, ...] = ()
    permissions: SkillPermissions = Field(default_factory=SkillPermissions)
    model_profile: Text

    @model_validator(mode="after")
    def distinct_files(self) -> Self:
        if len({"manifest.json", self.instructions, self.examples}) != 3:
            raise ValueError("Manifest, instructions and examples must be separate")
        return self


class ExampleAnchor(Contract):
    path: Text
    side: Literal["LEFT", "RIGHT"]
    line: Positive


class ExpectedFinding(Contract):
    rule: RuleRef | None
    category: Category
    anchor: ExampleAnchor


class SkillExample(Contract):
    case: Text
    kind: Literal["acceptable", "violating"]
    expected_findings: tuple[ExpectedFinding, ...] = ()
    forbidden_findings: tuple[ExpectedFinding, ...] = ()
    expected_limitations: tuple[LimitationCode, ...] = ()
    forbidden_reads: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def outcome_matches_kind(self) -> Self:
        if (self.kind == "violating") != bool(self.expected_findings):
            raise ValueError(
                "Violating examples expect findings; acceptable examples expect none"
            )
        return self


class SkillExamples(Contract):
    corpus: FileName
    examples: Annotated[tuple[SkillExample, ...], Field(min_length=2, max_length=20)]

    @model_validator(mode="after")
    def both_kinds(self) -> Self:
        if {example.kind for example in self.examples} != {"acceptable", "violating"}:
            raise ValueError("Include acceptable and violating examples")
        cases = [example.case for example in self.examples]
        if len(cases) != len(set(cases)):
            raise ValueError("Each example case may appear once")
        return self


class ModelProfile(Contract):
    model_id: Text
    adapter_version: Text
    max_output_tokens: Positive


class ApprovedSkill(Contract):
    id: SkillId
    version: Version
    package: FileName
    digest: Digest


class ApprovedSkills(Contract):
    schema_version: Literal[1]
    permissions: tuple[Capability, ...] = ()
    allowed_disclosures: tuple[Disclosure, ...] = ("public",)
    model_profiles: dict[Text, ModelProfile]
    skills: tuple[ApprovedSkill, ...]

    @model_validator(mode="after")
    def unique_skills(self) -> Self:
        for values in (
            [skill.id for skill in self.skills],
            [skill.package for skill in self.skills],
        ):
            if len(values) != len(set(values)):
                raise ValueError("Approved skill IDs and packages must be unique")
        return self


class InstalledSkill(Contract):
    pin: VersionPin
    manifest: SkillManifest
    instructions: Text
    examples: SkillExamples
    model: ModelProfile
    active: bool
    status: Text


class EvaluatedModel(Contract):
    model_id: Text
    adapter_version: Text
    max_output_tokens: Positive


class CaseResult(Contract):
    case: Text
    kind: Literal["acceptable", "violating"]
    passed: bool
    status: Text
    matched: tuple[ExpectedFinding, ...] = ()
    missed: tuple[ExpectedFinding, ...] = ()
    unexpected: tuple[ExpectedFinding, ...] = ()
    forbidden: tuple[ExpectedFinding, ...] = ()
    missing_limitations: tuple[LimitationCode, ...] = ()
    unexpected_limitations: tuple[LimitationCode, ...] = ()
    forbidden_reads: tuple[Text, ...] = ()
    withdrawn: tuple[Text, ...] = ()
    model_calls: NonNegative = 0
    input_tokens: NonNegative | None = None
    output_tokens: NonNegative | None = None

    def meets_expectations(self) -> bool:
        return self.status in {"completed", "partial"} and not any(
            (
                self.missed,
                self.unexpected,
                self.forbidden,
                self.missing_limitations,
                self.unexpected_limitations,
                self.forbidden_reads,
            )
        )

    @model_validator(mode="after")
    def consistent_verdict(self) -> Self:
        if self.passed != self.meets_expectations():
            raise ValueError("Case verdict does not match its recorded results")
        return self


class SkillEvaluation(Contract):
    schema_version: Literal[1] = 1
    skill: VersionPin
    model: EvaluatedModel
    protocol_sha256: Digest
    corpus_sha256: Digest
    evaluated_at: AwareDatetime
    cases: Annotated[tuple[CaseResult, ...], Field(min_length=1)]

    @property
    def passed(self) -> bool:
        return all(case.passed for case in self.cases)
