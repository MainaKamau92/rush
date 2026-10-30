import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from app.core.errors import ReviewError, SkillError, SourceAccessError
from app.schemas.local_review import LocalReviewRequest, ReviewOutcome
from app.schemas.model_review import Capability, ReviewPermissions, ReviewTask
from app.schemas.review import (
    Limitation,
    ModelConfiguration,
    ReviewInputs,
    ReviewResult,
    ReviewSettings,
    SourceSnapshot,
    VersionPin,
)
from app.schemas.skill import InstalledSkill
from app.services.context_retrieval import ContextRetrievalService
from app.services.finding_validation import FindingValidationService
from app.services.investigation import InvestigationService
from app.services.model_review import ModelReviewService
from app.services.review_records import ReviewRecordService
from app.services.review_skills import SkillCatalog

RUNTIME_CAPABILITIES: tuple[Capability, ...] = ("repo.read_snippet", "repo.find_symbol")


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class LocalReviewService:
    def __init__(
        self,
        catalog: SkillCatalog,
        model_review: Callable[[InvestigationService], ModelReviewService],
        validation: FindingValidationService,
        records: ReviewRecordService,
        clock: Callable[[], datetime],
        retrieval: Callable[[], ContextRetrievalService] | None = None,
    ) -> None:
        self._catalog, self._model_review = catalog, model_review
        self._validation, self._records, self._clock = validation, records, clock
        self._retrieval = retrieval

    async def review(
        self,
        investigation: InvestigationService,
        request: LocalReviewRequest,
        skills: tuple[InstalledSkill, ...] | None = None,
    ) -> ReviewOutcome:
        candidates = self._catalog.active if skills is None else skills
        if not candidates:
            raise SkillError("No active review skill; evaluate and approve one first")
        started = await investigation.start(
            request.head, target=request.target, base=request.base
        )
        scope = started.scope
        if scope is None:
            raise ReviewError("Change discovery did not produce a reviewable scope")
        paths = {item.new_path or item.old_path or "" for item in scope.files}
        selected = self._catalog.select(paths, candidates)
        profiles = {skill.model for skill in selected or candidates[:1]}
        if len(profiles) != 1:
            raise SkillError("Selected skills use different model profiles")
        profile = profiles.pop()
        rules, policy = self._rules(request)
        retrieved: tuple[SourceSnapshot, ...] = ()
        if selected and request.live_context:
            retrieved = await self._retrieve(investigation, request)
        sources = (*self._context(request), *retrieved, *policy)
        inputs = ReviewInputs(
            repository=request.repository,
            target_sha=scope.target_sha or scope.base_sha,
            merge_base_sha=scope.base_sha,
            head_sha=scope.head_sha,
            policy_sha=scope.base_sha,
            memory_revision="none",
            settings=ReviewSettings(
                models=tuple(
                    ModelConfiguration(
                        task=task,
                        model_id=profile.model_id,
                        adapter_version=profile.adapter_version,
                        max_output_tokens=profile.max_output_tokens,
                    )
                    for task in ("review", "critique")
                ),
                limits=investigation.limits,
            ),
            rules=rules,
            skills=tuple(skill.pin for skill in selected or candidates),
            sources=sources,
            scope_manifest_sha256=scope.manifest_sha256(),
        )
        if not selected:
            return await self._unreviewed(investigation, request.run_id, inputs)
        service = self._model_review(investigation)
        try:
            report = await service.run(
                request.run_id,
                inputs,
                *(self._task(skill, request) for skill in selected),
            )
        finally:
            await service.close()
        return await self._validation.validate(
            report, {skill.pin.id: skill for skill in selected}
        )

    async def _unreviewed(
        self, investigation: InvestigationService, run_id: str, inputs: ReviewInputs
    ) -> ReviewOutcome:
        report = investigation.finish()
        await self._records.create(run_id, inputs)
        if report.scope and report.scope.omissions:
            record = await self._records.advance(
                run_id,
                "partial",
                "No admitted file matches an approved skill; some files were omitted",
                ReviewResult(limitations=report.limitations),
            )
        else:
            record = await self._records.advance(
                run_id, "skipped", "No approved skill matches the changed files"
            )
        return ReviewOutcome(record=record, investigation=report)

    async def _retrieve(
        self, investigation: InvestigationService, request: LocalReviewRequest
    ) -> tuple[SourceSnapshot, ...]:
        if self._retrieval is None:
            raise ReviewError("Live ticket and guideline retrieval is not configured")
        try:
            retrieval = self._retrieval()
        except SourceAccessError as error:
            investigation.note(Limitation(code="access_denied", reason=str(error)))
            return ()
        try:
            if retrieval.disclosure not in self._catalog.approved.allowed_disclosures:
                investigation.note(
                    Limitation(
                        code="access_denied",
                        reason=f"Live sources are classified {retrieval.disclosure}; "
                        "the team has not approved sending them to the model, so "
                        "none were read",
                    )
                )
                return ()
            return await retrieval.retrieve(
                investigation,
                tickets=request.ticket_references,
                pull_request_text=request.pull_request_text,
                guidelines=request.live_guidelines,
                ticket_supplied=any(item.kind == "ticket" for item in request.context),
            )
        finally:
            await retrieval.close()

    async def finish(self, outcome: ReviewOutcome) -> ReviewOutcome:
        return await self._validation.finish(outcome)

    def _task(self, skill: InstalledSkill, request: LocalReviewRequest) -> ReviewTask:
        approved = self._catalog.approved
        instructions = skill.instructions
        if skill.manifest.rule_ids:
            instructions += "\nApply only these approved rule IDs: " + ", ".join(
                skill.manifest.rule_ids
            )
        return ReviewTask(
            skill=skill.pin,
            instructions=instructions,
            code_disclosure=request.disclosure,
            permissions=ReviewPermissions(
                runtime=RUNTIME_CAPABILITIES,
                repository=approved.permissions,
                skill=skill.manifest.permissions.capabilities,
                allowed_disclosures=approved.allowed_disclosures,
            ),
        )

    def _context(self, request: LocalReviewRequest) -> tuple[SourceSnapshot, ...]:
        counts: dict[str, int] = {}
        snapshots = []
        for item in request.context:
            counts[item.kind] = counts.get(item.kind, 0) + 1
            snapshots.append(
                SourceSnapshot(
                    id=f"{item.kind}-{counts[item.kind]}",
                    kind=item.kind,
                    reference=item.reference,
                    content_sha256=_digest(item.text),
                    retrieved_at=self._clock(),
                    disclosure=request.disclosure,
                    excerpt=item.text,
                )
            )
        return tuple(snapshots)

    def _rules(
        self, request: LocalReviewRequest
    ) -> tuple[tuple[VersionPin, ...], tuple[SourceSnapshot, ...]]:
        if request.rules is None:
            return (), ()
        try:
            rows = json.loads(request.rules)
            pins = tuple(
                VersionPin(
                    id=row["id"],
                    version=row["version"],
                    digest=_digest(json.dumps(row, sort_keys=True)),
                )
                for row in rows
            )
        except (ValueError, TypeError, KeyError):
            raise ReviewError(
                "Rules must be a JSON list of rules, each with an id and version"
            ) from None
        if len({pin.id for pin in pins}) != len(pins):
            raise ReviewError("Each rule ID may appear once")
        policy = SourceSnapshot(
            id="policy",
            kind="policy",
            reference="approved rules",
            content_sha256=_digest(request.rules),
            retrieved_at=self._clock(),
            disclosure=request.disclosure,
            excerpt=request.rules,
        )
        return pins, (policy,)
