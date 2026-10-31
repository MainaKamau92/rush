import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal

from app.core.errors import ReviewError
from app.schemas.learning import CaseResult, LearningDraft
from app.schemas.local_review import LocalReviewRequest, ReviewOutcome
from app.schemas.policy import PolicyScope, Rule
from app.schemas.review import RuleRef
from app.schemas.skill import InstalledSkill
from app.services.skill_evaluation import SkillEvaluationService

ExampleReview = Callable[
    [str, LocalReviewRequest, InstalledSkill], Awaitable[ReviewOutcome]
]
EVALUATOR = "rush learning evaluation"


class LearningEvaluationService:
    def __init__(
        self,
        review: ExampleReview,
        request: Callable[[str, str], LocalReviewRequest],
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
    ):
        self._review, self._request = review, request
        self._clock, self._new_id = clock, new_id

    async def evaluate(
        self, draft: LearningDraft, rule: Rule, skill: InstalledSkill
    ) -> tuple[CaseResult, ...]:
        examples = draft.examples
        if set(examples.violating) & set(examples.acceptable):
            raise ReviewError("An example cannot be both violating and acceptable")
        labelled = set(examples.violating) | set(examples.acceptable)
        missing = {example.case for example in skill.examples.examples} - labelled
        if missing:
            raise ReviewError(
                "Label every affected skill example for the proposed rule: "
                + ", ".join(sorted(missing))
            )
        trial = rule.model_copy(
            update={
                "status": "approved",
                "approved_by": EVALUATOR,
                "approved_at": self._clock(),
                "scope": PolicyScope(path="**"),
            }
        )
        cases = []
        planned: list[tuple[str, Literal["violating", "acceptable"]]] = [
            *((name, "violating") for name in dict.fromkeys(examples.violating)),
            *((name, "acceptable") for name in dict.fromkeys(examples.acceptable)),
        ]
        for name, expected in planned:
            request = self._request(name, self._new_id())
            request = request.model_copy(
                update={
                    "rules": json.dumps([trial.model_dump(mode="json")]),
                    "exceptions": None,
                    "approvers": (EVALUATOR,),
                    "review_time": self._clock(),
                    "context": tuple(
                        item for item in request.context if item.kind == "ticket"
                    ),
                }
            )
            outcome = await self._review(name, request, skill)
            count = sum(
                item.rule_ref == RuleRef(id=rule.id, version=rule.version)
                for item in outcome.record.progress.result.findings
            )
            status: Literal["passed", "failed", "incomplete"] = "incomplete"
            if outcome.record.status == "completed":
                status = (
                    "passed" if bool(count) == (expected == "violating") else "failed"
                )
            cases.append(
                CaseResult(
                    case=name,
                    expected=expected,
                    status=status,
                    rule_findings=count,
                    run_status=outcome.record.status,
                )
            )
        for example in skill.examples.examples:
            outcome = await self._review(
                example.case, self._request(example.case, self._new_id()), skill
            )
            matched = SkillEvaluationService().compare(example, outcome)
            cases.append(
                CaseResult(
                    case=example.case,
                    purpose="skill_regression",
                    expected=example.kind,
                    status="passed" if matched.passed else "failed",
                    rule_findings=len(outcome.record.progress.result.findings),
                    run_status=outcome.record.status,
                )
            )
        return tuple(cases)
