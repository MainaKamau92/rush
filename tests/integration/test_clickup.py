import asyncio
from typing import Any, cast

import httpx2
import pytest
from mcp import Client
from mcp.client.auth import OAuthFlowError
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import ToolAnnotations

from app.core.errors import SourceError
from app.internal.adapters.clickup import ClickUpSourceAdapter
from app.internal.adapters.mcp_auth import AuthorizationRequiredError
from app.models.source_access import ToolCall


def clickup_double(calls: list[dict[str, Any]]) -> MCPServer:
    server = MCPServer("clickup-double")

    @server.tool(annotations=ToolAnnotations(read_only_hint=True))
    def clickup_get_task(task_id: str, workspace_id: str | None = None) -> str:
        calls.append({"task_id": task_id, "workspace_id": workspace_id})
        if task_id == "limited":
            raise ToolError("RATE_LIMIT_EXCEEDED retryAfter=60")
        if task_id == "missing":
            raise ToolError("Task not found: private detail")
        return "Fictional ticket text"

    @server.tool()
    def clickup_get_document_pages(
        document_id: str, page_ids: list[str], workspace_id: str | None = None
    ) -> str:
        calls.append(
            {
                "document_id": document_id,
                "page_ids": page_ids,
                "workspace_id": workspace_id,
            }
        )
        return "Fictional guideline text"

    @server.tool(annotations=ToolAnnotations(destructive_hint=True))
    def clickup_delete_task(task_id: str) -> str:
        raise AssertionError("A destructive tool must never be called")

    return server


def adapter(calls: list[dict[str, Any]]) -> ClickUpSourceAdapter:
    return ClickUpSourceAdapter(Client(clickup_double(calls)), "9001")


async def test_discovery_reports_actual_names_inputs_and_annotations() -> None:
    source = adapter([])
    tools = {tool.name: tool for tool in await source.list_tools()}
    await source.close()
    task = tools["clickup_get_task"]
    assert task.required_inputs == ("task_id",)
    assert set(task.accepted_inputs) == {"task_id", "workspace_id"}
    assert task.read_only is True and task.destructive is not True
    assert tools["clickup_get_document_pages"].required_inputs == (
        "document_id",
        "page_ids",
    )
    assert tools["clickup_delete_task"].destructive is True


async def test_ticket_and_guideline_calls_send_mapped_arguments() -> None:
    calls: list[dict[str, Any]] = []
    source = adapter(calls)
    ticket = await source.call_tool(source.ticket_call("86abc1"))
    guideline = await source.call_tool(source.guideline_call("doc-1/page-2"))
    await source.close()
    assert ticket.text == "Fictional ticket text" and not ticket.is_error
    assert guideline.text == "Fictional guideline text"
    assert calls == [
        {"task_id": "86abc1", "workspace_id": "9001"},
        {"document_id": "doc-1", "page_ids": ["page-2"], "workspace_id": "9001"},
    ]


@pytest.mark.parametrize(
    ("kind", "reference"),
    [
        ("ticket", "../other"),
        ("ticket", "https://app.clickup.com/t/1"),
        ("guideline", "doc-only"),
        ("guideline", "doc/page/extra"),
    ],
)
def test_malformed_references_are_rejected_before_any_request(
    kind: str, reference: str
) -> None:
    source = adapter([])
    build = source.ticket_call if kind == "ticket" else source.guideline_call
    with pytest.raises(SourceError, match="valid ClickUp"):
        build(reference)


def test_workspace_identity_is_validated() -> None:
    with pytest.raises(SourceError, match="workspace ID"):
        ClickUpSourceAdapter(Client(clickup_double([])), "")


async def test_tool_errors_are_flagged_and_rate_limits_are_explicit() -> None:
    source = adapter([])
    failed = await source.call_tool(source.ticket_call("missing"))
    with pytest.raises(SourceError, match="request limit"):
        await source.call_tool(source.ticket_call("limited"))
    await source.close()
    assert failed.is_error


class FailingClient:
    def __init__(self, error: BaseException) -> None:
        self.error = error

    async def __aenter__(self) -> "FailingClient":
        raise self.error

    async def __aexit__(self, *exc: object) -> None:
        return None


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            ExceptionGroup("wrapped", [AuthorizationRequiredError()]),
            "authorization is required",
        ),
        (OAuthFlowError("private token endpoint body"), "sign-in failed"),
        (httpx2.ReadTimeout("private-timeout"), "timed out"),
        (httpx2.ConnectError("private-connection"), "connection failed"),
        (MCPError(-32600, "private protocol detail"), "protocol error -32600"),
        (SourceError("Stored source credentials are unreadable"), "unreadable"),
    ],
)
async def test_connection_failures_become_safe_source_errors(
    error: Exception, message: str
) -> None:
    http_client = httpx2.AsyncClient()
    source = ClickUpSourceAdapter(
        cast(Client, FailingClient(error)), "9001", http_client
    )
    with pytest.raises(SourceError, match=message) as raised:
        await source.list_tools()
    await source.close()
    assert "private" not in str(raised.value)
    assert http_client.is_closed


@pytest.mark.parametrize("error", [ValueError("bug"), asyncio.CancelledError()])
async def test_unexpected_errors_and_cancellation_are_not_hidden(
    error: BaseException,
) -> None:
    source = ClickUpSourceAdapter(cast(Client, FailingClient(error)), "9001")
    with pytest.raises(type(error)):
        await source.call_tool(ToolCall("clickup_get_task", {"task_id": "1"}))
