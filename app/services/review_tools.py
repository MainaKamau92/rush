"""
Repository tools a review model calls while it reviews a change: read a file,
search the repository, and list files, all at the frozen review commits.

Access is liberal by design: any tracked text file may be read whole, within
per-call and per-conversation size limits. Paths stay inside the repository,
`.git` is never read, and files that commonly hold secrets are refused.
"""

import json
from collections.abc import Callable
from typing import Annotated, Any, Literal

from pydantic import Field, ValidationError

from app.core.errors import ChangeError, MissingObjectError
from app.models.repository_path import path_matches, safe_repository_path
from app.schemas.code_change import ChangeScope
from app.schemas.investigation import ToolUse
from app.schemas.review import Contract, Positive, Text
from app.services.investigation import InvestigationService

READ_LINES = 1500
READ_BYTES = 160_000
FILE_BYTES = 2_000_000
SEARCH_RESULTS = 150
LIST_RESULTS = 500
SECRET_FILES = (
    "**/.env",
    "**/.env.*",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    "**/*.keystore",
    "**/*.jks",
    "**/id_rsa*",
    "**/id_ed25519*",
    "**/.netrc",
    "**/.npmrc",
    "**/.pypirc",
    "**/credentials*.json",
    "**/secrets/**",
)
SAFE_EXAMPLES = ("**/.env.example", "**/.env.sample", "**/.env.template")
Ref = Literal["head", "base"]


def is_secret_file(path: str) -> bool:
    if any(path_matches(pattern, path) for pattern in SAFE_EXAMPLES):
        return False
    return any(path_matches(pattern, path) for pattern in SECRET_FILES)


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


REF_PROPERTY = {
    "type": "string",
    "enum": ["head", "base"],
    "description": "head (default) is the PR's version; base is before the change.",
}
READ_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "type": "function",
        "name": "read_file",
        "description": "Read a repository file with line numbers. Omit the lines "
        "to read the whole file (long files are returned in parts; ask for the "
        "next part by start_line). Read whatever helps: callers, callees, "
        "models, tests, configuration.",
        "parameters": _schema(
            {
                "path": {"type": "string", "description": "Repository-relative path."},
                "start_line": {"type": "integer", "minimum": 1},
                "end_line": {"type": "integer", "minimum": 1},
                "ref": REF_PROPERTY,
            },
            ["path"],
        ),
    },
    {
        "type": "function",
        "name": "search",
        "description": "Search tracked files (git grep, POSIX extended regex "
        "unless fixed is true). Returns path:line: text, at most 25 matches per "
        "file. Use it to find definitions, callers and usages.",
        "parameters": _schema(
            {
                "pattern": {"type": "string"},
                "path": {
                    "type": "string",
                    "description": "Optional file or folder to search within.",
                },
                "glob": {
                    "type": "string",
                    "description": "Optional filename filter, e.g. **/*.py.",
                },
                "fixed": {"type": "boolean"},
                "ignore_case": {"type": "boolean"},
                "ref": REF_PROPERTY,
            },
            ["pattern"],
        ),
    },
    {
        "type": "function",
        "name": "list_files",
        "description": "List tracked files, under a folder if given.",
        "parameters": _schema(
            {
                "path": {"type": "string", "description": "Optional folder."},
                "ref": REF_PROPERTY,
            },
            [],
        ),
    },
)


class _Read(Contract):
    path: Text
    start_line: Positive | None = None
    end_line: Positive | None = None
    ref: Ref = "head"


class _Search(Contract):
    pattern: Annotated[str, Field(min_length=1, max_length=500)]
    path: Text | None = None
    glob: Annotated[str, Field(max_length=200)] | None = None
    fixed: bool = False
    ignore_case: bool = False
    ref: Ref = "head"


class _List(Contract):
    path: Text | None = None
    ref: Ref = "head"


