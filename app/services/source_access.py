import asyncio
import hashlib
from collections.abc import Mapping
from datetime import UTC, datetime

from app.core.errors import SourceError
from app.models.source_access import (
    SourceEvidence,
    SourceKind,
    SourceTool,
    ToolCall,
)
from app.provider.source.abstract import SourceProviderAbstract


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


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

    async def tools(self) -> list[SourceTool]:
        try:
            async with asyncio.timeout(self._timeout_seconds):
                return await self._provider.list_tools()
        except TimeoutError:
            raise SourceError("Tool discovery timed out") from None

    async def read(self, kind: SourceKind, reference: str) -> SourceEvidence:
        if reference not in self._approved.get(kind, frozenset()):
            raise SourceError(
                f"The {kind} reference is not approved; no request was sent"
            )
        if kind == "ticket":
            call = self._provider.ticket_call(reference)
        else:
            call = self._provider.guideline_call(reference)
        try:
            async with asyncio.timeout(self._timeout_seconds):
                tools = {tool.name: tool for tool in await self._provider.list_tools()}
                self._verify(call, tools.get(call.tool))
                output = await self._provider.call_tool(call)
        except TimeoutError:
            raise SourceError(f"The {kind} read timed out") from None
        if output.is_error:
            raise SourceError(
                f"{call.tool} returned an error; its content was not kept"
            )
        if not output.text.strip():
            raise SourceError(f"{call.tool} returned no readable content")
        return SourceEvidence(
            source=self._provider.name,
            kind=kind,
            tool=call.tool,
            reference_sha256=_sha256(reference),
            content_sha256=_sha256(output.text),
            characters=len(output.text),
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds"),
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
