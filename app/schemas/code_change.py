import hashlib
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from app.schemas.review import (
    Commit,
    Contract,
    DiffAnchor,
    Limitation,
    NonNegative,
    Positive,
    Text,
)

RepositoryPath = Annotated[str, Field(min_length=1)]
Side = Literal["LEFT", "RIGHT"]
OmissionReason = Literal[
    "invalid_path",
    "symlink",
    "submodule",
    "unsupported_entry",
    "binary",
    "not_utf8",
    "too_large",
    "missing_object",
]


class ChangeLine(Contract):
    kind: Literal["context", "added", "removed"]
    old_line: Positive | None = None
    new_line: Positive | None = None
    text: str


class Hunk(Contract):
    id: Text
    old_start: NonNegative
    old_lines: NonNegative
    new_start: NonNegative
    new_lines: NonNegative
    lines: tuple[ChangeLine, ...]


class FileChange(Contract):
    status: Literal["added", "deleted", "modified", "renamed"]
    old_path: RepositoryPath | None
    new_path: RepositoryPath | None
    old_object: Commit | None
    new_object: Commit | None
    old_mode: Text | None
    new_mode: Text | None
    similarity: Annotated[int, Field(ge=0, le=100)] | None = None
    additions: NonNegative
    deletions: NonNegative
    hunks: tuple[Hunk, ...]


class Omission(Contract):
    reason: OmissionReason
    old_path: RepositoryPath | None
    new_path: RepositoryPath | None
    detail: Text


class ChangeScope(Contract):
    schema_version: Literal[1] = 1
    comparison: Literal["merge_base", "exact"]
    target_sha: Commit | None
    base_sha: Commit
    head_sha: Commit
    files: tuple[FileChange, ...]
    omissions: tuple[Omission, ...]

    @model_validator(mode="after")
    def target_matches_comparison(self) -> Self:
        if (self.comparison == "merge_base") != (self.target_sha is not None):
            raise ValueError("Only a merge-base comparison records a target")
        return self

    @property
    def complete(self) -> bool:
        return not self.omissions

    def manifest_sha256(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()

    def limitations(self) -> tuple[Limitation, ...]:
        return tuple(
            Limitation(
                code="scope_excluded",
                reason=f"{omission.new_path or omission.old_path}: {omission.detail}",
            )
            for omission in self.omissions
        )

    def anchor(self, path: str, side: Side, line: int) -> DiffAnchor | None:
        for change in self.files:
            if (change.old_path if side == "LEFT" else change.new_path) != path:
                continue
            for hunk in change.hunks:
                for item in hunk.lines:
                    if (item.old_line if side == "LEFT" else item.new_line) == line:
                        return DiffAnchor(
                            path=path, side=side, line=line, hunk_id=hunk.id
                        )
        return None
