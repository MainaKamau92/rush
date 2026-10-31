from collections.abc import Awaitable, Callable
from typing import Any, Literal

from app.core.errors import ChangeError, ModelError, ReviewError, SkillError, StateError
from app.schemas.local_review import ReviewOutcome
from app.schemas.skill import InstalledSkill, ModelProfile, SkillExample
from app.services.skill_evaluation import SkillEvaluationService

ExampleRunner = Callable[[InstalledSkill, SkillExample, int], Awaitable[ReviewOutcome]]


class ModelComparisonService:
    def __init__(self, run_example: ExampleRunner, clock: Callable[[], float]):
        self._run_example, self._clock = run_example, clock

    async def run(
        self,
        skills: tuple[InstalledSkill, ...],
        profiles: tuple[ModelProfile, ...],
        mode: Literal["live", "simulated"],
        checkpoint: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        if not skills or not profiles:
            raise ReviewError("Select skills and model configurations to compare")
        if len({profile.model_id for profile in profiles}) != len(profiles):
            raise ReviewError("Each selected model must appear once")
        report: dict[str, Any] = {
            "mode": mode,
            "repetitions": 3,
            "complete": False,
            "passed": False,
            "human_feedback": "Not collected; these are automated fixture results.",
            "matching": "Pass means rule/category/anchor and limit expectations match; "
            "semantic correctness and trigger meaning need human review.",
            "controls": "Run the separate team-control and PR-journey suites; "
            "example matching alone does not verify approval or publication.",
            "configurations": [profile.model_dump(mode="json") for profile in profiles],
            "skills": [skill.pin.model_dump(mode="json") for skill in skills],
            "runs": [],
        }
        checkpoint(report)
        for profile in profiles:
            for repetition in range(1, 4):
                for skill in skills:
                    selected = skill.model_copy(update={"model": profile})
                    for example in skill.examples.examples:
                        result = await self._example(selected, example, repetition)
                        report["runs"].append(result)
                        checkpoint(report)
        report["complete"] = True
        report["passed"] = all(item["passed"] for item in report["runs"])
        checkpoint(report)
        return report

    async def _example(
        self, skill: InstalledSkill, example: SkillExample, repetition: int
    ) -> dict[str, Any]:
        result: dict[str, Any] = {
            "model": skill.model.model_dump(mode="json"),
            "skill": skill.pin.model_dump(mode="json"),
            "case": example.case,
            "repetition": repetition,
            "expected": example.model_dump(mode="json"),
            "passed": False,
        }
        started = self._clock()
        try:
            outcome = await self._run_example(skill, example, repetition)
            sources = (
                *outcome.record.inputs.sources,
                *outcome.record.progress.result.context_sources,
            )
            if any(source.disclosure != "public" for source in sources):
                raise ReviewError("Comparison evidence requires public fixture sources")
            compared = SkillEvaluationService().compare(example, outcome)
            result.update(
                passed=compared.passed,
                actual={
                    "status": outcome.record.status,
                    "target_sha": outcome.record.inputs.target_sha,
                    "base_sha": outcome.record.inputs.merge_base_sha,
                    "head_sha": outcome.record.inputs.head_sha,
                    "findings": [
                        item.model_dump(mode="json")
                        for item in outcome.record.progress.result.findings
                    ],
                    "sources": [source.model_dump(mode="json") for source in sources],
                    "limitations": [
                        item.code for item in outcome.record.progress.result.limitations
                    ],
                    "attempts": [
                        item.model_dump(mode="json", exclude={"response_sha256"})
                        for item in outcome.record.progress.result.model_attempts
                    ],
                },
                comparison=compared.model_dump(mode="json", exclude={"withdrawn"}),
            )
        except (ChangeError, ModelError, ReviewError, SkillError, StateError) as error:
            result.update(error=type(error).__name__, actual={"status": "error"})
        finally:
            result["elapsed_seconds"] = max(0.0, self._clock() - started)
        return result
