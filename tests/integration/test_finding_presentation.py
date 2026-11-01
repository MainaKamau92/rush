import asyncio
import json
from pathlib import Path

import pytest

from app import dependencies
from app.core.errors import ModelError, ReviewError
from app.models.model_access import ModelReply
from app.schemas.review import PresentationSettings, ReviewLimits
from app.services.disclosure import DisclosureService
from app.services.finding_presentation import FindingPresentationService
from app.services.github_commands import review_settings
from app.services.review_budget import ReviewBudget
from tests.integration.test_local_review import Harness, finding, verdicts
from tests.unit.test_model_review import Model

WORDING = {
    "problem": "The customer lookup can cross tenant boundaries.",
    "connection": "The changed call omits tenant_id.",
    "consequence": "A customer from another tenant can be returned.",
    "example": "A shared customer identifier can select the other tenant's customer.",
    "remediation": "Pass tenant_id to find_customer.",
}


@pytest.fixture
async def styled(initialized, monkeypatch):
    catalog = await dependencies.build_skill_catalog(Path("skills")).load()
    harness = Harness(initialized, catalog)
    formatter = Model()
    formatter.capabilities = harness.provider.capabilities
    formatter.steps = [WORDING]
    providers = iter((harness.provider, formatter))
    monkeypatch.setattr(
        dependencies, "_build_model_provider", lambda _: next(providers)
    )
    harness.service = dependencies.build_local_review(initialized, catalog)
    harness.records = dependencies.build_review_records(initialized)
    harness.provider.steps = [
        {"kind": "done"},
        finding,
        {"kind": "done"},
        verdicts("keep"),
    ]
    return harness, formatter


@pytest.mark.parametrize("complexity", ["plain", "technical"])
@pytest.mark.parametrize("verbosity", ["short", "detailed"])
async def test_initial_wording_is_frozen_without_changing_the_finding(
    styled, complexity, verbosity
):
    harness, formatter = styled
    style = PresentationSettings(complexity=complexity, verbosity=verbosity)
    outcome = await harness.service.finish(await harness.review(presentation=style))
    record = await harness.records.get(outcome.record.id)
    result = record.progress.result
    assert record.status == "completed" and record.inputs.settings.presentation == style
    assert result.findings[0].problem == "The lookup no longer passes the tenant."
    assert result.findings[0].severity == "high"
    assert result.findings[0].rule_ref.id == "lantern.tenant-lookup"
    assert result.presentations[0].finding_id == result.findings[0].id
    assert result.presentations[0].wording.model_dump() == WORDING
    assert result.presentations[0].settings == style
    assert result.presentation_notes == () and result.usage.model_calls == 5
    assert result.usage.input_tokens == 50 and result.usage.output_tokens == 20
    request = json.loads(formatter.calls[0].prompt)
    assert request["settings"] == style.model_dump()
    assert request["evidence"] and formatter.closed
    assert result.model_attempts[-1].requested_model.task == "clarification"


@pytest.mark.parametrize("cap", [4, 5])
async def test_wording_and_its_repair_share_the_remaining_review_budget(styled, cap):
    harness, formatter = styled

    formatter.steps = ["invalid", WORDING]
    outcome = await harness.service.finish(
        await harness.review(
            presentation=PresentationSettings(),
            limits=ReviewLimits(model_calls=cap),
        )
    )
    result = outcome.record.progress.result
    assert outcome.record.status == "completed" and result.findings
    assert result.presentations == () and result.presentation_notes
    assert result.usage.model_calls == cap
    assert len(formatter.calls) == cap - 4
    assert formatter.closed == (cap > 4)


