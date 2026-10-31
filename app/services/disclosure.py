from typing import Literal

from app.schemas.local_review import ReviewOutcome
from app.schemas.model_review import Disclosure
from app.schemas.review import Finding, Limitation

Audience = Literal["private", "public"]
WITHHELD = "Withheld: this text may draw on sources not approved for this audience."


class DisclosureService:
    def __init__(self, publishable: tuple[Disclosure, ...]) -> None:
        self._publishable = frozenset(publishable)

    def for_audience(
        self, outcome: ReviewOutcome, audience: Audience, code: Disclosure
    ) -> ReviewOutcome:
        if audience == "private":
            return outcome
        record = outcome.record
        result = record.progress.result
        sensitive = sorted(
            {
                source.disclosure
                for source in (*record.inputs.sources, *result.context_sources)
                if source.excerpt is not None
                and source.disclosure not in self._publishable
            }
            | ({code} - self._publishable)
        )
        if not sensitive:
            return outcome
        redacted = result.model_copy(
            update={
                "findings": tuple(self._finding(item) for item in result.findings),
                "withdrawn": tuple(
                    item.model_copy(
                        update={
                            "reason": WITHHELD,
                            "finding": item.finding.model_copy(
                                update={"problem": WITHHELD}
                            ),
                        }
                    )
                    for item in result.withdrawn
                ),
                "waived": tuple(
                    item.model_copy(
                        update={
                            "finding": self._finding(item.finding),
                            "reason": WITHHELD,
                        }
                    )
                    for item in result.waived
                ),
                "limitations": tuple(
                    self._limitation(item) for item in result.limitations
                ),
            }
        )
        investigation = outcome.investigation
        return outcome.model_copy(
            update={
                "investigation": investigation.model_copy(
                    update={
                        "questions": tuple(
                            item.model_copy(
                                update={
                                    "question": WITHHELD,
                                    "answer": WITHHELD if item.answer else None,
                                }
                            )
                            for item in investigation.questions
                        ),
                        "reads": tuple(
                            item.model_copy(
                                update={
                                    "request": item.request.model_copy(
                                        update={
                                            "question": WITHHELD,
                                            "expected_evidence": WITHHELD,
                                            "target": WITHHELD,
                                        }
                                    ),
                                    "path": WITHHELD
                                    if item.action == "denied"
                                    else item.path,
                                    "snippet": None,
                                }
                            )
                            for item in investigation.reads
                        ),
                        "limitations": tuple(
                            self._limitation(item) for item in investigation.limitations
                        ),
                    }
                ),
                "record": record.model_copy(
                    update={
                        "progress": record.progress.model_copy(
                            update={"result": redacted}
                        )
                    }
                ),
                "withheld": "The review used "
                + " and ".join(sensitive)
                + " material that is not approved for a public audience, so "
                "model-written text is withheld. The private review record "
                f"{record.id} keeps the full findings.",
            }
        )

    @staticmethod
    def _finding(finding: Finding) -> Finding:
        return finding.model_copy(
            update={
                "problem": WITHHELD,
                "consequence": WITHHELD,
                "trigger_scenario": WITHHELD,
                "remediation": WITHHELD,
                "assumptions": (),
            }
        )

    @staticmethod
    def _limitation(limitation: Limitation) -> Limitation:
        return limitation.model_copy(update={"reason": WITHHELD})
