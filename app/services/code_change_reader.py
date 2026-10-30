import hashlib
import re
from typing import Literal

from app.core.errors import ChangeError, MissingObjectError
from app.models.code_change import TreeChange
from app.provider.repository.abstract import CodeRepositoryAbstract
from app.schemas.code_change import (
    ChangeLine,
    ChangeScope,
    FileChange,
    Hunk,
    Omission,
    OmissionReason,
)

MAX_FILE_BYTES = 1_048_576
REVISION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/~^-]{0,199}")
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
STATUSES: dict[str, Literal["added", "deleted", "modified", "renamed"]] = {
    "A": "added",
    "D": "deleted",
    "M": "modified",
    "R": "renamed",
}
REGULAR_MODES = {"100644", "100755"}
ABSENT_MODE = "000000"
ENTRY_OMISSIONS: dict[str, tuple[OmissionReason, str]] = {
    "120000": ("symlink", "Symbolic links are not followed or read"),
    "160000": ("submodule", "Submodule contents are not read"),
}


class _OmittedError(Exception):
    def __init__(self, reason: OmissionReason, detail: str) -> None:
        super().__init__(detail)
        self.reason: OmissionReason = reason
        self.detail = detail


class CodeChangeReaderService:
    def __init__(
        self, repository: CodeRepositoryAbstract, max_file_bytes: int = MAX_FILE_BYTES
    ) -> None:
        self._repository = repository
        self._max_file_bytes = max_file_bytes

    async def read(
        self, head: str, *, target: str | None = None, base: str | None = None
    ) -> ChangeScope:
        if (target is None) == (base is None):
            raise ChangeError("Choose either a PR target or an exact base version")
        head_sha = await self._commit(head)
        target_sha = None
        if target is not None:
            target_sha = await self._commit(target)
            base_sha = await self._repository.merge_base(target_sha, head_sha)
        else:
            base_sha = await self._commit(str(base))
        files: list[FileChange] = []
        omissions: list[Omission] = []
        for change in await self._repository.changes(base_sha, head_sha):
            try:
                files.append(await self._file(change))
            except _OmittedError as omitted:
                omissions.append(
                    Omission(
                        reason=omitted.reason,
                        old_path=_display(change.old_path),
                        new_path=_display(change.new_path),
                        detail=omitted.detail,
                    )
                )
        return ChangeScope(
            comparison="exact" if target_sha is None else "merge_base",
            target_sha=target_sha,
            base_sha=base_sha,
            head_sha=head_sha,
            files=tuple(files),
            omissions=tuple(omissions),
        )

    async def _commit(self, revision: str) -> str:
        if not REVISION.fullmatch(revision) or ".." in revision:
            raise ChangeError(
                "Unsupported version reference; use a branch, tag or commit ID"
            )
        return await self._repository.commit(revision)

    async def _file(self, change: TreeChange) -> FileChange:
        for path in (change.old_path, change.new_path):
            if path is not None and not _safe_path(path):
                raise _OmittedError(
                    "invalid_path", "Path is not a safe repository-relative UTF-8 path"
                )
        for mode in (change.old_mode, change.new_mode):
            if mode in ENTRY_OMISSIONS:
                raise _OmittedError(*ENTRY_OMISSIONS[mode])
        status = STATUSES.get(change.status)
        if status is None or {change.old_mode, change.new_mode} - {
            *REGULAR_MODES,
            ABSENT_MODE,
        }:
            raise _OmittedError("unsupported_entry", "This kind of change is not read")
        old_text = await self._text(change.old_object)
        new_text = await self._text(change.new_object)
        if old_text is None or new_text is None:
            hunks = _whole_file(change, old_text, new_text)
        elif change.old_object == change.new_object:
            hunks = []
        else:
            patch = await self._repository.compare(
                str(change.old_object), str(change.new_object)
            )
            hunks = _parse(change, patch)
        lines = [line.kind for hunk in hunks for line in hunk.lines]
        return FileChange(
            status=status,
            old_path=change.old_path,
            new_path=change.new_path,
            old_object=change.old_object,
            new_object=change.new_object,
            old_mode=None if change.old_mode == ABSENT_MODE else change.old_mode,
            new_mode=None if change.new_mode == ABSENT_MODE else change.new_mode,
            similarity=change.similarity,
            additions=lines.count("added"),
            deletions=lines.count("removed"),
            hunks=tuple(hunks),
        )

    async def _text(self, object_id: str | None) -> str | None:
        if object_id is None:
            return None
        try:
            content = await self._repository.blob(object_id, self._max_file_bytes)
        except MissingObjectError as error:
            raise _OmittedError(
                "missing_object", "File content is unavailable"
            ) from error
        if content is None:
            raise _OmittedError(
                "too_large",
                f"File exceeds {self._max_file_bytes} bytes and was not read",
            )
        if b"\0" in content:
            raise _OmittedError("binary", "Binary content is not read")
        try:
            return content.decode()
        except UnicodeDecodeError as error:
            raise _OmittedError("not_utf8", "Content is not valid UTF-8") from error


