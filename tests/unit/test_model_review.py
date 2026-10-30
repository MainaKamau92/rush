import asyncio
import inspect
import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.core.errors import ModelError, ReviewError
from app.models.model_access import ModelReply, TokenUsage
from app.provider.model.abstract import ModelProviderAbstract
from app.schemas.model_review import ReviewPermissions, ReviewTask
from app.schemas.review import (
    ModelCapabilities,
    ModelConfiguration,
    ReviewLimits,
    ReviewSettings,
)
from app.services.model_context import ModelContext
from app.services.model_review import ModelReviewService
from app.services.review_records import ReviewRecordService
from tests.unit.test_investigation import make_service
from tests.unit.test_review_records import MemoryReviews


class Model(ModelProviderAbstract):
    def __init__(self):
        self.steps = []
        self.calls = []
        self.closed = False
        self.capabilities = ModelCapabilities(
            provider="meta",
            model_id="muse-spark-1.3",
            adapter_version="test",
            native_tool_calls=False,
            native_structured_output=False,
        )
        self.description_error = None

    def describe(self, model_id):
        if self.description_error:
            raise self.description_error
        return self.capabilities

    async def generate(self, request):
        self.calls.append(request)
        step = self.steps.pop(0)
        if callable(step):
            step = step(request)
        if inspect.isawaitable(step):
            step = await step
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, ModelReply):
            return step
        return ModelReply(
            "meta",
            request.model_id,
            json.dumps(step) if isinstance(step, dict) else step,
            TokenUsage(10, 4, 14),
            {},
        )

    async def close(self):
        self.closed = True


@pytest.fixture
def review_limits(request):
    return getattr(request, "param", ReviewLimits())


@pytest.fixture
def model_timeout(request):
    return getattr(request, "param", 30)


@pytest.fixture
async def review(review_inputs, review_limits, model_timeout):
    broker, repository, reader, clock = make_service(review_limits)
    scope = (await broker.start("head", base="base")).scope
    selected = ModelConfiguration(
        task="review",
        model_id="muse-spark-1.3",
        adapter_version="test",
        max_output_tokens=2048,
    )
    inputs = review_inputs.model_copy(
        update={
            "target_sha": scope.base_sha,
            "merge_base_sha": scope.base_sha,
            "head_sha": scope.head_sha,
            "scope_manifest_sha256": scope.manifest_sha256(),
            "sources": (),
            "settings": ReviewSettings(models=(selected,), limits=broker.limits),
        }
    )
    permission = ("repo.read_snippet", "repo.find_symbol")
    task = ReviewTask(
        skill=inputs.skills[0],
        instructions="Inspect the changed tenant lookup.",
        code_disclosure="public",
        permissions=ReviewPermissions(
            runtime=permission, repository=permission, skill=permission
        ),
    )

    def now():
        return datetime(2026, 1, 15, tzinfo=UTC)

    provider = Model()
    records = ReviewRecordService(MemoryReviews(), now)
    service = ModelReviewService(
        provider,
        broker,
        records,
        lambda frozen, disclosure: ModelContext(frozen, broker, disclosure, now),
        timeout_seconds=model_timeout,
    )
    harness = SimpleNamespace(
        service=service,
        provider=provider,
        broker=broker,
        repository=repository,
        reader=reader,
        clock=clock,
        inputs=inputs,
        task=task,
        records=records,
    )
    yield harness
    await service.close()


async def run(review):
    return await review.service.run("model-run", review.inputs, review.task)


def ask(request, **changes):
    data = json.loads(request.prompt)
    hunk = data["change"]["files"][0]["hunks"][0]["id"]
    return {
        "kind": "request_context",
        "requests": [
            {
                "question_id": "tenant",
                "question": "Does the lookup keep the tenant boundary?",
                "origin_hunk_id": hunk,
                "relationship": "callee",
                "target": "store.py",
                "expected_evidence": "The called query's tenant condition",
                "start_line": 1,
                "end_line": 4,
                **changes,
            }
        ],
    }


