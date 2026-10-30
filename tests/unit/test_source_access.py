import asyncio
import hashlib

import pytest

from app.core.errors import SourceError
from app.models.source_access import (
    SourceKind,
    SourcePassage,
    SourceTool,
    TicketLinks,
    ToolCall,
    ToolOutput,
)
from app.provider.source.abstract import SourceProviderAbstract
from app.services.source_access import SourceAccessService

TASK_TOOL = SourceTool(
    "get_task", ("task_id",), ("task_id", "workspace_id"), True, False
)
PAGE_TOOL = SourceTool("get_page", ("page_id",), ("page_id",), None, None)


class ControlledSource(SourceProviderAbstract):
    name = "controlled"

    def __init__(self) -> None:
        self.tools = [TASK_TOOL, PAGE_TOOL]
        self.output = ToolOutput("Private ticket body", False)
        self.calls: list[ToolCall] = []
        self.listings = 0
        self.closed = False

    def ticket_call(self, reference: str) -> ToolCall:
        return ToolCall("get_task", {"task_id": reference, "workspace_id": "w1"})

    def guideline_call(self, reference: str) -> ToolCall:
        return ToolCall("get_page", {"page_id": reference})

    def ticket_references(self, text: str) -> TicketLinks:
        words = text.split()
        return TicketLinks(
            tuple(word[5:] for word in words if word.startswith("task:")),
            sum(word.startswith("elsewhere:") for word in words),
        )

    def passage(
        self,
        kind: SourceKind,
        reference: str,
        call: ToolCall,
        output: ToolOutput,
        limit: int,
    ) -> SourcePassage:
        return SourcePassage(
            kind,
            reference,
            call.tool,
            output.text[:limit],
            None,
            None,
            len(output.text) > limit,
        )

    async def list_tools(self) -> list[SourceTool]:
        self.listings += 1
        return self.tools

    async def call_tool(self, call: ToolCall) -> ToolOutput:
        self.calls.append(call)
        return self.output

    async def close(self) -> None:
        self.closed = True


def service_for(
    source: SourceProviderAbstract, timeout: float = 30
) -> SourceAccessService:
    return SourceAccessService(
        source, {"ticket": frozenset({"t1"}), "guideline": frozenset({"g1"})}, timeout
    )


async def test_approved_read_keeps_only_safe_evidence() -> None:
    source = ControlledSource()
    service = service_for(source)
    evidence = await service.read("ticket", "t1")
    await service.close()
    assert source.calls == [
        ToolCall("get_task", {"task_id": "t1", "workspace_id": "w1"})
    ]
    assert evidence.source == "controlled" and evidence.tool == "get_task"
    assert evidence.reference_sha256 == hashlib.sha256(b"t1").hexdigest()
    assert evidence.content_sha256 == hashlib.sha256(b"Private ticket body").hexdigest()
    assert evidence.characters == len("Private ticket body")
    assert "Private" not in repr(evidence) and "'t1'" not in repr(evidence)
    assert source.closed


async def test_guideline_reads_use_the_guideline_mapping() -> None:
    source = ControlledSource()
    evidence = await service_for(source).read("guideline", "g1")
    assert evidence.kind == "guideline"
    assert source.calls == [ToolCall("get_page", {"page_id": "g1"})]


@pytest.mark.parametrize(
    ("kind", "reference"),
    [("ticket", "unlisted"), ("guideline", "t1"), ("ticket", " t1")],
)
async def test_unapproved_references_never_reach_the_source(
    kind: str, reference: str
) -> None:
    source = ControlledSource()
    with pytest.raises(SourceError, match="not approved"):
        await service_for(source).read(kind, reference)  # type: ignore[arg-type]
    assert source.listings == 0 and source.calls == []


@pytest.mark.parametrize(
    ("tools", "message"),
    [
        ([PAGE_TOOL], "does not offer get_task"),
        (
            [
                SourceTool(
                    "get_task", ("task_id",), ("task_id", "workspace_id"), False, None
                )
            ],
            "not declared read-only",
        ),
        (
            [
                SourceTool(
                    "get_task", ("task_id",), ("task_id", "workspace_id"), None, True
                )
            ],
            "not declared read-only",
        ),
        (
            [
                SourceTool(
                    "get_task",
                    ("task_id", "list_id"),
                    ("task_id", "workspace_id", "list_id"),
                    True,
                    False,
                )
            ],
            r"missing \['list_id'\]",
        ),
        (
            [SourceTool("get_task", ("task_id",), ("task_id",), True, False)],
            r"unknown \['workspace_id'\]",
        ),
    ],
)
async def test_discovered_tools_must_match_the_mapping_before_calling(
    tools: list[SourceTool], message: str
) -> None:
    source = ControlledSource()
    source.tools = tools
    with pytest.raises(SourceError, match=message):
        await service_for(source).read("ticket", "t1")
    assert source.calls == []


@pytest.mark.parametrize(
    ("output", "message"),
    [
        (ToolOutput("Private failure details", True), "returned an error"),
        (ToolOutput("  \n", False), "no readable content"),
    ],
)
async def test_failed_or_empty_reads_never_become_evidence(
    output: ToolOutput, message: str
) -> None:
    source = ControlledSource()
    source.output = output
    with pytest.raises(SourceError, match=message) as error:
        await service_for(source).read("ticket", "t1")
    assert "Private" not in str(error.value)
    assert len(source.calls) == 1


async def test_deadline_cancels_a_stalled_read() -> None:
    cancelled = asyncio.Event()

    class StalledSource(ControlledSource):
        async def call_tool(self, call: ToolCall) -> ToolOutput:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            raise AssertionError("Stalled read unexpectedly completed")

    with pytest.raises(SourceError, match="timed out"):
        await service_for(StalledSource(), timeout=0.01).read("ticket", "t1")
    assert cancelled.is_set()


async def test_deadline_bounds_tool_discovery() -> None:
    class StalledSource(ControlledSource):
        async def list_tools(self) -> list[SourceTool]:
            await asyncio.Event().wait()
            return []

    with pytest.raises(SourceError, match="discovery timed out"):
        await service_for(StalledSource(), timeout=0.01).tools()


async def test_cancellation_propagates_without_another_call() -> None:
    class CancelledSource(ControlledSource):
        async def call_tool(self, call: ToolCall) -> ToolOutput:
            self.calls.append(call)
            raise asyncio.CancelledError

    source = CancelledSource()
    with pytest.raises(asyncio.CancelledError):
        await service_for(source).read("ticket", "t1")
    assert len(source.calls) == 1