class RepositoryTools:
    """
    Run one review conversation's tool calls. Results are plain text for the
    model; every call is recorded on the investigation's audit trail.
    """

    def __init__(
        self,
        investigation: InvestigationService,
        scope: ChangeScope,
        conversation_bytes: int,
        on_limit: Callable[[str], None] | None = None,
    ) -> None:
        self._investigation, self._scope = investigation, scope
        self._remaining = conversation_bytes
        self._on_limit = on_limit
        self._texts: dict[tuple[str, str], str] = {}

    @property
    def remaining_bytes(self) -> int:
        return self._remaining

    def commit(self, ref: Ref) -> str:
        return self._scope.head_sha if ref == "head" else self._scope.base_sha

    async def text(self, path: str, ref: Ref = "head") -> str:
        """The whole text of a file at a review commit, cached per conversation."""
        key = (ref, path)
        if key not in self._texts:
            if not safe_repository_path(path) or is_secret_file(path):
                raise ChangeError("This path cannot be read")
            file = await self._investigation.repository.file(
                self.commit(ref), path, FILE_BYTES
            )
            if file.mode not in {"100644", "100755"}:
                raise ChangeError("Not a regular file")
            if file.content is None:
                raise ChangeError("File is larger than 2 MB")
            if b"\0" in file.content:
                raise ChangeError("Binary file")
            self._texts[key] = file.content.decode(errors="replace")
        return self._texts[key]

    async def run(self, name: str, arguments: str) -> str:
        """Run one tool call and return its text result."""
        self._investigation.check_time()
        try:
            values = json.loads(arguments or "{}")
            if not isinstance(values, dict):
                raise ValueError
        except ValueError:
            return "Error: arguments must be a JSON object."
        if name not in {"read_file", "search", "list_files"}:
            return f"Error: unknown tool {name}."
        if self._remaining <= 0:
            target = str(values.get("path") or values.get("pattern") or "")
            self._record(name, target, "refused", "conversation read limit reached")
            return (
                "Error: this conversation's read limit is reached. Finish with the "
                "evidence you already have."
            )
        try:
            if name == "read_file":
                result = await self._read(_Read.model_validate(values, strict=False))
            elif name == "search":
                result = await self._search(
                    _Search.model_validate(values, strict=False)
                )
            else:
                result = await self._list(_List.model_validate(values, strict=False))
        except ValidationError as error:
            problems = "; ".join(
                f"{'.'.join(map(str, item['loc'])) or 'arguments'}: {item['msg']}"
                for item in error.errors()
            )
            return f"Error: invalid arguments ({problems})."
        size = len(result.encode())
        if size > self._remaining:
            result = result.encode()[: self._remaining].decode(errors="ignore")
            result += "\n[truncated: conversation read limit reached]"
            if self._on_limit is not None:
                self._on_limit(name)
        self._remaining -= min(size, self._remaining)
        return result

    def _record(
        self, tool: str, target: str, outcome: str, detail: str, size: int = 0
    ) -> None:
        self._investigation.record_tool(
            ToolUse.model_validate(
                {
                    "tool": tool,
                    "target": target[:300] or "(repository)",
                    "outcome": outcome,
                    "detail": detail[:300],
                    "bytes": size,
                }
            )
        )

    async def _read(self, request: _Read) -> str:
        try:
            text = await self.text(request.path, request.ref)
        except MissingObjectError as error:
            self._record("read_file", request.path, "failed", str(error))
            return f"Error: {request.path} does not exist at {request.ref}."
        except ChangeError as error:
            self._record("read_file", request.path, "refused", str(error))
            return f"Error: {request.path}: {error}."
        lines = text.splitlines()
        start = request.start_line or 1
        end = min(request.end_line or len(lines), len(lines), start + READ_LINES - 1)
        if start > max(1, len(lines)):
            self._record("read_file", request.path, "failed", "start past end")
            return f"Error: {request.path} has only {len(lines)} lines."
        body: list[str] = []
        size = 0
        for number in range(start, end + 1):
            row = f"{number}| {lines[number - 1]}"
            size += len(row) + 1
            if size > READ_BYTES and body:
                end = number - 1
                break
            body.append(row)
        header = f"{request.path} ({request.ref}) lines {start}-{end} of {len(lines)}"
        if end < len(lines) and (request.end_line is None or end < request.end_line):
            header += f"; continue with start_line={end + 1}"
        self._record("read_file", request.path, "ok", f"lines {start}-{end}", size)
        return header + "\n" + "\n".join(body)

    async def _search(self, request: _Search) -> str:
        target = request.pattern + (f" in {request.path}" if request.path else "")
        try:
            matches = await self._investigation.repository.search(
                self.commit(request.ref),
                request.pattern,
                request.path,
                fixed=request.fixed,
                ignore_case=request.ignore_case,
            )
        except ChangeError as error:
            self._record("search", target, "failed", str(error))
            return f"Error: {error}."
        kept = [
            match
            for match in matches
            if not is_secret_file(match.path)
            and (request.glob is None or path_matches(request.glob, match.path))
        ]
        rows = [
            f"{match.path}:{match.line}: {match.text[:300]}"
            for match in kept[:SEARCH_RESULTS]
        ]
        if len(kept) > SEARCH_RESULTS:
            rows.append(
                f"[{len(kept) - SEARCH_RESULTS} more matches; narrow the pattern "
                "or path]"
            )
        result = "\n".join(rows) or "No matches."
        self._record("search", target, "ok", f"{len(kept)} matches", len(result))
        return result

    async def _list(self, request: _List) -> str:
        target = request.path or ""
        try:
            names = await self._investigation.repository.list_files(
                self.commit(request.ref), request.path
            )
        except ChangeError as error:
            self._record("list_files", target, "failed", str(error))
            return f"Error: {error}."
        rows = names[:LIST_RESULTS]
        if len(names) > LIST_RESULTS:
            rows.append(f"[{len(names) - LIST_RESULTS} more files; list a subfolder]")
        result = "\n".join(rows) or "No files."
        self._record("list_files", target, "ok", f"{len(names)} files", len(result))
        return result


def render_change(scope: ChangeScope) -> str:
    """
    The change as compact text: each changed file's hunks with head line
    numbers for added and context lines and base numbers for removed lines.
    """
    parts = []
    for file in scope.files:
        path = file.new_path or file.old_path
        title = f"## {path} ({file.status}, +{file.additions} -{file.deletions})"
        if file.status == "renamed":
            title += f" renamed from {file.old_path}"
        parts.append(title)
        for hunk in file.hunks:
            parts.append(
                f"@@ base {hunk.old_start},{hunk.old_lines} head "
                f"{hunk.new_start},{hunk.new_lines} @@"
            )
            for line in hunk.lines:
                if line.kind == "removed":
                    parts.append(f"-{line.old_line:>5} | {line.text}")
                else:
                    mark = "+" if line.kind == "added" else " "
                    parts.append(f"{mark}{line.new_line:>5} | {line.text}")
    for omission in scope.omissions:
        parts.append(
            f"## {omission.new_path or omission.old_path} (not shown: "
            f"{omission.detail})"
        )
    return "\n".join(parts)