def candidate(request, **changes):
    data = json.loads(request.prompt)
    source = data["evidence_catalog"][0]
    hunk = data["change"]["files"][0]["hunks"][0]
    evidence = {
        "source_id": source["source_id"],
        "start": 1,
        "end": 1,
    }
    return {
        "kind": "candidates",
        "findings": [
            {
                "category": "security",
                "severity": "high",
                "anchor": {
                    "path": "customers.py",
                    "side": "RIGHT",
                    "line": 4,
                    "hunk_id": hunk["id"],
                },
                "problem": "The changed lookup is unscoped.",
                "consequence": "Another tenant's record can be returned.",
                "trigger_scenario": "Two tenants share an external ID.",
                "causal_path": [evidence],
                "evidence": [evidence],
                "remediation": "Pass the tenant ID.",
                **changes,
            }
        ],
    }


def answered(request, *, findings=False):
    data = json.loads(request.prompt)
    read = next(item for item in data["reads"] if item["action"] == "read")
    result = candidate(request) if findings else {"kind": "done"}
    result["answers"] = [
        {
            "question_id": "tenant",
            "answer": "The helper's scope is known.",
            "evidence_ids": [read["read_id"]],
        }
    ]
    return result


async def test_context_candidates_and_metadata_are_recorded_without_publication(review):
    review.provider.steps = [ask, lambda request: answered(request, findings=True)]
    report = await run(review)
    assert report.status == "ready" and len(report.result.candidate_findings) == 1
    assert report.result.findings == ()
    assert report.result.usage.model_calls == 2
    assert report.result.usage.input_tokens == 20
    assert report.result.usage.output_tokens == 8
    assert [item.status for item in report.result.model_attempts] == [
        "accepted",
        "accepted",
    ]
    assert [path for _, path in review.repository.calls] == ["customers.py", "store.py"]
    assert {item.id for item in report.result.context_sources} == {
        "diff:lookup-hunk",
        "read-1",
    }
    record = await review.records.get("model-run")
    assert record.status == "validating" and record.progress.result == report.result
    assert record.inputs == review.inputs
    assert all(
        item.requested_model == review.inputs.settings.models[0]
        for item in report.result.model_attempts
    )
    with pytest.raises(ReviewError, match="Unvalidated"):
        await review.records.advance("model-run", "publishing", "Not yet validated")
    with pytest.raises(ReviewError, match="only once"):
        await run(review)


async def test_one_schema_repair_uses_the_same_model_and_budget(review):
    review.provider.steps = ["fixture-sensitive-invalid-body", {"kind": "done"}]
    report = await run(review)
    assert report.status == "ready" and len(review.provider.calls) == 2
    assert [item.repair for item in report.result.model_attempts] == [False, True]
    assert [item.status for item in report.result.model_attempts] == [
        "invalid",
        "accepted",
    ]
    assert json.loads(review.provider.calls[1].prompt)["repair"] is True
    assert "fixture-sensitive-invalid-body" not in report.model_dump_json()
    assert "fixture-sensitive-invalid-body" not in review.provider.calls[1].prompt
    assert report.result.usage.model_calls == 2


@pytest.mark.parametrize(
    "bad",
    [
        "not JSON",
        {"kind": "publish", "destination": "elsewhere"},
        {"kind": "done", "permissions": ["publish"]},
        {
            "kind": "done",
            "limitations": [
                {
                    "code": "missing_context",
                    "reason": "required",
                    "affects_completeness": False,
                }
            ],
        },
    ],
)
async def test_repeated_invalid_output_is_failed_never_a_clean_empty_review(
    review, bad
):
    review.provider.steps = [bad, bad, {"kind": "done"}]
    report = await run(review)
    assert report.status == "failed" and "one schema repair" in report.reason
    assert len(review.provider.calls) == 2 and review.repository.calls == []
    assert (await review.records.get("model-run")).status == "failed"
    assert report.result.candidate_findings == report.result.findings == ()


async def test_repair_allowance_does_not_reset_after_a_valid_context_turn(review):
    review.provider.steps = ["invalid", ask, "invalid again", {"kind": "done"}]
    report = await run(review)
    assert report.status == "failed" and len(review.provider.calls) == 3
    assert [item.repair for item in report.result.model_attempts] == [
        False,
        True,
        False,
    ]


@pytest.mark.parametrize("layer", ["runtime", "repository", "skill"])
async def test_each_permission_layer_can_refuse_reads_before_repository_io(
    review, layer
):
    review.task = review.task.model_copy(
        update={"permissions": review.task.permissions.model_copy(update={layer: ()})}
    )
    review.provider.steps = [ask, {"kind": "done"}]
    report = await run(review)
    assert report.status == "partial" and review.repository.calls == []
    assert any(item.code == "access_denied" for item in report.result.limitations)
    assert json.loads(review.provider.calls[1].prompt)["host_limitations"]


