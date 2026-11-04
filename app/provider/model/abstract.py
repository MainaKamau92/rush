from abc import ABC, abstractmethod

from app.core.errors import ModelError
from app.models.model_access import ModelReply, ToolReply
from app.schemas.model_review import ModelRequest, ToolRequest
from app.schemas.review import ModelCapabilities


class ModelProviderAbstract(ABC):
    @abstractmethod
    def describe(self, model_id: str) -> ModelCapabilities: ...

    @abstractmethod
    async def generate(self, request: ModelRequest) -> ModelReply: ...

    async def converse(self, request: ToolRequest) -> ToolReply:
        raise ModelError("This model provider does not support tool calls")

    @abstractmethod
    async def close(self) -> None: ...