@pytest.mark.parametrize(
    "failure", ["invalid", "transport", "identity", "incomplete", "unsupported"]
)
async def test_wording_failure_keeps_the_validated_review(styled, failure):
    harness, formatter = styled
    replies = {
        "invalid": ["[]", {**WORDING, "severity": "low"}],
        "transport": [ModelError("fictional failure")],
        "identity": [
            ModelReply("another", "muse-spark-1.3", json.dumps(WORDING), None, {})
        ],
        "incomplete": [
            ModelReply(
                "meta",
                "muse-spark-1.3",
                json.dumps(WORDING),
                None,
                {},
                status="incomplete",
            )
        ],
        "unsupported": [
            ModelReply(
                "meta",
                "muse-spark-1.3",
                json.dumps(WORDING),
                None,
                {},
                unsupported_features=("fictional",),
            )
        ],
    }
    formatter.steps = replies[failure]
    outcome = await harness.service.finish(
        await harness.review(presentation=PresentationSettings())
    )
    result = outcome.record.progress.result
    assert outcome.record.status == "completed"
    assert result.findings[0].severity == "high" and not result.presentations
    assert result.presentation_notes and formatter.closed
    assert result.usage.model_calls == 4 + len(formatter.calls)
    assert result.model_attempts[-1].status in {
        "invalid",
        "failed",
        "identity_mismatch",
        "incomplete",
    }
    if failure != "invalid":
        assert result.usage.input_tokens is None and result.usage.output_tokens is None


async def test_one_schema_repair_is_recorded(styled):
    harness, formatter = styled
    formatter.steps = ["invalid", WORDING]
    outcome = await harness.review(presentation=PresentationSettings())
    result = outcome.record.progress.result
    assert [attempt.status for attempt in result.model_attempts[-2:]] == [
        "invalid",
        "accepted",
    ]
    assert result.model_attempts[-1].repair
    assert result.presentations and result.usage.model_calls == 6


async def test_blank_prose_is_repaired_or_disclosed_as_fallback(styled):
    harness, formatter = styled
    formatter.steps = [{key: " \n\t" for key in WORDING}, WORDING]
    outcome = await harness.review(presentation=PresentationSettings())
    result = outcome.record.progress.result
    assert result.presentations[0].wording.model_dump() == WORDING
    assert [attempt.status for attempt in result.model_attempts[-2:]] == [
        "invalid",
        "accepted",
    ]


async def test_validation_delay_uses_the_live_investigation_deadline(
    styled, monkeypatch
):
    harness, formatter = styled
    original = dependencies.FindingValidationService._settle
    tick = [0.0]

    def delayed(service, *args):
        settled = original(service, *args)
        tick[0] = 10000.0
        return settled

    monkeypatch.setattr(
        dependencies,
        "ReviewBudget",
        lambda limits, _: ReviewBudget(limits, lambda: tick[0]),
    )
    monkeypatch.setattr(dependencies.FindingValidationService, "_settle", delayed)
    outcome = await harness.review(presentation=PresentationSettings())
    assert not formatter.calls
    assert outcome.record.progress.result.findings
    assert outcome.record.progress.result.presentation_notes


async def test_prompt_preparation_does_not_extend_the_deadline(styled):
    harness, previous = styled
    outcome = await harness.review(presentation=PresentationSettings())
    provider = Model()
    provider.capabilities = previous.capabilities
    elapsed = iter((0.0, 0.0, 10000.0))
    service = FindingPresentationService(
        lambda: provider,
        harness.records,
        dependencies.time.monotonic,
        allowed=("public",),
        publishable=("public",),
        audience="public",
    )
    result = await service.render(
        outcome.record,
        outcome.record.progress.result,
        outcome.investigation,
        lambda: next(elapsed),
    )
    assert not provider.calls and provider.closed
    assert not result.presentations and result.presentation_notes


async def test_unknown_usage_stays_unknown(styled):
    harness, formatter = styled
    formatter.steps = [
        ModelReply("meta", "muse-spark-1.3", json.dumps(WORDING), None, {})
    ]
    result = (
        await harness.review(presentation=PresentationSettings())
    ).record.progress.result
    assert result.presentations and result.usage.input_tokens is None
    assert result.usage.output_tokens is None


async def test_cancelled_wording_saves_attempt_and_canonical_finding(styled):
    harness, formatter = styled
    formatter.steps = [asyncio.CancelledError()]
    with pytest.raises(asyncio.CancelledError):
        await harness.review(presentation=PresentationSettings())
    record = await harness.records.get("run-unsafe")
    assert record.status == "cancelled" and record.progress.result.findings
    assert record.progress.result.model_attempts[-1].status == "cancelled"
    assert record.progress.result.usage.model_calls == 5 and formatter.closed