@pytest.mark.parametrize(
    "changes",
    [
        {"target": "../outside.py"},
        {"target": "billing.py"},
        {"target": "test_customer.py"},
        {"parent_read_id": "invented"},
    ],
)
async def test_guessed_or_unapproved_reads_leave_explicit_gaps(review, changes):
    review.provider.steps = [lambda request: ask(request, **changes), {"kind": "done"}]
    report = await run(review)
    assert report.status == "partial"
    assert any(item.action == "denied" for item in report.investigation.reads)
    assert not any(
        path in {"billing.py", "test_customer.py", "../outside.py"}
        for _, path in review.repository.calls
    )
    assert any(item.code == "unresolved_question" for item in report.result.limitations)


async def test_answering_requires_successful_evidence_for_that_question(review):
    review.provider.steps = [
        {
            "kind": "done",
            "answers": [
                {
                    "question_id": "invented",
                    "answer": "Solved",
                    "evidence_ids": ["guessed"],
                }
            ],
        }
    ]
    report = await run(review)
    assert report.status == "failed" and len(review.provider.calls) == 1
    assert review.repository.calls == []


async def test_unknown_origin_is_refused_without_repository_io(review):
    review.provider.steps = [lambda request: ask(request, origin_hunk_id="invented")]
    report = await run(review)
    assert report.status == "failed" and review.repository.calls == []


async def test_model_limitations_always_block_completion(review):
    review.provider.steps = [
        {
            "kind": "done",
            "limitations": [
                {"code": "missing_context", "reason": "Ticket unavailable"}
            ],
        }
    ]
    report = await run(review)
    assert report.status == "partial"
    assert report.result.limitations[0].affects_completeness
    assert (await review.records.get("model-run")).status == "partial"


@pytest.mark.parametrize(
    "changes, attempt_status",
    [
        ({"provider": "other"}, "identity_mismatch"),
        ({"model_id": "different-model"}, "identity_mismatch"),
        ({"status": "incomplete"}, "incomplete"),
        ({"status": "cancelled"}, "incomplete"),
        ({"unsupported_features": ("native_tool_calls",)}, "unsupported"),
    ],
)
async def test_identity_and_unsupported_outputs_stop_without_repair(
    review, changes, attempt_status
):
    reply = ModelReply(
        "meta", "muse-spark-1.3", '{"kind":"done"}', TokenUsage(8, 3, 11), {}
    )
    review.provider.steps = [replace(reply, **changes)]
    report = await run(review)
    assert report.status == "failed" and len(review.provider.calls) == 1
    assert report.result.model_attempts[0].status == attempt_status
    assert report.result.usage.input_tokens == 8
    assert review.repository.calls == []


async def test_unknown_usage_remains_unknown_in_aggregates(review):
    review.provider.steps = [
        "invalid",
        ModelReply("meta", "muse-spark-1.3", '{"kind":"done"}', None, {}),
    ]
    report = await run(review)
    assert report.status == "ready" and report.result.usage.input_tokens is None
    assert report.result.usage.output_tokens is None
    assert report.result.model_attempts[0].input_tokens == 10


async def test_provider_errors_are_safe_recorded_and_not_retried(review):
    review.provider.steps = [ModelError("fixture-sensitive-provider-body")]
    report = await run(review)
    assert report.status == "failed" and len(review.provider.calls) == 1
    assert report.result.model_attempts[0].status == "failed"
    assert report.result.usage.input_tokens is None
    assert "fixture-sensitive-provider-body" not in report.model_dump_json()
    assert (await review.records.get("model-run")).status == "failed"


@pytest.mark.parametrize("model_timeout", [0.01], indirect=True)
async def test_provider_deadline_cancels_work_and_records_timeout(review):
    stopped = asyncio.Event()

    async def stall(request):
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    review.provider.steps = [stall]
    report = await run(review)
    assert report.status == "failed" and stopped.is_set()
    assert [item.status for item in report.result.model_attempts] == ["timeout"]
    assert len(review.provider.calls) == 1


async def test_external_cancellation_is_recorded_and_propagated(review):
    started, stopped = asyncio.Event(), asyncio.Event()

    async def stall(request):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    review.provider.steps = [stall]
    task = asyncio.create_task(run(review))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    record = await review.records.get("model-run")
    assert record.status == "cancelled" and stopped.is_set()
    assert record.progress.result.model_attempts[0].status == "cancelled"
    assert len(review.provider.calls) == 1


