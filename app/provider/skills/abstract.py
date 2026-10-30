from abc import ABC, abstractmethod

from app.models.skill import PackageFile


class SkillStoreAbstract(ABC):
    @abstractmethod
    async def approved(self) -> bytes: ...

    @abstractmethod
    async def package(self, name: str) -> tuple[PackageFile, ...]: ...

    @abstractmethod
    async def evaluation(self, name: str) -> bytes | None: ...

    @abstractmethod
    async def save_evaluation(self, name: str, content: bytes) -> None: ...
