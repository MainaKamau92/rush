import asyncio
import json
from typing import Any, cast

import httpx2
import pytest
from mcp import Client
from mcp.client.auth import OAuthFlowError
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import ToolAnnotations

from app.core.errors import SourceAccessError, SourceError, SourceRateLimitError
from app.internal.adapters.clickup import ClickUpSourceAdapter
from app.internal.adapters.mcp_auth import AuthorizationRequiredError
from app.models.source_access import SourceKind, TicketLinks, ToolCall, ToolOutput


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


def status_error(status: int) -> httpx2.HTTPStatusError:
    request = httpx2.Request("POST", "https://mcp.clickup.com/mcp")
    return httpx2.HTTPStatusError(
        "private status body",
        request=request,
        response=httpx2.Response(status, request=request),
    )


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
        (status_error(429), "request limit reached"),
        (status_error(401), "refused access \\(HTTP 401\\)"),
        (status_error(403), "refused access \\(HTTP 403\\)"),
        (status_error(500), "connection failed"),
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
    if "limit" in message:
        assert isinstance(raised.value, SourceRateLimitError)
    if "refused" in message or "authorization" in message:
        assert isinstance(raised.value, SourceAccessError)
    assert http_client.is_closed


@pytest.mark.parametrize("error", [ValueError("bug"), asyncio.CancelledError()])
async def test_unexpected_errors_and_cancellation_are_not_hidden(
    error: BaseException,
) -> None:
    source = ClickUpSourceAdapter(cast(Client, FailingClient(error)), "9001")
    with pytest.raises(type(error)):
        await source.call_tool(ToolCall("clickup_get_task", {"task_id": "1"}))


@pytest.mark.parametrize(
    ("text", "references", "outside"),
    [
        ("Fixes https://app.clickup.com/t/86abc12", ("86abc12",), 0),
        ("(https://app.clickup.com/t/9001/DEMO-1).", ("DEMO-1",), 0),
        ("https://app.clickup.com/t/a1 and https://app.clickup.com/t/a1", ("a1",), 0),
        ("https://app.clickup.com/t/1234/other-workspace", (), 1),
        ("https://app.clickup.com.evil.invalid/t/a1", (), 0),
        ("http://app.clickup.com/t/a1", (), 0),
        ("https://evil.invalid/?next=https://app.clickup.com/t/a1", (), 0),
        ("https://app.clickup.com/t/a1/../../admin", (), 0),
        ("See CU-123 or task a1", (), 0),
    ],
)
def test_only_https_task_links_in_the_approved_workspace_are_found(
    text: str, references: tuple[str, ...], outside: int
) -> None:
    assert adapter([]).ticket_references(text) == TicketLinks(references, outside)


def test_passages_keep_review_text_and_drop_people_and_unknown_versions() -> None:
    source = adapter([])
    call = source.ticket_call("a1")
    task = json.dumps(
        {
            "name": "Trim customer names",
            "text_content": "Return the display name without whitespace.",
            "assignees": [{"email": "person@example.invalid"}],
            "url": "https://app.clickup.com/t/a1",
            "date_updated": "1760000000000",
        }
    )
    passage = source.passage("ticket", "a1", call, ToolOutput(task, False), 1000)
    assert passage.text == (
        "# Trim customer names\n\nReturn the display name without whitespace."
    )
    assert (passage.url, passage.version, passage.truncated) == (
        "https://app.clickup.com/t/a1",
        "date_updated:1760000000000",
        False,
    )
    forged = json.dumps({"name": "x", "url": "https://evil.invalid/t/a1"})
    assert (
        source.passage("ticket", "a1", call, ToolOutput(forged, False), 9).url is None
    )

    pages = json.dumps(
        [
            {"name": "Tenant lookups", "content": "Pass the tenant.", "version": 3},
            {"name": "Names", "content": "Never return email.", "version": 3},
        ]
    )
    guideline = source.passage(
        "guideline", "d/p", source.guideline_call("d/p"), ToolOutput(pages, False), 1000
    )
    assert guideline.text == (
        "# Tenant lookups\n\nPass the tenant.\n\n# Names\n\nNever return email."
    )
    assert guideline.version == "3"
    mixed = json.dumps({"pages": [{"content": "A", "version": 1}, {"content": "B"}]})
    assert (
        source.passage("guideline", "d/p", call, ToolOutput(mixed, False), 1000).version
        is None
    )
    plain = source.passage("ticket", "a1", call, ToolOutput("Plain text", False), 5)
    assert (plain.text, plain.truncated) == ("Plain", True)


@pytest.mark.parametrize(
    ("kind", "body"),
    [
        ("ticket", {"assignees": [{"email": "person@example.invalid"}]}),
        ("ticket", ["unexpected"]),
        ("guideline", {"members": ["person@example.invalid"]}),
        ("guideline", [{"name": " ", "content": ""}]),
    ],
)
def test_unrecognized_structured_responses_are_not_kept(
    kind: SourceKind, body: object
) -> None:
    source = adapter([])
    call = source.ticket_call("a1")
    with pytest.raises(SourceError, match="unrecognized response"):
        source.passage(kind, "a1", call, ToolOutput(json.dumps(body), False), 100)
