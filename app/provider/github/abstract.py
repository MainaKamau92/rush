from abc import ABC, abstractmethod
from pathlib import Path

from app.schemas.github import PullRequest


class CodeHostAbstract(ABC):
    @abstractmethod
    async def pull_request(
        self, installation_id: int, repository: str, number: int
    ) -> PullRequest: ...

    @abstractmethod
    async def permission(
        self, installation_id: int, repository: str, user: str
    ) -> str: ...

    @abstractmethod
    async def fetch(
        self, installation_id: int, pull: PullRequest, mirror: Path
    ) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
