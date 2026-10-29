import asyncio

from app.core.errors import ModelError
from app.models.model_access import ModelAccess
from app.services.ports import TextModelProvider


class ModelAccessService:
    def __init__(
        self, provider: TextModelProvider, timeout_seconds: float = 30
    ) -> None:
        self._provider = provider
        self._timeout_seconds = timeout_seconds

    async def check(self, model_id: str) -> ModelAccess:
        if not model_id or model_id != model_id.strip():
            raise ModelError("Specify a valid, explicit model ID")
        try:
            async with asyncio.timeout(self._timeout_seconds):
                reply = await self._provider.generate(
                    model_id, "Reply with RUSH_OK.", 128
                )
        except TimeoutError:
            raise ModelError("Model access check timed out") from None
        if reply.model_id != model_id:
            raise ModelError("Provider returned a different model; access check failed")
        if reply.text.strip() != "RUSH_OK":
            raise ModelError("Model did not return the expected access-check reply")
        return ModelAccess(
            provider=reply.provider,
            requested_model=model_id,
            resolved_model=reply.model_id,
            usage=reply.usage,
            rate_limits=reply.rate_limits,
        )

    async def close(self) -> None:
        await self._provider.close()