async def test_public_redaction_also_removes_presentations(styled):
    harness, _ = styled
    outcome = await harness.review(presentation=PresentationSettings())
    public = DisclosureService(()).for_audience(outcome, "public", "public")
    assert public.withheld and not public.record.progress.result.presentations
    assert not public.record.progress.result.presentation_notes
    assert WORDING["problem"] not in public.model_dump_json()


@pytest.mark.parametrize(
    "guard", ["publish", "disclosure", "time", "size", "describe", "timeout"]
)
async def test_wording_guards_prevent_unapproved_or_unbounded_calls(styled, guard):
    harness, previous = styled
    outcome = await harness.review(presentation=PresentationSettings())
    record = outcome.record
    result = record.progress.result.model_copy(update={"presentations": ()})
    provider = Model()
    provider.capabilities = previous.capabilities
    provider.steps = [lambda _: asyncio.sleep(0.1)]
    if guard in {"publish", "disclosure"}:
        record = record.model_copy(
            update={
                "inputs": record.inputs.model_copy(
                    update={
                        "sources": tuple(
                            source.model_copy(update={"disclosure": "private"})
                            for source in record.inputs.sources
                        ),
                    }
                )
            }
        )
    if guard == "size":
        record = record.model_copy(
            update={
                "inputs": record.inputs.model_copy(
                    update={
                        "settings": record.inputs.settings.model_copy(
                            update={
                                "limits": record.inputs.settings.limits.model_copy(
                                    update={"source_bytes": 1}
                                )
                            }
                        ),
                    }
                )
            }
        )
    if guard == "describe":
        provider.description_error = ModelError("Unavailable")
    service = FindingPresentationService(
        lambda: provider,
        harness.records,
        dependencies.time.monotonic,
        allowed=("public",) if guard == "disclosure" else ("public", "private"),
        publishable=("public",),
        audience="public" if guard == "publish" else "private",
        timeout=0.001,
    )
    report = (
        outcome.investigation.model_copy(update={"elapsed_seconds": 10000})
        if guard == "time"
        else outcome.investigation
    )
    rendered = await service.render(record, result, report)
    assert rendered.findings == result.findings and not rendered.presentations
    assert len(provider.calls) == (1 if guard == "timeout" else 0)
    if guard == "timeout":
        assert rendered.model_attempts[-1].status == "timeout"
        assert rendered.usage.input_tokens is None
    assert provider.closed == (guard not in {"publish", "disclosure", "time"})


@pytest.mark.parametrize("change", ["finding_id", "settings", "duplicate"])
async def test_saved_presentation_cannot_change_its_identity_or_preferences(
    styled, change
):
    harness, _ = styled
    outcome = await harness.review(presentation=PresentationSettings())
    result = outcome.record.progress.result
    presentation = result.presentations[0]
    presentations = (
        (presentation, presentation)
        if change == "duplicate"
        else (
            presentation.model_copy(
                update={
                    change: "other"
                    if change == "finding_id"
                    else PresentationSettings(verbosity="detailed")
                }
            ),
        )
    )
    with pytest.raises(ReviewError, match="Presentation"):
        await harness.records.advance(
            outcome.record.id,
            "completed",
            "Ready",
            result.model_copy(update={"presentations": presentations}),
        )


@pytest.mark.parametrize(
    "command",
    [
        "/rush review verbosity=verbose",
        "/rush review complexity=hard",
        "/rush review verbosity=short verbosity=detailed",
        "/rush review unknown=value",
        "/rush reviewplease",
        "",
        "/rush explain verbosity=short",
    ],
)
def test_invalid_review_overrides_are_not_accepted(command):
    assert review_settings(command) is None


def test_review_overrides_are_independent_of_each_other_and_followup_prose():
    defaults = PresentationSettings(complexity="technical", verbosity="detailed")
    assert review_settings(
        "/rush REVIEW verbosity=short\ncomplexity=plain", defaults
    ) == PresentationSettings(complexity="technical", verbosity="short")
