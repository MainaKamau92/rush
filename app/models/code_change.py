from dataclasses import dataclass


@dataclass(frozen=True)
class TreeChange:
    status: str
    old_mode: str
    new_mode: str
    old_object: str | None
    new_object: str | None
    old_path: str | None
    new_path: str | None
    similarity: int | None = None


@dataclass(frozen=True)
class RepositoryFile:
    path: str
    object_id: str
    mode: str
    content: bytes | None