@pytest.mark.parametrize(
    "field, value",
    [
        ("head_sha", "c" * 40),
        ("scope_manifest_sha256", "c" * 64),
        ("target_sha", "c" * 40),
        ("merge_base_sha", "c" * 40),
    ],
)
async def test_input_pins_are_checked_before_generation(review, field, value):
    review.inputs = review.inputs.model_copy(update={field: value})
    report = await run(review)
    assert report.status == "failed" and review.provider.calls == []
    assert (await review.records.get("model-run")).status == "failed"


async def test_private_code_is_not_sent_without_host_disclosure_approval(review):
    review.task = review.task.model_copy(update={"code_disclosure": "private"})
    report = await run(review)
    assert report.status == "failed" and review.provider.calls == []


@pytest.mark.parametrize("feature", ["native_tool_calls", "native_structured_output"])
async def test_unsupported_required_features_are_recorded_without_a_paid_attempt(
    review, feature
):
    review.task = review.task.model_copy(update={"required_features": (feature,)})
    report = await run(review)
    assert report.status == "failed" and review.provider.calls == []
    assert report.result.unsupported_features == (feature,)
    assert report.result.model_capabilities is not None


@pytest.mark.parametrize(
    "change",
    [{"adapter_version": "other"}, {"provider": "other"}, {"model_id": "other"}],
)
async def test_capability_identity_must_match_the_frozen_model_configuration(
    review, change
):
    review.provider.capabilities = review.provider.capabilities.model_copy(
        update=change
    )
    report = await run(review)
    assert report.status == "failed" and review.provider.calls == []


async def test_response_after_shared_wall_deadline_never_executes_a_tool(review):
    def overrun(request):
        review.clock.value += review.broker.limits.wall_seconds + 1
        return ask(request)

    review.provider.steps = [overrun]
    report = await run(review)
    assert report.status == "partial" and review.repository.calls == []
    assert any(item.code == "budget" for item in report.result.limitations)
    assert len(review.provider.calls) == 1


@pytest.mark.parametrize(
    "change",
    [
        {
            "anchor": {
                "path": "billing.py",
                "side": "RIGHT",
                "line": 2,
                "hunk_id": "lookup-hunk",
            }
        },
        {"rule_ref": {"id": "invented", "version": "1"}},
    ],
)
async def test_candidates_cannot_claim_unrelated_code_or_unfrozen_rules(review, change):
    review.provider.steps = [lambda request: candidate(request, **change)]
    report = await run(review)
    assert report.status == "failed" and report.result.candidate_findings == ()


@pytest.mark.parametrize(
    "change",
    [
        {"source_id": "invented"},
        {"content_sha256": "0" * 64},
        {"revision": "other"},
        {"end": 1000},
    ],
)
async def test_candidate_citations_must_match_the_supplied_passage(review, change):
    def wrong_evidence(request):
        step = candidate(request)
        step["findings"][0]["evidence"][0].update(change)
        return step

    review.provider.steps = [wrong_evidence, wrong_evidence]
    report = await run(review)
    assert report.status == "failed" and report.result.findings == ()


async def test_a_resolved_backend_revision_is_retained_and_cannot_drift(review):
    def first(request):
        return ModelReply(
            "meta",
            request.model_id,
            json.dumps(ask(request)),
            None,
            {},
            resolved_revision="backend-1",
        )

    review.provider.steps = [
        first,
        ModelReply(
            "meta",
            "muse-spark-1.3",
            '{"kind":"done"}',
            None,
            {},
            resolved_revision="backend-2",
        ),
    ]
    report = await run(review)
    assert report.status == "failed" and len(review.provider.calls) == 2
    assert report.result.model_capabilities.resolved_revision == "backend-1"
    assert [item.resolved_revision for item in report.result.model_attempts] == [
        "backend-1",
        "backend-2",
    ]
    assert report.result.model_attempts[-1].status == "identity_mismatch"


async def test_public_frozen_source_excerpt_is_supplied_without_connector_access(
    review, review_inputs
):
    source = review_inputs.sources[0].model_copy(update={"disclosure": "public"})
    review.inputs = review.inputs.model_copy(update={"sources": (source,)})
    review.provider.steps = [{"kind": "done"}]
    report = await run(review)
    data = json.loads(review.provider.calls[0].prompt)
    supplied = next(
        item for item in data["evidence_catalog"] if item["source_id"] == source.id
    )
    assert supplied["excerpt"] == source.excerpt
    assert "content_sha256" not in supplied and "revision" not in supplied
    assert report.status == "ready" and report.result.usage.source_bytes > len(
        source.excerpt
    )


