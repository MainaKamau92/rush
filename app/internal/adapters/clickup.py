import json
import re
from collections.abc import Iterator
from contextlib import AsyncExitStack, contextmanager

import httpx2
from mcp import Client
from mcp.client.auth import OAuthFlowError
from mcp.shared.exceptions import MCPError
from mcp.types import TextContent, Tool

from app.core.errors import SourceAccessError, SourceError, SourceRateLimitError
from app.internal.adapters.mcp_auth import (
    AuthorizationRequiredError,
    CredentialRejectedError,
)
from app.models.source_access import (
    SourceKind,
    SourcePassage,
    SourceTool,
    TicketLinks,
    ToolCall,
    ToolOutput,
)
from app.provider.source.abstract import SourceProviderAbstract

_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}")
_TASK_LINK = re.compile(
    r"(?:^|(?<=[\s(<\[\"']))https://app\.clickup\.com/t/"
    r"(?:(?P<workspace>[0-9]{1,32})/)?(?P<task>[A-Za-z0-9_-]{1,64})(?=$|[\s)>\]\"'.,;:!?])"
)
_ORIGIN = "https://app.clickup.com/"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _section(title: str | None, body: str | None) -> str:
    return "\n\n".join(part for part in (f"# {title}" if title else None, body) if part)


_PLAIN = object()


def _pages(data: object) -> list[dict[str, object]]:
    pages = data.get("pages") if isinstance(data, dict) else data
    if isinstance(pages, list) and all(isinstance(page, dict) for page in pages):
        return pages
    return []


def _version(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value) or None


def _identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value):
        raise SourceError(f"Specify a valid ClickUp {label}")
    return value


def _leaves(error: BaseException) -> list[BaseException]:
    if isinstance(error, BaseExceptionGroup):
        return [leaf for inner in error.exceptions for leaf in _leaves(inner)]
    return [error]


def _status_error(status: int) -> SourceError | None:
    if status == 429:
        return SourceRateLimitError("ClickUp request limit reached; retry later")
    if status in {401, 403}:
        return SourceAccessError(
            f"ClickUp refused access (HTTP {status}); check the credential "
            "or run rush source-connect"
        )
    return None


def _source_error(error: Exception) -> SourceError | None:
    for leaf in _leaves(error):
        if isinstance(leaf, SourceError):
            return leaf
        if isinstance(leaf, AuthorizationRequiredError):
            return SourceAccessError(
                "ClickUp authorization is required; run rush source-connect"
            )
        if isinstance(leaf, CredentialRejectedError):
            return SourceAccessError(
                "ClickUp rejected the configured credential; replace "
                "CLICK_UP_API_TOKEN or run rush source-connect"
            )
        if isinstance(leaf, OAuthFlowError):
            return SourceAccessError(
                "ClickUp sign-in failed; run rush source-connect again"
            )
        if isinstance(leaf, httpx2.HTTPStatusError) and (
            refused := _status_error(leaf.response.status_code)
        ):
            return refused
        if isinstance(leaf, httpx2.TimeoutException):
            return SourceError("ClickUp request timed out; no retry was attempted")
        if isinstance(leaf, httpx2.HTTPError):
            return SourceError("ClickUp connection failed; no retry was attempted")
        if isinstance(leaf, MCPError):
            return SourceError(f"ClickUp returned protocol error {leaf.error.code}")
    return None


@contextmanager
def _translated_errors() -> Iterator[None]:
    try:
        yield
    except Exception as error:
        translated = _source_error(error)
        if translated is None:
            raise
        raise translated from None


def _tool(tool: Tool) -> SourceTool:
    schema = tool.input_schema
    annotations = tool.annotations
    return SourceTool(
        name=tool.name,
        required_inputs=tuple(schema.get("required", ())),
        accepted_inputs=tuple(schema.get("properties", {})),
        read_only=annotations.read_only_hint if annotations else None,
        destructive=annotations.destructive_hint if annotations else None,
    )


