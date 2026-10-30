from app.schemas.local_review import ReviewOutcome
from app.schemas.skill import CaseResult, ExampleAnchor, ExpectedFinding, SkillExample


class SkillEvaluationService:
    def compare(self, example: SkillExample, outcome: ReviewOutcome) -> CaseResult:
        record = outcome.record
        result = record.progress.result
        remaining = [
            ExpectedFinding(
                rule=finding.rule_ref,
                category=finding.category,
                anchor=ExampleAnchor(
                    path=finding.anchor.path,
                    side=finding.anchor.side,
                    line=finding.anchor.line,
                ),
            )
            for finding in result.findings
        ]
        matched, missed = [], []
        for expected in example.expected_findings:
            if expected in remaining:
                remaining.remove(expected)
                matched.append(expected)
            else:
                missed.append(expected)
        forbidden = [item for item in remaining if item in example.forbidden_findings]
        unexpected = [item for item in remaining if item not in forbidden]
        codes = {item.code for item in result.limitations}
        blocking = {
            item.code for item in result.limitations if item.affects_completeness
        }
        reads = sorted(
            {
                item.path
                for item in outcome.investigation.reads
                if item.action != "denied" and item.path in example.forbidden_reads
            }
        )
        case = CaseResult.model_construct(
            passed=False,
            case=example.case,
            kind=example.kind,
            status=record.status,
            matched=tuple(matched),
            missed=tuple(missed),
            unexpected=tuple(unexpected),
            forbidden=tuple(forbidden),
            missing_limitations=tuple(
                code for code in example.expected_limitations if code not in codes
            ),
            unexpected_limitations=tuple(
                sorted(blocking - set(example.expected_limitations))
            ),
            forbidden_reads=tuple(reads),
            withdrawn=tuple(
                f"{item.finding.anchor.path}:{item.finding.anchor.line} "
                f"({item.by}): {item.reason}"
                for item in outcome.withdrawn
            ),
            model_calls=result.usage.model_calls,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
        )
        return case.model_copy(update={"passed": case.meets_expectations()})
