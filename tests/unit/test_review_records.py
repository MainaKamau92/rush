import json
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.core.errors import ReviewConflictError, ReviewError
from app.models.review import NEXT_STATUS
from app.schemas.review import (
    EvidenceRef,
    Limitation,
    ReviewInputs,
    ReviewRecord,
    ReviewResult,
    ReviewSettings,
)
from app.services.review_records import ReviewRecordService


class MemoryReviews:
    def __init__(self):
        self.records = {}
        self.conflict = False

    async def create(self, record):
        if record.id in self.records:
            raise ReviewConflictError("Review identity already exists")
        self.records[record.id] = record

    async def get(self, run_id):
        return self.records[run_id]

    async def save(self, record, expected_revision):
        if self.conflict or self.records[record.id].revision != expected_revision:
            raise ReviewConflictError("Concurrent update")
        self.records[record.id] = record


@pytest.fixture
def service():
    return ReviewRecordService(
        MemoryReviews(), lambda: datetime(2026, 1, 15, tzinfo=UTC)
    )


async def test_progress_records_every_stage_and_preserves_the_frozen_inputs(
    service, review_inputs, review_result
):
    accepted = await service.create("demo-run", review_inputs)
    assert accepted.status == "queued"
    for index, stage in enumerate(NEXT_STATUS.values(), start=1):
        record = await service.advance(
            "demo-run", stage, f"Entered {stage}", review_result
        )
        assert record.revision == index
        assert record.inputs == accepted.inputs
    assert record.status == "completed"
    assert [event.status for event in record.progress.events] == [
        "queued",
        *NEXT_STATUS.values(),
    ]
    assert record.progress.result == review_result
    with pytest.raises(ValidationError, match="frozen"):
        record.inputs.settings.models[0].model_id = "replacement"
    assert isinstance(record.inputs.sources, tuple)
    with pytest.raises(ValidationError, match="frozen"):
        record.inputs.sources[0].revision = "replacement"


@pytest.mark.parametrize(
    "status", ["partial", "failed", "superseded", "cancelled", "skipped"]
)
async def test_terminal_alternatives_record_reasons_and_cannot_be_reopened(
    service, review_inputs, status
):
    await service.create("demo-run", review_inputs)
    result = ReviewResult(
        limitations=(
            Limitation(code="missing_context", reason="Guideline unavailable"),
        )
    )
    record = await service.advance(
        "demo-run", status, "Work stopped for this reason", result
    )
    assert record.status == status
    assert record.progress.events[-1].reason == "Work stopped for this reason"
    with pytest.raises(ReviewError, match="terminal"):
        await service.advance("demo-run", "preparing", "Attempt to reopen")
    assert await service.get("demo-run") == record


async def test_invalid_progress_never_overwrites_saved_work(service, review_inputs):
    accepted = await service.create("demo-run", review_inputs)
    with pytest.raises(ReviewError, match="lifecycle"):
        await service.advance("demo-run", "completed", "Cannot skip work")
    with pytest.raises(ReviewError, match="limitations"):
        await service.advance("demo-run", "partial", "Missing explanation")
    with pytest.raises(ValidationError):
        await service.advance("demo-run", "failed", "   ")
    assert await service.get("demo-run") == accepted


async def test_completed_cannot_hide_unresolved_limitations(service, review_inputs):
    await service.create("demo-run", review_inputs)
    for stage in ("preparing", "reviewing", "validating", "publishing"):
        await service.advance("demo-run", stage, stage)
    result = ReviewResult(
        limitations=(Limitation(code="budget", reason="Model budget exhausted"),)
    )
    with pytest.raises(ReviewError, match="partial"):
        await service.advance("demo-run", "completed", "Attempted clean result", result)
    assert (await service.get("demo-run")).status == "publishing"


async def test_optional_context_limitations_do_not_prevent_completion(
    service, review_inputs
):
    await service.create("demo-run", review_inputs)
    result = ReviewResult(
        limitations=(
            Limitation(
                code="unresolved_question",
                reason="Optional dependency detail unavailable",
                affects_completeness=False,
            ),
        )
    )
    for stage in NEXT_STATUS.values():
        record = await service.advance("demo-run", stage, stage, result)
    assert record.status == "completed"
    assert record.progress.result.limitations == result.limitations


def test_limitation_codes_are_distinct_and_reject_unknown_spellings():
    codes = (
        "missing_ticket",
        "access_denied",
        "rate_limited",
        "content_truncated",
        "guideline_changed",
        "conflicting_sources",
    )
    assert tuple(Limitation(code=code, reason=code).code for code in codes) == codes
    with pytest.raises(ValidationError, match="code"):
        Limitation(code="rate-limit", reason="Noncanonical spelling")


