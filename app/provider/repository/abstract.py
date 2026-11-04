from abc import ABC, abstractmethod

from app.core.errors import ChangeError
from app.models.code_change import RepositoryFile, SearchMatch, TreeChange


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

    async def search(
        self,
        commit: str,
        pattern: str,
        path: str | None,
        *,
        fixed: bool,
        ignore_case: bool,
    ) -> list[SearchMatch]:
        raise ChangeError("This repository does not support search")

    async def list_files(self, commit: str, path: str | None) -> list[str]:
        raise ChangeError("This repository does not support listing files")
