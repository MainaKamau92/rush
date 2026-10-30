import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from app.core.errors import ReviewError
from app.schemas.model_review import Capability, Disclosure
from app.schemas.review import EvidenceRef, Limitation, ReviewInputs, SourceSnapshot
from app.services.investigation import InvestigationService


class ModelContext:
    def __init__(
        self,
        inputs: ReviewInputs,
        investigation: InvestigationService,
        disclosure: Disclosure,
        clock: Callable[[], datetime],
    ) -> None:
        self._inputs, self._investigation = inputs, investigation
        self._disclosure, self._clock = disclosure, clock
        self._sources = {
            source.id: source for source in inputs.sources if source.excerpt is not None
        }
        self._captured: dict[str, SourceSnapshot] = {}
        self._hunks: set[str] = set()
        self._sent: set[str] = set()

    def prepare(self) -> None:
        for source in self._sources.values():
            self._investigation.supply_context(source.excerpt or "")
        scope = self._investigation.report().scope
        if scope is None:
            raise ReviewError("No admitted change is available")
        for file in scope.files:
            for hunk in file.hunks:
                self._hunks.add(f"diff:{hunk.id}")
                self._add(
                    f"diff:{hunk.id}",
                    f"{file.new_path or file.old_path}#hunk:{hunk.id}",
                    f"{scope.base_sha}..{scope.head_sha}",
                    "\n".join(line.text for line in hunk.lines),
                )

    def _add(self, identity: str, reference: str, revision: str, text: str) -> None:
        if identity in self._captured:
            return
        if any(source.id == identity for source in self._inputs.sources):
            raise ReviewError("Context identity conflicts with a frozen source")
        source = SourceSnapshot(
            id=identity,
            kind="code",
            reference=reference,
            revision=revision,
            content_sha256=hashlib.sha256(text.encode()).hexdigest(),
            retrieved_at=self._clock(),
            disclosure=self._disclosure,
            excerpt=text,
        )
        self._sources[identity] = self._captured[identity] = source

    @property
    def captured(self) -> tuple[SourceSnapshot, ...]:
        return tuple(self._captured.values())

    def payload(
        self,
        *,
        repair: bool,
        permissions: tuple[Capability, ...],
        limitations: tuple[Limitation, ...],
    ) -> str:
        report = self._investigation.report()
        for read in report.reads:
            if read.snippet:
                snippet = read.snippet
                self._add(
                    snippet.id,
                    f"{snippet.path}#L{snippet.start_line}-L{snippet.end_line}",
                    snippet.commit,
                    snippet.text,
                )
        for source in self._sources.values():
            if source.id in self._sent:
                self._investigation.supply_context(source.excerpt or "")
        self._sent.update(self._sources)
        return json.dumps(
            {
                "change": report.scope.model_dump(mode="json")
                if report.scope
                else None,
                "evidence_catalog": [
                    {
                        **source.model_dump(
                            mode="json",
                            include={"kind", "reference"}
                            if source.id in self._hunks
                            else {"kind", "reference", "excerpt"},
                        ),
                        "source_id": source.id,
                        "start": 1,
                        "end": max(1, len((source.excerpt or "").splitlines())),
                        "numbered": "\n".join(
                            f"{number}| {line}"
                            for number, line in enumerate(
                                (source.excerpt or "").splitlines(), start=1
                            )
                        ),
                    }
                    for source in self._sources.values()
                ],
                "questions": [
                    item.model_dump(mode="json") for item in report.questions
                ],
                "reads": [
                    item.model_dump(mode="json", exclude={"snippet"})
                    | {
                        "read_id": item.snippet.id if item.snippet else None,
                        "evidence_source_id": item.snippet.id if item.snippet else None,
                    }
                    for item in report.reads
                ],
                "repair": repair,
                "effective_permissions": permissions,
                "host_limitations": [
                    item.model_dump(mode="json") for item in limitations
                ],
                "frozen_rules": [
                    item.model_dump(mode="json") for item in self._inputs.rules
                ],
            }
        )

    def quote(self, source_id: str, start: int, end: int) -> str:
        self.resolve_evidence(source_id, start, end)
        excerpt = self._sources[source_id].excerpt or ""
        return "\n".join(excerpt.splitlines()[start - 1 : end])

    def resolve_evidence(self, source_id: str, start: int, end: int) -> EvidenceRef:
        source = self._sources.get(source_id)
        if source is None:
            raise ReviewError("Model evidence names a source that was not supplied")
        if end < start or end > max(1, len((source.excerpt or "").splitlines())):
            raise ReviewError("Model evidence is outside the supplied passage")
        return EvidenceRef(
            source_id=source.id,
            revision=source.revision,
            content_sha256=source.content_sha256,
            start=start,
            end=end,
        )
