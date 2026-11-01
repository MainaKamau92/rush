import hashlib
import json
from collections.abc import Callable

from app.schemas.code_change import ChangeLine, ChangeScope, FileChange, Hunk, Omission
from app.schemas.review import ReviewLimits


def _cost(lines: tuple[ChangeLine, ...]) -> int:
    return (
        sum(
            len(json.dumps(line.model_dump(mode="json")).encode())
            + 2 * len(json.dumps(line.text).encode())
            + 24
            for line in lines
        )
        + 1024
    )


def _part(file: FileChange, hunks: tuple[Hunk, ...]) -> FileChange:
    return file.model_copy(
        update={
            "hunks": hunks,
            "additions": sum(line.kind == "added" for h in hunks for line in h.lines),
            "deletions": sum(line.kind == "removed" for h in hunks for line in h.lines),
        }
    )


class ChangeBatchService:
    def __init__(self, limits: ReviewLimits, check: Callable[[], float] | None = None):
        self._limits, self._check = limits, check
        self._bytes = max(1, limits.source_bytes // 2)

    def prepare(self, scope: ChangeScope) -> ChangeScope:
        files, omissions = [], list(scope.omissions)
        for file in scope.files:
            hunks = []
            for hunk in file.hunks:
                chunks, missing = self._chunks(hunk.lines)
                if missing:
                    omissions.append(
                        Omission(
                            reason="budget",
                            old_path=file.old_path,
                            new_path=file.new_path,
                            detail="A changed passage exceeds the "
                            "per-batch source allowance",
                        )
                    )
                if len(chunks) == 1 and chunks[0] == hunk.lines:
                    hunks.append(hunk)
                else:
                    hunks.extend(
                        self._hunk(hunk, lines, i) for i, lines in enumerate(chunks)
                    )
            files.append(_part(file, tuple(hunks)))
        return scope.model_copy(
            update={"files": tuple(files), "omissions": tuple(omissions)}
        )

    def _chunks(
        self, lines: tuple[ChangeLine, ...]
    ) -> tuple[list[tuple[ChangeLine, ...]], bool]:
        chunks: list[tuple[ChangeLine, ...]] = []
        current: list[ChangeLine] = []
        size, changed, missing = 1024, 0, False
        for line in lines:
            if self._check:
                self._check()
            cost = _cost((line,)) - 1024
            amount = int(line.kind != "context")
            if current and (
                size + cost > self._bytes
                or changed + amount > self._limits.changed_lines
            ):
                chunks.append(tuple(current))
                current, size, changed = [], 1024, 0
            if cost + 1024 > self._bytes:
                missing = True
                continue
            current.append(line)
            size += cost
            changed += amount
        if current:
            chunks.append(tuple(current))
        return chunks, missing

    @staticmethod
    def _hunk(hunk: Hunk, lines: tuple[ChangeLine, ...], index: int) -> Hunk:
        old = [line.old_line for line in lines if line.old_line is not None]
        new = [line.new_line for line in lines if line.new_line is not None]
        return Hunk(
            id="h" + hashlib.sha256(f"{hunk.id}:{index}".encode()).hexdigest()[:16],
            old_start=min(old, default=hunk.old_start),
            old_lines=len(old),
            new_start=min(new, default=hunk.new_start),
            new_lines=len(new),
            lines=lines,
        )

    def plan(self, scope: ChangeScope) -> tuple[ChangeScope, ...]:
        batches: list[ChangeScope] = []
        current: dict[str, FileChange] = {}
        size = changed = 0
        for file in scope.files:
            path = file.new_path or file.old_path or ""
            for hunk in file.hunks or (None,):
                if self._check:
                    self._check()
                amount = (
                    sum(line.kind != "context" for line in hunk.lines) if hunk else 0
                )
                cost = _cost(hunk.lines if hunk else ())
                full = (
                    len(current) + (path not in current) > self._limits.changed_files
                    or changed + amount > self._limits.changed_lines
                    or size + cost > self._bytes
                )
                if current and full:
                    batches.append(
                        scope.model_copy(
                            update={"files": tuple(current.values()), "omissions": ()}
                        )
                    )
                    current, size, changed = {}, 0, 0
                previous = current.get(path)
                current[path] = _part(
                    file,
                    (*(previous.hunks if previous else ()), *((hunk,) if hunk else ())),
                )
                size += cost
                changed += amount
        if current:
            batches.append(
                scope.model_copy(
                    update={"files": tuple(current.values()), "omissions": ()}
                )
            )
        return tuple(batches)
