from abc import ABC, abstractmethod

from app.models.model_access import ModelReply


class ModelProviderAbstract(ABC):
    @abstractmethod
    async def generate(
        self, model_id: str, prompt: str, max_output_tokens: int
    ) -> ModelReply: ...

    @abstractmethod
    async def close(self) -> None: ...
