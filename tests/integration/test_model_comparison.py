import json
from pathlib import Path

import pytest

from app import dependencies
from app.core.errors import ModelError, ReviewError
from app.schemas.skill import ModelProfile
from app.services.model_comparison import ModelComparisonService
from tests.integration.test_local_review import Harness, finding, verdicts

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
async def comparison(initialized):
    catalog = await dependencies.build_skill_catalog(ROOT / "skills").load()
    skill = catalog.get("rush.team-standards")
    skill = skill.model_copy(
        update={
            "examples": skill.examples.model_copy(
                update={
                    "examples": tuple(
                        example
                        for example in skill.examples.examples
                        if example.case in {"unsafe", "safe"}
                    )
                }
            )
        }
    )
    harness = Harness(initialized, catalog)
    calls = []

    async def run(skill, example, repetition):
        calls.append((skill, example.case, repetition))
        harness.provider.capabilities = harness.provider.capabilities.model_copy(
            update={"model_id": skill.model.model_id}
        )
        harness.provider.steps = (
            [finding, verdicts("keep")]
            if example.case == "unsafe"
            else [{"kind": "done"}]
        )
        return await harness.service.finish(
            await harness.review(
                example.case,
                skills=(skill,),
                run_id=f"{skill.model.model_id}-{repetition}-{example.case}",
            )
        )

    return harness, skill, calls, run


async def test_same_pinned_examples_run_three_times_per_configuration(comparison):
    harness, skill, calls, run = comparison
    profiles = tuple(
        ModelProfile(model_id=model, adapter_version="0.2.0", max_output_tokens=2048)
        for model in ("muse-spark-1.3", "muse-wonder-1.0")
    )
    checkpoints = []
    service = ModelComparisonService(run, lambda: 1.0)
    result = await service.run(
        (skill,),
        profiles,
        "simulated",
        lambda report: checkpoints.append(json.loads(json.dumps(report))),
    )
    assert result["complete"] and result["passed"] and result["mode"] == "simulated"
    assert len(result["runs"]) == 12
    assert len(checkpoints) == 14 and checkpoints[0]["complete"] is False
    assert all(
        item.pin == skill.pin and item.instructions == skill.instructions
        for item, _, _ in calls
    )
    assert {item.model for item, _, _ in calls} == set(profiles)
    assert all(item["comparison"]["model_calls"] > 0 for item in result["runs"])
    assert {call.model_id for call in harness.provider.calls} == {
        profile.model_id for profile in profiles
    }


async def test_failures_and_misses_remain_visible_without_fallback(comparison):
    _, skill, calls, run = comparison
    profile = skill.model

    async def failing(selected, example, repetition):
        if repetition == 2:
            raise ModelError("private response must not be recorded")
        outcome = await run(selected, example, repetition)
        if example.case == "unsafe":
            result = outcome.record.progress.result.model_copy(update={"findings": ()})
            outcome = outcome.model_copy(
                update={
                    "record": outcome.record.model_copy(
                        update={
                            "progress": outcome.record.progress.model_copy(
                                update={"result": result}
                            )
                        }
                    )
                }
            )
        return outcome

    result = await ModelComparisonService(failing, lambda: 1.0).run(
        (skill,), (profile,), "simulated", lambda _: None
    )
    assert result["complete"] and not result["passed"]
    assert len(result["runs"]) == 6
    assert sum("error" in item for item in result["runs"]) == 2
    assert (
        sum(bool(item.get("comparison", {}).get("missed")) for item in result["runs"])
        == 2
    )
    assert "private response" not in json.dumps(result)
    assert all(item.model == profile for item, _, _ in calls)


async def test_cancellation_preserves_an_incomplete_checkpoint(comparison):
    import asyncio

    _, skill, _, _ = comparison
    checkpoints = []

    async def cancelled(*args):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await ModelComparisonService(cancelled, lambda: 1.0).run(
            (skill,),
            (skill.model,),
            "simulated",
            lambda report: checkpoints.append(json.loads(json.dumps(report))),
        )
    assert len(checkpoints) == 1 and not checkpoints[0]["complete"]


