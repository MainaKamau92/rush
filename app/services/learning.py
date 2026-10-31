import hashlib
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Literal

from app.core.errors import ReviewError
from app.schemas.learning import (
    CaseResult,
    LearningDraft,
    LearningEvaluation,
    LearningProposal,
)
from app.schemas.policy import Rule
from app.schemas.review import ModelConfiguration, RuleRef, VersionPin
from app.services.ports import LearningRepository

Evaluator = Callable[
    [LearningDraft, Rule],
    Awaitable[tuple[VersionPin, ModelConfiguration, tuple[CaseResult, ...]]],
]
SHORT_DIGEST = 12


class LearningService:
    """
    Turn an explicit learning request into an inactive, versioned proposal that
    becomes a rule only after it passes evaluation and an authorized approval.
    """

    def __init__(
        self,
        repository: LearningRepository,
        approvers: frozenset[str],
        clock: Callable[[], datetime],
        new_id: Callable[[], str],
    ) -> None:
        self._repository, self._approvers = repository, approvers
        self._clock, self._new_id = clock, new_id

    @staticmethod
    def digest(draft: LearningDraft) -> str:
        text = json.dumps(draft.model_dump(mode="json"), sort_keys=True)
        return hashlib.sha256(text.encode()).hexdigest()

    @staticmethod
    def rule(proposal: LearningProposal) -> Rule:
        draft = proposal.draft
        return Rule(
            id=draft.rule_id,
            version=str(proposal.revision),
            statement=draft.statement,
            rationale=draft.rationale,
            category=draft.category,
            owner=draft.owner,
            scope=draft.scope,
            waivable=draft.waivable,
            overridable=False,
            status="approved" if proposal.approved_by else "proposed",
            approved_by=proposal.approved_by,
            approved_at=proposal.approved_at,
            source=f"learning:{proposal.id}@{proposal.revision}",
        )

    async def propose(self, draft: LearningDraft, proposer: str) -> LearningProposal:
        taken = {item.draft.rule_id: item.id for item in await self.proposals()}
        if draft.rule_id in taken:
            raise ReviewError(
                f"Proposal {taken[draft.rule_id]} already uses rule ID {draft.rule_id}"
            )
        now = self._clock()
        proposal = LearningProposal(
            id=self._new_id(),
            revision=1,
            draft=draft,
            content_sha256=self.digest(draft),
            status="proposed",
            proposer=proposer,
            created_at=now,
            updated_at=now,
        )
        await self._repository.save(proposal)
        return proposal

    async def revise(self, proposal_id: str, draft: LearningDraft) -> LearningProposal:
        current = await self.show(proposal_id)
        if current.status == "approved":
            raise ReviewError("An approved proposal cannot change; propose a new rule")
        if draft.rule_id != current.draft.rule_id:
            raise ReviewError("A revision must keep the proposal's rule ID")
        if self.digest(draft) == current.content_sha256:
            return current
        revised = current.model_copy(
            update={
                "revision": current.revision + 1,
                "draft": draft,
                "content_sha256": self.digest(draft),
                "status": "proposed",
                "evaluation": None,
                "updated_at": self._clock(),
            }
        )
        await self._repository.save(revised, current)
        return revised

    async def evaluate(
        self, proposal_id: str, evaluator: Evaluator
    ) -> LearningProposal:
        current = await self.show(proposal_id)
        if current.status == "approved":
            raise ReviewError("The proposal is already approved")
        examples = current.draft.examples
        if not (examples.violating and examples.acceptable):
            raise ReviewError(
                "Add at least one violating and one acceptable example first"
            )
        rule = self.rule(current)
        skill, model, cases = await evaluator(current.draft, rule)
        passed = bool(cases) and all(case.status == "passed" for case in cases)
        evaluated = current.model_copy(
            update={
                "evaluation": LearningEvaluation(
                    content_sha256=current.content_sha256,
                    rule=RuleRef(id=rule.id, version=rule.version),
                    skill=skill,
                    model=model,
                    cases=cases,
                    passed=passed,
                    evaluated_at=self._clock(),
                ),
                "status": "evaluated" if passed else "proposed",
                "updated_at": self._clock(),
            }
        )
        await self._repository.save(evaluated, current)
        return evaluated

    async def approve(
        self,
        proposal_id: str,
        content_sha256: str,
        approver: str,
        authorized: bool,
        channel: Literal["github", "cli"] = "cli",
    ) -> tuple[LearningProposal, bool]:
        current = await self.show(proposal_id)
        if approver not in self._approvers or not authorized:
            raise ReviewError(
                f"{approver} is not a designated, currently authorized approver"
            )
        if len(content_sha256) < SHORT_DIGEST or not current.content_sha256.startswith(
            content_sha256
        ):
            raise ReviewError(
                "That is not the current version of the proposal; inspect it again"
            )
        if current.status == "approved":
            return current, False
        evaluation = current.evaluation
        if (
            evaluation is None
            or not evaluation.passed
            or evaluation.content_sha256 != current.content_sha256
        ):
            raise ReviewError(
                "Only a proposal whose current version passed evaluation can be "
                "approved"
            )
        now = self._clock()
        approved = current.model_copy(
            update={
                "status": "approved",
                "approved_by": approver,
                "approved_at": now,
                "approval_channel": channel,
                "updated_at": now,
            }
        )
        await self._repository.save(approved, current, self.rule(approved))
        return approved, True

    async def show(self, proposal_id: str) -> LearningProposal:
        proposal = await self._repository.get(proposal_id)
        if proposal is None:
            raise ReviewError(f"Learning proposal {proposal_id} not found")
        return proposal

    async def proposals(self) -> tuple[LearningProposal, ...]:
        return await self._repository.proposals()

    async def active_rules(self) -> tuple[Rule, ...]:
        return await self._repository.rules()

    async def bundle(self) -> str:
        rules = [rule.model_dump(mode="json") for rule in await self.active_rules()]
        return json.dumps(rules, indent=2) + "\n"
