from collections.abc import Callable
from datetime import datetime

from app.core.errors import ReviewError
from app.models.review import NEXT_STATUS, TERMINAL_STATUSES, ReviewStatus
from app.schemas.review import (
    ReviewInputs,
    ReviewProgress,
    ReviewRecord,
    ReviewResult,
    RunEvent,
)
from app.services.ports import ReviewRepository


class ReviewRecordService:
    def __init__(
        self, repository: ReviewRepository, clock: Callable[[], datetime]
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def create(self, run_id: str, inputs: ReviewInputs) -> ReviewRecord:
        frozen = ReviewInputs.model_validate_json(inputs.model_dump_json())
        record = ReviewRecord(
            id=run_id,
            inputs=frozen,
            progress=ReviewProgress(
                events=(
                    RunEvent(
                        status="queued", reason="Review accepted", at=self._clock()
                    ),
                )
            ),
        )
        await self._repository.create(record)
        return record

    async def get(self, run_id: str) -> ReviewRecord:
        return await self._repository.get(run_id)

    async def advance(
        self,
        run_id: str,
        status: ReviewStatus,
        reason: str,
        result: ReviewResult | None = None,
    ) -> ReviewRecord:
        current = await self._repository.get(run_id)
        if current.status in TERMINAL_STATUSES:
            raise ReviewError("A terminal review cannot change; create a new run")
        if status != NEXT_STATUS[current.status] and status not in TERMINAL_STATUSES - {
            "completed"
        }:
            raise ReviewError("Review stage must follow the recorded lifecycle")
        event = RunEvent(status=status, reason=reason, at=self._clock())
        if event.at < current.progress.events[-1].at:
            raise ReviewError("Review progress time cannot move backwards")
        output = result if result is not None else current.progress.result
        if status == "partial" and not output.limitations:
            raise ReviewError("A partial review must record its limitations")
        if status == "completed" and output.limitations:
            raise ReviewError(
                "A review with unresolved limitations must remain partial"
            )
        self._validate_findings(current, output)
        updated = ReviewRecord(
            id=current.id,
            inputs=current.inputs,
            progress=ReviewProgress(
                events=(*current.progress.events, event),
                result=output,
            ),
        )
        await self._repository.save(updated, current.revision)
        return updated

    @staticmethod
    def _validate_findings(record: ReviewRecord, result: ReviewResult) -> None:
        sources = {source.id: source for source in record.inputs.sources}
        ids = [finding.id for finding in result.findings]
        if len(ids) != len(set(ids)):
            raise ReviewError("Finding IDs must be unique within a run")
        for finding in result.findings:
            if finding.run_id != record.id or finding.skill not in record.inputs.skills:
                raise ReviewError("Finding must reference this run and a frozen skill")
            if finding.rule_ref and not any(
                rule.id == finding.rule_ref.id
                and rule.version == finding.rule_ref.version
                for rule in record.inputs.rules
            ):
                raise ReviewError("Finding rule must match a frozen rule version")
            for evidence in (*finding.evidence, *finding.causal_path):
                source = sources.get(evidence.source_id)
                if source is None or (source.revision, source.content_sha256) != (
                    evidence.revision,
                    evidence.content_sha256,
                ):
                    raise ReviewError("Finding evidence must reference a frozen source")
