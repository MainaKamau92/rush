import hashlib
import json
from collections.abc import Mapping
from typing import Literal

from app.schemas.code_change import ChangeScope
from app.schemas.local_review import ReviewOutcome, WithdrawnProposal
from app.schemas.model_review import ModelReviewReport, Proposal
from app.schemas.review import Finding, FindingDraft, Limitation
from app.schemas.skill import InstalledSkill
from app.services.review_records import ReviewRecordService
from app.services.review_skills import path_matches


def _changed_line(scope: ChangeScope, proposal: Proposal) -> tuple[int, str] | None:
    anchor = proposal.finding.anchor
    kind = "added" if anchor.side == "RIGHT" else "removed"
    for file in scope.files:
        if (file.new_path if anchor.side == "RIGHT" else file.old_path) != anchor.path:
            continue
        for hunk in file.hunks:
            if hunk.id != anchor.hunk_id:
                continue
            for position, line in enumerate(hunk.lines, start=1):
                number = line.new_line if anchor.side == "RIGHT" else line.old_line
                if number == anchor.line and line.kind == kind:
                    return position, line.text
    return None


class FindingValidationService:
    def __init__(self, records: ReviewRecordService) -> None:
        self._records = records

    async def validate(
        self, report: ModelReviewReport, skills: Mapping[str, InstalledSkill]
    ) -> ReviewOutcome:
        record = await self._records.get(report.run_id)
        scope = report.investigation.scope
        if record.status != "validating" or scope is None:
            return ReviewOutcome(record=record, investigation=report.investigation)
        kept: list[tuple[Proposal, str]] = []
        withdrawn: list[WithdrawnProposal] = []
        questions: list[Limitation] = []
        for proposal in report.proposals:
            finding, verdict = proposal.finding, proposal.verdict
            location = f"{finding.anchor.path}:{finding.anchor.line}"
            line = _changed_line(scope, proposal)
            problem = self._host_problem(proposal, line, skills.get(proposal.skill.id))
            if problem:
                withdrawn.append(self._withdraw(proposal, "host", problem))
            elif verdict is None:
                questions.append(
                    self._question(
                        location, "No critique pass challenged it", blocking=True
                    )
                )
            elif verdict.verdict == "withdraw":
                withdrawn.append(self._withdraw(proposal, "critique", verdict.reason))
            elif verdict.verdict == "question":
                questions.append(self._question(location, verdict.question))
            else:
                kept.append((proposal, line[1] if line else ""))
        findings: list[Finding] = []
        seen: dict[tuple[str, str, int], Finding] = {}
        for proposal, text in sorted(
            kept, key=lambda item: item[0].finding.rule_ref is None
        ):
            anchor = proposal.finding.anchor
            key = (anchor.path, anchor.side, anchor.line)
            if key in seen:
                withdrawn.append(
                    self._withdraw(
                        proposal,
                        "host",
                        f"Repeats finding {seen[key].id} at the same changed line",
                    )
                )
                continue
            seen[key] = self._canonical(
                report.run_id, len(findings) + 1, proposal, text
            )
            findings.append(seen[key])
        result = report.result.model_copy(
            update={
                "findings": tuple(findings),
                "candidate_findings": (),
                "limitations": (*report.result.limitations, *questions),
            }
        )
        if any(item.affects_completeness for item in result.limitations):
            record = await self._records.advance(
                report.run_id,
                "partial",
                "Review finished with limitations that affect completeness",
                result,
            )
        else:
            record = await self._records.advance(
                report.run_id,
                "publishing",
                "Findings validated; writing the review report",
                result,
            )
        return ReviewOutcome(
            record=record,
            investigation=report.investigation,
            withdrawn=tuple(withdrawn),
        )

    async def finish(self, outcome: ReviewOutcome) -> ReviewOutcome:
        if outcome.record.status != "publishing":
            return outcome
        record = await self._records.advance(
            outcome.record.id, "completed", "Review report ready"
        )
        return outcome.model_copy(update={"record": record})

    @staticmethod
    def _host_problem(
        proposal: Proposal,
        line: tuple[int, str] | None,
        skill: InstalledSkill | None,
    ) -> str | None:
        finding = proposal.finding
        if skill is None:
            return "Proposal names a skill that was not selected for this review"
        if line is None:
            return "Anchored line is unchanged context, so this change does not add it"
        if not any(
            path_matches(pattern, finding.anchor.path)
            for pattern in skill.manifest.scope.paths
        ):
            return "Anchored file is outside the skill's scope"
        hunk = f"diff:{finding.anchor.hunk_id}"
        if not any(
            item.source_id == hunk and item.start <= line[0] <= item.end
            for item in (*finding.evidence, *finding.causal_path)
        ):
            return "Evidence does not quote the changed line the finding is anchored to"
        allowed = skill.manifest.rule_ids
        if finding.rule_ref and allowed and finding.rule_ref.id not in allowed:
            return "Cited rule is outside the skill's approved rules"
        return None

    @staticmethod
    def _withdraw(
        proposal: Proposal, by: Literal["critique", "host"], reason: str
    ) -> WithdrawnProposal:
        return WithdrawnProposal(
            skill=proposal.skill, finding=proposal.finding, by=by, reason=reason
        )

    @staticmethod
    def _question(
        location: str, question: str | None, *, blocking: bool = False
    ) -> Limitation:
        return Limitation(
            code="unresolved_question",
            reason=f"{location}: {question or 'Essential assumption is unsupported'}",
            affects_completeness=blocking,
        )

    @staticmethod
    def _canonical(run_id: str, number: int, proposal: Proposal, line: str) -> Finding:
        draft, anchor = proposal.finding, proposal.finding.anchor
        rule = draft.rule_ref
        fingerprint = hashlib.sha256(
            json.dumps(
                [
                    proposal.skill.id,
                    rule.id if rule else None,
                    rule.version if rule else None,
                    draft.category,
                    anchor.path,
                    anchor.side,
                    line.strip(),
                ]
            ).encode()
        ).hexdigest()
        return Finding(
            **{name: getattr(draft, name) for name in FindingDraft.model_fields},
            id=f"{run_id}-{number}",
            fingerprint=fingerprint,
            run_id=run_id,
            skill=proposal.skill,
            verification="code_inspected",
        )