async def test_frozen_metadata_without_a_passage_is_explicitly_incomplete(
    review, review_inputs
):
    source = review_inputs.sources[0].model_copy(
        update={"disclosure": "public", "excerpt": None}
    )
    review.inputs = review.inputs.model_copy(update={"sources": (source,)})
    review.provider.steps = [{"kind": "done"}]
    report = await run(review)
    assert report.status == "partial"
    assert any(
        item.code == "missing_context" and item.source_id == source.id
        for item in report.result.limitations
    )


async def test_a_frozen_source_cannot_be_replaced_by_a_captured_read_identity(
    review, review_inputs
):
    source = review_inputs.sources[0].model_copy(
        update={"id": "diff:lookup-hunk", "disclosure": "public"}
    )
    review.inputs = review.inputs.model_copy(update={"sources": (source,)})
    report = await run(review)
    assert report.status == "failed" and review.provider.calls == []
    assert "conflicts" in report.reason


async def test_nonpublic_source_cannot_be_sent_under_public_only_permissions(
    review, review_inputs
):
    source = review_inputs.sources[0].model_copy(update={"disclosure": "private"})
    review.inputs = review.inputs.model_copy(update={"sources": (source,)})
    report = await run(review)
    assert report.status == "failed" and review.provider.calls == []


async def test_missing_required_skill_and_model_description_fail_before_generation(
    review,
):
    review.task = review.task.model_copy(
        update={"skill": review.task.skill.model_copy(update={"id": "unknown"})}
    )
    report = await run(review)
    assert report.status == "failed" and review.provider.calls == []


async def test_model_description_errors_are_safe_and_recorded(review):
    review.provider.description_error = ModelError("fixture-sensitive-description")
    report = await run(review)
    assert report.status == "failed" and review.provider.calls == []
    assert "fixture-sensitive-description" not in report.model_dump_json()


@pytest.mark.parametrize("review_limits", [ReviewLimits(model_calls=1)], indirect=True)
async def test_context_loop_stops_when_the_shared_model_attempt_limit_is_reached(
    review,
):
    review.provider.steps = [ask, {"kind": "done"}]
    report = await run(review)
    assert report.status == "partial" and len(review.provider.calls) == 1
    assert report.result.usage.model_calls == 1
    assert any(item.code == "budget" for item in report.result.limitations)
    assert (await review.records.get("model-run")).status == "partial"


@pytest.mark.parametrize(
    "review_limits", [ReviewLimits(source_bytes=40)], indirect=True
)
async def test_repair_context_resupply_cannot_bypass_the_shared_byte_limit(review):
    review.provider.steps = ["invalid", {"kind": "done"}]
    report = await run(review)
    assert report.status == "partial" and len(review.provider.calls) == 1
    assert report.result.model_attempts[0].status == "invalid"
    assert any("source_bytes" in item.reason for item in report.result.limitations)


@pytest.mark.parametrize(
    "review_limits", [ReviewLimits(changed_lines=1)], indirect=True
)
async def test_wholly_omitted_changes_never_trigger_a_paid_call_or_a_clean_result(
    review,
):
    report = await run(review)
    assert report.status == "partial" and review.provider.calls == []
    assert report.investigation.scope.files == ()
    assert any(item.code == "scope_excluded" for item in report.result.limitations)


@pytest.mark.parametrize("excerpt", ["", " \n\t\n"])
async def test_supplied_empty_or_whitespace_code_passages_are_retained_exactly(
    review, review_inputs, excerpt
):
    import hashlib

    source = review_inputs.sources[0].model_copy(
        update={
            "kind": "code",
            "disclosure": "public",
            "excerpt": excerpt,
            "content_sha256": hashlib.sha256(excerpt.encode()).hexdigest(),
        }
    )
    review.inputs = review.inputs.model_copy(update={"sources": (source,)})
    review.provider.steps = [{"kind": "done"}]
    report = await run(review)
    catalog = json.loads(review.provider.calls[0].prompt)["evidence_catalog"]
    assert (
        next(item for item in catalog if item["source_id"] == source.id)["excerpt"]
        == excerpt
    )
    assert report.status == "ready" and report.result.limitations == ()
