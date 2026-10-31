from abc import ABC, abstractmethod
from pathlib import Path
from typing import Literal

from app.models.github import HostComment, Placement
from app.schemas.github import PullRequest

CommentKind = Literal["issue", "review"]


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
    async def bot_comments(
        self, installation_id: int, repository: str, number: int, kind: CommentKind
    ) -> list[HostComment]: ...

    @abstractmethod
    async def post_comment(
        self,
        installation_id: int,
        repository: str,
        number: int,
        body: str,
        placement: Placement | None,
    ) -> int: ...

    @abstractmethod
    async def edit_comment(
        self,
        installation_id: int,
        repository: str,
        kind: CommentKind,
        comment_id: int,
        body: str,
    ) -> None: ...

    @abstractmethod
    async def report_check(
        self,
        installation_id: int,
        repository: str,
        head_sha: str,
        conclusion: Literal["success", "neutral", "failure"],
        title: str,
        summary: str,
    ) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...
