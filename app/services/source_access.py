import asyncio
import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import NamedTuple

from app.core.errors import SourceAccessError, SourceError
from app.models.source_access import (
    SourceEvidence,
    SourceKind,
    SourcePassage,
    SourceTool,
    TicketLinks,
    ToolCall,
)
from app.provider.source.abstract import SourceProviderAbstract


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class FetchedSource(NamedTuple):
    passage: SourcePassage
    raw: str

    @property
    def tool(self) -> str:
        return self.passage.tool


class SourceAccessService:
    def __init__(
        self,
        provider: SourceProviderAbstract,
        approved: Mapping[SourceKind, frozenset[str]],
        timeout_seconds: float = 30,
    ) -> None:
        self._provider = provider
        self._approved = approved
        self._timeout_seconds = timeout_seconds
        self._tools: dict[str, SourceTool] | None = None

    @property
    def name(self) -> str:
        return self._provider.name

    def approved(self, kind: SourceKind) -> frozenset[str]:
        return self._approved.get(kind, frozenset())

    def ticket_references(self, text: str) -> TicketLinks:
        return self._provider.ticket_references(text)

    async def tools(self) -> list[SourceTool]:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await self._provider.list_tools()
        except TimeoutError:
            raise SourceError("Tool discovery timed out") from None

    async def discover(self) -> None:
        if self._tools is None:
            self._tools = {tool.name: tool for tool in await self.tools()}

    async def read(self, kind: SourceKind, reference: str) -> SourceEvidence:
        self._require_approval(kind, reference)
        await self.discover()
        output = await self.fetch(kind, reference, limit=1_000_000)
        return SourceEvidence(
            source=self._provider.name,
            kind=kind,
            tool=output.tool,
            reference_sha256=_sha256(reference),
            content_sha256=_sha256(output.raw),
            characters=len(output.raw),
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )

    async def fetch(
        self, kind: SourceKind, reference: str, limit: int
    ) -> FetchedSource:
        self._require_approval(kind, reference)
        if self._tools is None:
            raise SourceError("Discover the source's tools before reading")
        if kind == "ticket":
            call = self._provider.ticket_call(reference)
        else:
            call = self._provider.guideline_call(reference)
        self._verify(call, self._tools.get(call.tool))
        try:
            async with asyncio.timeout(self._timeout_seconds):
                output = await self._provider.call_tool(call)
        except TimeoutError:
            raise SourceError(f"The {kind} read timed out") from None
        if output.is_error:
            raise SourceError(
                f"{call.tool} returned an error; its content was not kept"
            )
        if not output.text.strip():
            raise SourceError(f"{call.tool} returned no readable content")
        passage = self._provider.passage(kind, reference, call, output, limit)
        return FetchedSource(passage, output.text)

    def _require_approval(self, kind: SourceKind, reference: str) -> None:
        if reference not in self.approved(kind):
            raise SourceAccessError(
                f"The {kind} reference is not approved; no request was sent"
            )

    def _verify(self, call: ToolCall, tool: SourceTool | None) -> None:
        if tool is None:
            raise SourceError(
                f"The connected server does not offer {call.tool}; "
                "run rush source-tools"
            )
        if tool.read_only is False or tool.destructive is True:
            raise SourceError(f"{call.tool} is not declared read-only; refusing it")
        missing = set(tool.required_inputs) - call.arguments.keys()
        unknown = call.arguments.keys() - set(tool.accepted_inputs)
        if missing or unknown:
            raise SourceError(
                f"{call.tool} inputs changed (missing {sorted(missing)}, "
                f"unknown {sorted(unknown)}); update the mapping"
            )

    async def close(self) -> None:
        await self._provider.close()
