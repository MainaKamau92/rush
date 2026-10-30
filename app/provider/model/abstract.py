from abc import ABC, abstractmethod

from app.models.model_access import ModelReply
from app.schemas.model_review import ModelRequest
from app.schemas.review import ModelCapabilities


class ModelProviderAbstract(ABC):
    @abstractmethod
    def describe(self, model_id: str) -> ModelCapabilities: ...

    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelReply: ...

    @abstractmethod
    async def close(self) -> None: ...
