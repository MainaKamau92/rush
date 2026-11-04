"""
The submit tools that end a review or critique conversation, and the checks
that turn a model's submission into findings the host can validate.
"""

from typing import Annotated, Any, Literal, get_args

from pydantic import Field, ValidationError

from app.core.errors import ChangeError, MissingObjectError, ReviewError
from app.schemas.code_change import ChangeScope
from app.schemas.model_review import ModelLimitation
from app.schemas.review import (
    HOST_LIMITATIONS,
    Contract,
    DiffAnchor,
    EvidenceRef,
    FindingDraft,
    FindingLabel,
    LimitationCode,
    Positive,
    RuleRef,
    Text,
    VersionPin,
)
from app.services.model_context import ModelContext
from app.services.review_tools import RepositoryTools

SUBMIT_REVIEW = "submit_review"
SUBMIT_VERDICTS = "submit_verdicts"
CATEGORIES = list(get_args(FindingDraft.model_fields["category"].annotation))
SEVERITIES = ["high", "medium", "low"]
MODEL_CODES = [
    code for code in get_args(LimitationCode) if code not in HOST_LIMITATIONS
]
EVIDENCE_LINES = 60


def _text(description: str) -> dict[str, Any]:
    return {"type": "string", "description": description}


SUBMIT_REVIEW_TOOL: dict[str, Any] = {
    "type": "function",
    "name": SUBMIT_REVIEW,
    "description": "Finish the review: submit every confirmed finding (an empty "
    "list when there are none). Call it once, last.",
    "parameters": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "path": _text("Changed file the comment belongs on."),
                        "line": {
                            "type": "integer",
                            "minimum": 1,
                            "description": "A changed line's number as shown in "
                            "the change (head number for +, base number for -).",
                        },
                        "side": {
                            "type": "string",
                            "enum": ["RIGHT", "LEFT"],
                            "description": "LEFT only for a removed (-) line.",
                        },
                        "label": {
                            "type": "string",
                            "enum": ["bug", "possible_bug", "nitpick"],
                            "description": "bug: confirmed from code you read; "
                            "possible_bug: suspected but not fully confirmed (say "
                            "what is unconfirmed in assumptions); nitpick: minor, "
                            "style or readability.",
                        },
                        "category": {"type": "string", "enum": CATEGORIES},
                        "severity": {"type": "string", "enum": SEVERITIES},
                        "rule_id": _text("Approved team rule ID, only if violated."),
                        "problem": _text("What is wrong, specifically."),
                        "consequence": _text("What goes wrong for users or data."),
                        "trigger_scenario": _text("Concrete inputs or steps."),
                        "remediation": _text("How to fix it."),
                        "assumptions": {"type": "array", "items": {"type": "string"}},
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "description": "Code you read that proves the finding: "
                            "path plus line range (ref head or base), or a supplied "
                            "source by source_id with its line numbers.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "source_id": {"type": "string"},
                                    "start_line": {"type": "integer", "minimum": 1},
                                    "end_line": {"type": "integer", "minimum": 1},
                                    "ref": {"type": "string", "enum": ["head", "base"]},
                                },
                                "required": ["start_line", "end_line"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": [
                        "path",
                        "line",
                        "label",
                        "category",
                        "severity",
                        "problem",
                        "consequence",
                        "trigger_scenario",
                        "remediation",
                        "evidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "limitations": {
                "type": "array",
                "description": "Only context you needed and could not obtain.",
                "items": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "enum": MODEL_CODES},
                        "reason": {"type": "string"},
                        "source_id": {"type": "string"},
                    },
                    "required": ["code", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["findings"],
        "additionalProperties": False,
    },
}

SUBMIT_VERDICTS_TOOL: dict[str, Any] = {
    "type": "function",
    "name": SUBMIT_VERDICTS,
    "description": "Finish the critique: one verdict for every candidate.",
    "parameters": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "candidate": {"type": "integer", "minimum": 0},
                        "verdict": {
                            "type": "string",
                            "enum": ["keep", "withdraw", "question"],
                        },
                        "reason": {"type": "string"},
                        "question": _text("Only for a question verdict."),
                    },
                    "required": ["candidate", "verdict", "reason"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["verdicts"],
        "additionalProperties": False,
    },
}


class SubmittedEvidence(Contract):
    path: Text | None = None
    source_id: Text | None = None
    start_line: Positive
    end_line: Positive
    ref: Literal["head", "base"] = "head"


class SubmittedFinding(Contract):
    path: Text
    line: Positive
    side: Literal["RIGHT", "LEFT"] = "RIGHT"
    label: FindingLabel = "bug"
    category: Literal[
        "correctness",
        "regression",
        "compatibility",
        "architecture",
        "completeness",
        "security",
    ]
    severity: Literal["high", "medium", "low"]
    rule_id: Text | None = None
    problem: Text
    consequence: Text
    trigger_scenario: Text
    remediation: Text
    assumptions: tuple[Text, ...] = ()
    evidence: Annotated[tuple[SubmittedEvidence, ...], Field(min_length=1)]


