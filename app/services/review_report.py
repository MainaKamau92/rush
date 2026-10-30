from typing import Any

from app.schemas.local_review import ReviewOutcome
from app.schemas.review import EvidenceRef, Finding

NOT_EXECUTED = (
    "Findings come from reading the code. No application code or tests were run, "
    "so no finding is backed by execution evidence."
)
COMPLETE_MEANS = (
    "Complete means the configured review work finished within the reviewed "
    "scope. It does not prove the change is correct or secure."
)
HEADLINES = {
    "completed": "Review complete",
    "partial": "Review incomplete",
    "failed": "Review failed",
    "cancelled": "Review cancelled",
    "skipped": "Review skipped",
}


def _evidence(item: EvidenceRef) -> str:
    lines = f"{item.start}" if item.start == item.end else f"{item.start}-{item.end}"
    return f"{item.source_id} lines {lines}"


class ReviewReportService:
    def data(self, outcome: ReviewOutcome) -> dict[str, Any]:
        record, investigation = outcome.record, outcome.investigation
        result = record.progress.result
        scope = investigation.scope
        return {
            "name": "rush",
            "run_id": record.id,
            "status": record.status,
            "reason": record.progress.events[-1].reason,
            "complete": record.status == "completed",
            "complete_means": COMPLETE_MEANS,
            "application_tests_executed": False,
            "withheld": outcome.withheld,
            "verification": NOT_EXECUTED,
            "repository": record.inputs.repository,
            "policy_as_of": record.inputs.review_time.isoformat()
            if record.inputs.review_time
            else None,
            "started_at": record.progress.events[0].at.isoformat(),
            "target_sha": record.inputs.target_sha,
            "base_sha": record.inputs.merge_base_sha,
            "head_sha": record.inputs.head_sha,
            "reviewed_files": [item.new_path or item.old_path for item in scope.files]
            if scope
            else [],
            "omitted_files": [item.model_dump(mode="json") for item in scope.omissions]
            if scope
            else [],
            "skills": [item.model_dump(mode="json") for item in record.inputs.skills],
            "findings": [item.model_dump(mode="json") for item in result.findings],
            "waived": [item.model_dump(mode="json") for item in result.waived],
            "unvalidated_candidates": len(result.candidate_findings),
            "withdrawn": [
                {
                    "skill": item.skill.id,
                    "by": item.by,
                    "reason": item.reason,
                    "anchor": item.finding.anchor.model_dump(mode="json"),
                    "problem": item.finding.problem,
                }
                for item in outcome.withdrawn
            ],
            "limitations": [
                item.model_dump(mode="json") for item in result.limitations
            ],
            "related_reads": [
                {
                    "path": item.path,
                    "action": item.action,
                    "question": item.request.question,
                    "relationship": item.request.relationship,
                    "reason": item.reason,
                }
                for item in investigation.reads
            ],
            "usage": result.usage.model_dump(mode="json"),
            "model_attempts": len(result.model_attempts),
            "events": [item.model_dump(mode="json") for item in record.progress.events],
        }

    def summary(self, outcome: ReviewOutcome) -> str:
        record = outcome.record
        result = record.progress.result
        scope = outcome.investigation.scope
        headline = HEADLINES.get(record.status, record.status)
        if record.status == "completed" and result.limitations:
            headline += " with open questions"
        lines = [
            f"# {headline}",
            "",
            f"{record.progress.events[-1].reason}.",
            "",
            *((outcome.withheld, "") if outcome.withheld else ()),
            f"- Repository: {record.inputs.repository}",
            f"- Compared: {record.inputs.merge_base_sha[:12]}"
            f"..{record.inputs.head_sha[:12]}",
            *(
                (f"- Policy evaluated as of: {record.inputs.review_time.isoformat()}",)
                if record.inputs.review_time
                else ()
            ),
            "- Skills: "
            + ", ".join(f"{item.id}@{item.version}" for item in record.inputs.skills),
        ]
        if scope:
            lines.append(
                "- Reviewed files: "
                + (
                    ", ".join(
                        item.new_path or item.old_path or "" for item in scope.files
                    )
                    or "none"
                )
            )
        lines += ["", f"## Findings ({len(result.findings)})", ""]
        if not result.findings:
            lines.append("No supported findings.")
        for finding in result.findings:
            lines += self._finding(finding)
        if result.waived:
            lines += [
                "",
                f"## Waived by approved exceptions ({len(result.waived)})",
                "",
            ]
            lines += [
                f"- {item.finding.anchor.path} line {item.finding.anchor.line}: "
                f"{item.reason}"
                for item in result.waived
            ]
        if result.candidate_findings:
            lines += [
                "",
                f"{len(result.candidate_findings)} proposal(s) were not validated "
                "and are not reported as findings.",
            ]
        if result.limitations:
            lines += ["", "## Limitations", ""]
            lines += [
                f"- {item.code}: {item.reason}"
                + (
                    ""
                    if item.affects_completeness
                    else " (does not affect completeness)"
                )
                for item in result.limitations
            ]
        reads = [item for item in outcome.investigation.reads if item.action == "read"]
        if reads:
            lines += ["", "## Related code read", ""]
            lines += [
                f"- {item.path}: {item.request.question} ({item.request.relationship})"
                for item in reads
            ]
        if outcome.withdrawn:
            lines += ["", "## Withdrawn proposals", ""]
            lines += [
                f"- {item.finding.anchor.path}:{item.finding.anchor.line} "
                f"({item.by}): {item.reason}"
                for item in outcome.withdrawn
            ]
        lines += ["", "## What this means", "", NOT_EXECUTED, COMPLETE_MEANS, ""]
        return "\n".join(lines)

    @staticmethod
    def _finding(finding: Finding) -> list[str]:
        anchor = finding.anchor
        rule = (
            f"{finding.rule_ref.id}@{finding.rule_ref.version}"
            if finding.rule_ref
            else "none"
        )
        side = "new" if anchor.side == "RIGHT" else "old"
        lines = [
            f"### {finding.severity.title()} {finding.category}: "
            f"{anchor.path} line {anchor.line} ({side} version)",
            "",
            f"- Problem: {finding.problem}",
            f"- Consequence: {finding.consequence}",
            f"- Example: {finding.trigger_scenario}",
            "- Evidence: " + "; ".join(_evidence(item) for item in finding.evidence),
            f"- Suggested fix: {finding.remediation}",
            f"- Rule: {rule}; skill: {finding.skill.id}@{finding.skill.version}",
        ]
        if finding.assumptions:
            lines.append("- Assumptions: " + "; ".join(finding.assumptions))
        return [*lines, ""]