class ClickUpSourceAdapter(SourceProviderAbstract):
    name = "clickup"

    def __init__(
        self,
        client: Client,
        workspace_id: str,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        self._client = client
        self._workspace_id = _identifier(workspace_id, "workspace ID")
        self._http_client = http_client
        self._stack = AsyncExitStack()
        self._connected = False

    def ticket_call(self, reference: str) -> ToolCall:
        return ToolCall(
            "clickup_get_task",
            {
                "task_id": _identifier(reference, "task ID"),
                "workspace_id": self._workspace_id,
            },
        )

    def guideline_call(self, reference: str) -> ToolCall:
        document, _, page = reference.partition("/")
        return ToolCall(
            "clickup_get_document_pages",
            {
                "document_id": _identifier(document, "document ID"),
                "page_ids": [_identifier(page, "page ID")],
                "workspace_id": self._workspace_id,
            },
        )

    def ticket_references(self, text: str) -> TicketLinks:
        references: list[str] = []
        outside = 0
        for match in _TASK_LINK.finditer(text):
            workspace = match["workspace"]
            if workspace is not None and workspace != self._workspace_id:
                outside += 1
            elif match["task"] not in references:
                references.append(match["task"])
        return TicketLinks(tuple(references), outside)

    def passage(
        self,
        kind: SourceKind,
        reference: str,
        call: ToolCall,
        output: ToolOutput,
        limit: int,
    ) -> SourcePassage:
        try:
            data: object = json.loads(output.text)
        except ValueError:
            data = _PLAIN
        text, url, version = output.text, None, None
        if data is _PLAIN:
            pass
        elif kind == "ticket" and isinstance(data, dict):
            text = _section(
                _text(data.get("name")),
                _text(data.get("text_content"))
                or _text(data.get("markdown_description"))
                or _text(data.get("description")),
            )
            url = _text(data.get("url"))
            updated = _version(data.get("date_updated"))
            version = f"date_updated:{updated}" if updated else None
        elif kind == "guideline" and _pages(data):
            pages = _pages(data)
            text = "\n\n".join(
                _section(_text(page.get("name")), _text(page.get("content")))
                for page in pages
            )
            versions = {_version(page.get("version")) for page in pages}
            version = versions.pop() if len(versions) == 1 else None
        else:
            text = ""
        if not text.strip():
            raise SourceError(
                f"{call.tool} returned an unrecognized response; nothing was kept"
            )
        if url is not None and not url.startswith(_ORIGIN):
            url = None
        return SourcePassage(
            kind=kind,
            reference=reference,
            tool=call.tool,
            text=text[:limit],
            url=url,
            version=version,
            truncated=len(text) > limit,
        )

    async def _session(self) -> Client:
        if not self._connected:
            await self._stack.enter_async_context(self._client)
            self._connected = True
        return self._client

    async def list_tools(self) -> list[SourceTool]:
        tools: list[SourceTool] = []
        cursor: str | None = None
        with _translated_errors():
            client = await self._session()
            while True:
                page = await client.list_tools(cursor=cursor)
                tools.extend(_tool(tool) for tool in page.tools)
                cursor = page.next_cursor
                if cursor is None:
                    return tools

    async def call_tool(self, call: ToolCall) -> ToolOutput:
        with _translated_errors():
            client = await self._session()
            result = await client.call_tool(call.tool, call.arguments)
        text = "".join(
            block.text for block in result.content if isinstance(block, TextContent)
        )
        if not text and result.structured_content is not None:
            text = json.dumps(result.structured_content, sort_keys=True)
        if result.is_error and "RATE_LIMIT_EXCEEDED" in text:
            raise SourceRateLimitError("ClickUp request limit reached; retry later")
        return ToolOutput(text, result.is_error)

    async def close(self) -> None:
        try:
            await self._stack.aclose()
        finally:
            if self._http_client is not None:
                await self._http_client.aclose()