class Submission(Contract):
    findings: Annotated[tuple[SubmittedFinding, ...], Field(max_length=60)] = ()
    limitations: tuple[ModelLimitation, ...] = ()


def parse_submission(arguments: str) -> Submission:
    try:
        return Submission.model_validate_json(arguments or "{}", strict=False)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(map(str, item['loc'])) or 'arguments'}: {item['msg']}"
            for item in error.errors()[:8]
        )
        raise ReviewError(f"invalid submission ({problems})") from None


def nearest_anchor(scope: ChangeScope, finding: SubmittedFinding) -> DiffAnchor:
    """
    The changed line a finding is placed on: the given line when it changed,
    otherwise the closest changed line on that side of the same file.
    """
    kind = "removed" if finding.side == "LEFT" else "added"
    best: tuple[int, DiffAnchor] | None = None
    for file in scope.files:
        path = file.old_path if finding.side == "LEFT" else file.new_path
        if path != finding.path:
            continue
        for hunk in file.hunks:
            for line in hunk.lines:
                number = line.old_line if finding.side == "LEFT" else line.new_line
                if line.kind != kind or number is None:
                    continue
                distance = abs(number - finding.line)
                if best is None or distance < best[0]:
                    best = (
                        distance,
                        DiffAnchor(
                            path=finding.path,
                            side=finding.side,
                            line=number,
                            hunk_id=hunk.id,
                        ),
                    )
    if best is None:
        raise ReviewError(
            f"{finding.path} has no {kind} line in this change; place the finding "
            "on a changed line of a file shown in the change"
        )
    return best[1]


def _hunk_position(scope: ChangeScope, anchor: DiffAnchor) -> int:
    for file in scope.files:
        for hunk in file.hunks:
            if hunk.id != anchor.hunk_id:
                continue
            for position, line in enumerate(hunk.lines, start=1):
                number = line.old_line if anchor.side == "LEFT" else line.new_line
                if number == anchor.line and line.kind != "context":
                    return position
    raise ReviewError("Anchor is not a changed line")


async def to_draft(
    finding: SubmittedFinding,
    scope: ChangeScope,
    context: ModelContext,
    tools: RepositoryTools,
    rules: tuple[VersionPin, ...],
) -> FindingDraft[EvidenceRef]:
    """
    Turn a submitted finding into a draft whose evidence is frozen source
    passages: the anchored changed line first, then each cited range.
    """
    anchor = nearest_anchor(scope, finding)
    rule = None
    if finding.rule_id is not None:
        pin = next((item for item in rules if item.id == finding.rule_id), None)
        if pin is None:
            raise ReviewError(f"rule {finding.rule_id} is not an approved rule")
        rule = RuleRef(id=pin.id, version=pin.version)
    position = _hunk_position(scope, anchor)
    evidence = [context.resolve_evidence(f"diff:{anchor.hunk_id}", position, position)]
    for item in finding.evidence:
        evidence.append(await _evidence(item, context, tools))
    return FindingDraft[EvidenceRef](
        rule_ref=rule,
        category=finding.category,
        severity=finding.severity,
        anchor=anchor,
        problem=finding.problem,
        consequence=finding.consequence,
        trigger_scenario=finding.trigger_scenario,
        causal_path=tuple(evidence),
        evidence=tuple(evidence),
        assumptions=finding.assumptions,
        remediation=finding.remediation,
    )


async def _evidence(
    item: SubmittedEvidence, context: ModelContext, tools: RepositoryTools
) -> EvidenceRef:
    start, end = item.start_line, max(item.start_line, item.end_line)
    if item.source_id is not None:
        try:
            return context.resolve_evidence(item.source_id, start, end)
        except ReviewError:
            raise ReviewError(
                f"evidence {item.source_id} lines {start}-{end} is not a supplied "
                "source passage"
            ) from None
    if item.path is None:
        raise ReviewError("each evidence item needs a path or a source_id")
    try:
        text = await tools.text(item.path, item.ref)
    except (ChangeError, MissingObjectError):
        raise ReviewError(f"evidence file {item.path} cannot be read") from None
    lines = text.splitlines()
    if start > len(lines):
        raise ReviewError(f"evidence {item.path} has only {len(lines)} lines")
    end = min(end, len(lines), start + EVIDENCE_LINES - 1)
    commit = tools.commit(item.ref)
    return context.add_file_evidence(
        f"file:{item.ref}:{item.path}#L{start}-L{end}",
        f"{item.path}#L{start}-L{end}",
        commit,
        "\n".join(lines[start - 1 : end]),
    )