async def test_backward_clock_and_concurrent_update_are_rejected(review_inputs):
    now = datetime(2026, 1, 15, tzinfo=UTC)
    repository = MemoryReviews()
    service = ReviewRecordService(repository, lambda: now)
    accepted = await service.create("demo-run", review_inputs)
    now -= timedelta(seconds=1)
    with pytest.raises(ReviewError, match="backwards"):
        await service.advance("demo-run", "preparing", "Clock regressed")
    now += timedelta(seconds=2)
    repository.conflict = True
    with pytest.raises(ReviewConflictError):
        await service.advance("demo-run", "preparing", "Lost race")
    assert await service.get("demo-run") == accepted


@pytest.mark.parametrize(
    "mutation", ["run", "skill", "rule", "evidence", "causal", "duplicate"]
)
async def test_findings_cannot_reference_other_runs_or_unfrozen_versions(
    service, review_inputs, review_result, mutation
):
    await service.create("demo-run", review_inputs)
    finding = review_result.findings[0]
    changes = {
        "run": {"run_id": "other-run"},
        "skill": {"skill": finding.skill.model_copy(update={"digest": "f" * 64})},
        "rule": {"rule_ref": finding.rule_ref.model_copy(update={"version": "2"})},
        "evidence": {
            "evidence": (
                finding.evidence[0].model_copy(update={"revision": "changed"}),
            )
        },
        "causal": {
            "causal_path": (
                finding.evidence[0].model_copy(update={"source_id": "missing"}),
            )
        },
    }
    findings = (
        (finding, finding)
        if mutation == "duplicate"
        else (finding.model_copy(update=changes[mutation]),)
    )
    result = ReviewResult(findings=findings)
    with pytest.raises(ReviewError):
        await service.advance("demo-run", "preparing", "Invalid attribution", result)
    assert (await service.get("demo-run")).revision == 0


async def test_correctness_finding_can_be_saved_without_a_team_rule(
    service, review_inputs, review_result
):
    await service.create("demo-run", review_inputs)
    finding = review_result.findings[0].model_copy(update={"rule_ref": None})
    record = await service.advance(
        "demo-run", "preparing", "Recorded candidate", ReviewResult(findings=(finding,))
    )
    assert record.progress.result.findings[0].rule_ref is None


@pytest.mark.parametrize(
    "mutation",
    ["version", "unknown", "provider", "budget", "type", "task", "duplicate-task"],
)
def test_unsupported_settings_fail_with_useful_safe_explanations(
    review_inputs, mutation
):
    value = json.loads(review_inputs.settings.model_dump_json())
    if mutation == "version":
        value["schema_version"] = 2
    elif mutation == "unknown":
        value["api_key"] = "private-fixture-value"
    elif mutation == "provider":
        value["models"][0]["provider"] = "private-fixture-value"
    elif mutation == "budget":
        value["limits"]["model_calls"] = 0
    elif mutation == "type":
        value["limits"]["model_calls"] = "12"
    elif mutation == "task":
        value["models"][0]["task"] = "critique"
    else:
        value["models"].append(value["models"][0])
    with pytest.raises(ValidationError) as error:
        ReviewSettings.model_validate_json(json.dumps(value))
    assert "private-fixture-value" not in str(error.value)
    assert str(error.value)


@pytest.mark.parametrize("kind", ["rules", "skills", "sources"])
def test_duplicate_snapshot_identities_are_rejected(review_inputs, kind):
    value = json.loads(review_inputs.model_dump_json())
    value[kind].append(value[kind][0])
    with pytest.raises(ValidationError, match="unique"):
        ReviewInputs.model_validate_json(json.dumps(value))


def test_invalid_evidence_ranges_are_rejected(review_result):
    value = review_result.findings[0].evidence[0].model_dump()
    value.update(start=6, end=5)
    with pytest.raises(ValidationError, match="precede"):
        EvidenceRef.model_validate(value)


async def test_inputs_from_unvalidated_copies_are_checked_again(service, review_inputs):
    invalid = review_inputs.model_copy(update={"head_sha": "not-a-commit"})
    with pytest.raises(ValidationError, match="head_sha"):
        await service.create("demo-run", invalid)


def test_saved_format_round_trips_and_exposes_a_json_schema(
    review_inputs, review_result
):
    record = ReviewRecord(
        id="demo-run",
        inputs=review_inputs,
        progress={
            "events": (
                {
                    "status": "queued",
                    "reason": "Accepted",
                    "at": datetime(2026, 1, 15, tzinfo=UTC),
                },
            ),
            "result": review_result,
        },
    )
    assert ReviewRecord.model_validate_json(record.model_dump_json()) == record
    schema = ReviewRecord.model_json_schema()
    assert schema["additionalProperties"] is False
    assert "inputs" in schema["required"]