def _safe_path(path: str) -> bool:
    try:
        path.encode()
    except UnicodeEncodeError:
        return False
    parts = path.split("/")
    return (
        not any(ord(character) < 32 or ord(character) == 127 for character in path)
        and all(part not in {"", ".", ".."} for part in parts)
        and all(part.lower() != ".git" for part in parts)
    )


def _display(path: str | None) -> str | None:
    if path is None:
        return None
    text = path.encode(errors="surrogateescape").decode(errors="backslashreplace")
    return "".join(
        character if character.isprintable() else f"\\x{ord(character):02x}"
        for character in text
    )


def _lines(text: str) -> list[str]:
    lines = text.split("\n")
    return lines[:-1] if text.endswith("\n") else lines


def _hunk_id(change: TreeChange, header: tuple[int, int, int, int]) -> str:
    identity = "\0".join(
        str(part)
        for part in (
            change.old_path,
            change.new_path,
            change.old_object,
            change.new_object,
            *header,
        )
    )
    return "h" + hashlib.sha256(identity.encode()).hexdigest()[:16]


def _whole_file(
    change: TreeChange, old_text: str | None, new_text: str | None
) -> list[Hunk]:
    text = new_text if old_text is None else old_text
    lines = _lines(text or "")
    if not lines:
        return []
    count = len(lines)
    added = old_text is None
    header = (0, 0, 1, count) if added else (1, count, 0, 0)
    return [
        Hunk(
            id=_hunk_id(change, header),
            old_start=header[0],
            old_lines=header[1],
            new_start=header[2],
            new_lines=header[3],
            lines=tuple(
                ChangeLine(kind="added", new_line=number, text=line)
                if added
                else ChangeLine(kind="removed", old_line=number, text=line)
                for number, line in enumerate(lines, start=1)
            ),
        )
    ]


def _parse(change: TreeChange, patch: str) -> list[Hunk]:
    hunks: list[Hunk] = []
    current: tuple[tuple[int, int, int, int], list[ChangeLine]] | None = None
    old_line = new_line = 0
    for raw in patch.split("\n"):
        if match := HUNK_HEADER.match(raw):
            if current is not None:
                hunks.append(_checked_hunk(change, *current))
            old_start, old_count, new_start, new_count = match.groups()
            header = (
                int(old_start),
                1 if old_count is None else int(old_count),
                int(new_start),
                1 if new_count is None else int(new_count),
            )
            current = (header, [])
            old_line, new_line = header[0], header[2]
            continue
        if current is None or not raw or raw.startswith("\\"):
            continue
        marker, text = raw[0], raw[1:]
        if marker == " ":
            current[1].append(
                ChangeLine(
                    kind="context", old_line=old_line, new_line=new_line, text=text
                )
            )
            old_line += 1
            new_line += 1
        elif marker == "+":
            current[1].append(ChangeLine(kind="added", new_line=new_line, text=text))
            new_line += 1
        elif marker == "-":
            current[1].append(ChangeLine(kind="removed", old_line=old_line, text=text))
            old_line += 1
        else:
            raise ChangeError("Git returned a comparison rush cannot read")
    if current is not None:
        hunks.append(_checked_hunk(change, *current))
    return hunks


def _checked_hunk(
    change: TreeChange, header: tuple[int, int, int, int], lines: list[ChangeLine]
) -> Hunk:
    old_count = sum(line.kind != "added" for line in lines)
    new_count = sum(line.kind != "removed" for line in lines)
    if (old_count, new_count) != (header[1], header[3]):
        raise ChangeError("Git returned a comparison rush cannot read")
    return Hunk(
        id=_hunk_id(change, header),
        old_start=header[0],
        old_lines=header[1],
        new_start=header[2],
        new_lines=header[3],
        lines=tuple(lines),
    )