@pytest.mark.parametrize("empty", ["skills", "profiles", "duplicate"])
async def test_invalid_matrix_cannot_be_reported_as_a_pass(comparison, empty):
    _, skill, _, run = comparison
    with pytest.raises(ReviewError):
        await ModelComparisonService(run, lambda: 1.0).run(
            () if empty == "skills" else (skill,),
            ()
            if empty == "profiles"
            else (skill.model, skill.model)
            if empty == "duplicate"
            else (skill.model,),
            "simulated",
            lambda _: None,
        )


async def test_planning_never_builds_a_model_or_changes_approvals(
    tmp_path, monkeypatch
):
    from scripts.compare_models import compare

    before = (ROOT / "skills/approved.json").read_bytes()

    def forbidden(*args):
        raise AssertionError("Planning must not build a model")

    monkeypatch.setattr(dependencies, "_build_model_provider", forbidden)
    output = tmp_path / "plan.json"
    assert await compare(output, False) == 0
    plan = json.loads(output.read_text())
    assert plan["status"] == "not_run" and plan["repetitions"] == 3
    assert len(plan["models"]) == 2 and "runs" not in plan
    assert (ROOT / "skills/approved.json").read_bytes() == before


async def test_targeted_recheck_plan_is_labelled_and_validated(tmp_path):
    from scripts.compare_models import compare

    output = tmp_path / "subset.json"
    assert await compare(output, False, ("rush.team-standards",), ("unsafe",)) == 0
    plan = json.loads(output.read_text())
    assert (
        plan["selection"] == "targeted subset" and plan["examples_per_repetition"] == 1
    )
    with pytest.raises(ReviewError, match="not an example"):
        await compare(output, False, ("rush.team-standards",), ("not-a-case",))


async def test_script_live_path_records_controlled_response_failures(
    tmp_path, monkeypatch
):
    from app.models.model_access import ModelReply
    from scripts.compare_models import compare
    from tests.unit.test_model_review import Model

    calls = []

    class Incomplete(Model):
        def describe(self, model_id):
            return self.capabilities.model_copy(
                update={"model_id": model_id, "adapter_version": "0.2.0"}
            )

        async def generate(self, request):
            calls.append(request)
            return ModelReply(
                "meta",
                request.model_id,
                '{"kind":"done"}',
                None,
                {},
                status="incomplete",
            )

    monkeypatch.setattr(dependencies, "_build_model_provider", lambda _: Incomplete())
    output = tmp_path / "controlled.json"
    assert await compare(output, True) == 1
    result = json.loads(output.read_text())
    assert result["complete"] and not result["passed"]
    assert len(result["runs"]) == 66
    assert {call.model_id for call in calls} == {"muse-spark-1.3", "muse-wonder-1.0"}
    assert all(item["actual"]["status"] == "failed" for item in result["runs"])
    assert all(
        item["actual"]["attempts"][0]["status"] == "incomplete"
        for item in result["runs"]
    )


async def test_nonpublic_sources_cannot_be_persisted_in_comparison(comparison):
    _, skill, _, run = comparison

    async def private(selected, example, repetition):
        outcome = await run(selected, example, repetition)
        sources = tuple(
            source.model_copy(
                update={"disclosure": "private", "excerpt": "private-canary"}
            )
            for source in outcome.record.inputs.sources
        )
        return outcome.model_copy(
            update={
                "record": outcome.record.model_copy(
                    update={
                        "inputs": outcome.record.inputs.model_copy(
                            update={"sources": sources}
                        )
                    }
                )
            }
        )

    result = await ModelComparisonService(private, lambda: 1.0).run(
        (skill,), (skill.model,), "simulated", lambda _: None
    )
    assert not result["passed"]
    assert all(item["error"] == "ReviewError" for item in result["runs"])
    assert "private-canary" not in json.dumps(result)
