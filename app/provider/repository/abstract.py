from abc import ABC, abstractmethod

from app.models.code_change import RepositoryFile, TreeChange


class CodeRepositoryAbstract(ABC):
    @abstractmethod
    async def commit(self, revision: str) -> str: ...

    @abstractmethod
    async def merge_base(self, target: str, head: str) -> str: ...

    @abstractmethod
    async def changes(self, base: str, head: str) -> list[TreeChange]: ...

    @abstractmethod
    async def blob(self, object_id: str, limit: int) -> bytes | None: ...

    @abstractmethod
    async def compare(self, old_object: str, new_object: str) -> str: ...

    @abstractmethod
    async def file(self, commit: str, path: str, limit: int) -> RepositoryFile: ...
