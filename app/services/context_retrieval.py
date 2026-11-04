import asyncio
import hashlib
from collections.abc import Callable
from datetime import datetime
from functools import partial

from app.core.errors import SourceAccessError, SourceError, SourceRateLimitError
from app.models.source_access import SourceKind, SourcePassage
from app.schemas.model_review import Disclosure
from app.schemas.review import Limitation, SourceSnapshot
from app.services.investigation import InvestigationService
from app.services.review_budget import BudgetExceededError
from app.services.source_access import FetchedSource, SourceAccessService

MAX_PASSAGE_CHARACTERS = 32_000
MAX_LINKED_TICKETS = 3
# ClickUp's per-minute limit clears quickly, so a rate-limited read is retried.
RATE_LIMIT_RETRIES = 2
RATE_LIMIT_SECONDS = 20.0


class ContextRetrievalService:
    def __init__(
        self,
        sources: SourceAccessService,
        disclosure: Disclosure,
        clock: Callable[[], datetime],
    ) -> None:
        self._sources, self._disclosure, self._clock = sources, disclosure, clock

    @property
    def disclosure(self) -> Disclosure:
        return self._disclosure

    async def retrieve(
        self,
        investigation: InvestigationService,
        *,
        tickets: tuple[str, ...] = (),
        pull_request_text: str | None = None,
        guidelines: bool = False,
        ticket_supplied: bool = False,
    ) -> tuple[SourceSnapshot, ...]:
        links = self._sources.ticket_references(pull_request_text or "")
        references = tuple(dict.fromkeys((*tickets, *links.references)))
        if links.outside:
            investigation.note(
                Limitation(
                    code="access_denied",
                    reason=f"{links.outside} linked task(s) are outside the approved "
                    "workspace; nothing was requested",
                    affects_completeness=False,
                )
            )
        elif not references and not ticket_supplied:
            investigation.note(
                Limitation(
                    code="missing_ticket",
                    reason="No ticket link was found in the pull request or request",
                    affects_completeness=False,
                )
            )
        if len(references) > MAX_LINKED_TICKETS:
            investigation.note(
                Limitation(
                    code="scope_excluded",
                    reason=f"Only the first {MAX_LINKED_TICKETS} of "
                    f"{len(references)} linked tickets were read",
                    affects_completeness=False,
                )
            )
        # Team guidelines are read before PR-chosen tickets so links cannot
        # exhaust the MCP allowance meant for policy.
        wanted: list[tuple[SourceKind, str]] = []
        if guidelines:
            configured = sorted(self._sources.guidelines)
            if not configured:
                investigation.note(
                    Limitation(
                        code="missing_context",
                        reason="No approved guideline is configured",
                    )
                )
            wanted += [("guideline", reference) for reference in configured]
        wanted += [("ticket", item) for item in references[:MAX_LINKED_TICKETS]]
        snapshots = await self._read(investigation, wanted) if wanted else ()
        read = sum(item.kind == "ticket" for item in snapshots)
        if read > 1:
            investigation.note(
                Limitation(
                    code="conflicting_sources",
                    reason=f"{read} tickets were read; their intents may differ",
                    affects_completeness=False,
                )
            )
        return snapshots

    async def _fetch(
        self, investigation: InvestigationService, kind: SourceKind, reference: str
    ) -> FetchedSource:
        """Fetch one source, waiting and retrying when ClickUp rate-limits."""
        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                return await investigation.call_mcp(
                    partial(
                        self._sources.fetch, kind, reference, MAX_PASSAGE_CHARACTERS
                    ),
                    required=kind == "guideline",
                )
            except SourceRateLimitError:
                if attempt == RATE_LIMIT_RETRIES:
                    raise
                await asyncio.sleep(RATE_LIMIT_SECONDS * (attempt + 1))
        raise AssertionError("unreachable")  # pragma: no cover

    async def _read(
        self,
        investigation: InvestigationService,
        wanted: list[tuple[SourceKind, str]],
    ) -> tuple[SourceSnapshot, ...]:
        snapshots: list[SourceSnapshot] = []
        try:
            await investigation.call_mcp(self._sources.discover)
            for kind, reference in wanted:
                try:
                    fetched = await self._fetch(investigation, kind, reference)
                except SourceRateLimitError as error:
                    investigation.note(
                        Limitation(
                            code="rate_limited",
                            reason=f"{error}; remaining sources were not read",
                        )
                    )
                    break
                except SourceAccessError as error:
                    investigation.note(
                        Limitation(code="access_denied", reason=str(error))
                    )
                    continue
                except SourceError as error:
                    investigation.note(
                        Limitation(code="missing_context", reason=str(error))
                    )
                    continue
                passage = fetched.passage
                if passage.truncated:
                    investigation.note(
                        Limitation(
                            code="content_truncated",
                            reason=f"A {kind} was longer than "
                            f"{MAX_PASSAGE_CHARACTERS} characters and was cut short",
                        )
                    )
                snapshots.append(self._snapshot(len(snapshots) + 1, passage))
        except BudgetExceededError:
            pass
        except SourceAccessError as error:
            investigation.note(Limitation(code="access_denied", reason=str(error)))
        except SourceError as error:
            investigation.note(Limitation(code="missing_context", reason=str(error)))
        return tuple(snapshots)

    def _snapshot(self, number: int, passage: SourcePassage) -> SourceSnapshot:
        digest = hashlib.sha256(passage.reference.encode()).hexdigest()[:12]
        return SourceSnapshot(
            id=f"{passage.kind}-live-{number}",
            kind=passage.kind,
            reference=passage.url or f"{self._sources.name}:{passage.kind}:{digest}",
            workspace=self._sources.name,
            revision=passage.version,
            content_sha256=hashlib.sha256(passage.text.encode()).hexdigest(),
            retrieved_at=self._clock(),
            disclosure=self._disclosure,
            excerpt=passage.text,
        )

    async def close(self) -> None:
        await self._sources.close()
