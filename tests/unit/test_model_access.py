import asyncio

import pytest

from app.core.errors import ModelError
from app.models.model_access import ModelReply, TokenUsage
from app.provider.model.abstract import ModelProviderAbstract
from app.schemas.model_review import ModelRequest
from app.schemas.review import ModelCapabilities
from app.services.model_access import ModelAccessService


class ControlledModel(ModelProviderAbstract):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.reply = ModelReply("meta", "muse-spark-1.3", "RUSH_OK", None, {})
        self.error: Exception | None = None
        self.closed = False

    def describe(self, model_id: str) -> ModelCapabilities:
        return ModelCapabilities(
            provider="meta",
            model_id=model_id,
            adapter_version="test",
            native_tool_calls=False,
            native_structured_output=False,
        )

    async def generate(self, request: ModelRequest) -> ModelReply:
        self.calls.append((request.model_id, request.prompt, request.max_output_tokens))
        if self.error:
            raise self.error
        return self.reply

    async def close(self) -> None:
        self.closed = True


async def test_access_check_uses_only_the_bounded_public_prompt() -> None:
    provider = ControlledModel()
    usage = TokenUsage(10, 4, 14)
    provider.reply = ModelReply("meta", "muse-spark-1.3", "RUSH_OK\n", usage, {})
    service = ModelAccessService(provider)
    result = await service.check("muse-spark-1.3")
    assert provider.calls == [("muse-spark-1.3", "Reply with RUSH_OK.", 128)]
    assert result.requested_model == result.resolved_model == "muse-spark-1.3"
    assert result.usage == usage
    await service.close()
    assert provider.closed


@pytest.mark.parametrize("model", ["", " ", " trailing-space "])
async def test_missing_or_padded_identity_does_not_send_a_request(
    model: str,
) -> None:
    provider = ControlledModel()
    with pytest.raises(ModelError):
        await ModelAccessService(provider).check(model)
    assert provider.calls == []


async def test_service_accepts_other_provider_identity_without_vendor_logic() -> None:
    provider = ControlledModel()
    provider.reply = ModelReply("other", "org/model:version", "RUSH_OK", None, {})
    result = await ModelAccessService(provider).check("org/model:version")
    assert result.provider == "other"
    assert result.requested_model == result.resolved_model == "org/model:version"


@pytest.mark.parametrize(
    ("model", "text", "message"),
    [
        ("different-model", "RUSH_OK", "different model"),
        ("muse-spark-1.3", "", "expected"),
        ("muse-spark-1.3", "Unable to answer", "expected"),
    ],
)
async def test_unexpected_response_never_becomes_success(
    model: str, text: str, message: str
) -> None:
    provider = ControlledModel()
    provider.reply = ModelReply("meta", model, text, None, {})
    with pytest.raises(ModelError, match=message):
        await ModelAccessService(provider).check("muse-spark-1.3")
    assert len(provider.calls) == 1


async def test_provider_failure_never_triggers_another_model_or_retry() -> None:
    provider = ControlledModel()
    provider.error = ModelError("Unavailable")
    with pytest.raises(ModelError, match="Unavailable"):
        await ModelAccessService(provider).check("muse-spark-1.3")
    assert len(provider.calls) == 1


async def test_cancellation_stops_work_without_another_request() -> None:
    class CancelledModel(ControlledModel):
        async def generate(self, request: ModelRequest) -> ModelReply:
            self.calls.append(
                (request.model_id, request.prompt, request.max_output_tokens)
            )
            raise asyncio.CancelledError

    provider = CancelledModel()
    with pytest.raises(asyncio.CancelledError):
        await ModelAccessService(provider).check("muse-spark-1.3")
    assert len(provider.calls) == 1


async def test_total_deadline_cancels_a_stalled_provider() -> None:
    cancelled = asyncio.Event()

    class StalledModel(ControlledModel):
        async def generate(self, request: ModelRequest) -> ModelReply:
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            raise AssertionError("Stalled request unexpectedly completed")

    with pytest.raises(ModelError, match="timed out"):
        await ModelAccessService(StalledModel(), timeout_seconds=0.01).check(
            "muse-spark-1.3"
        )
    assert cancelled.is_set()


@pytest.mark.parametrize(
    "changes",
    [{"status": "incomplete"}, {"unsupported_features": ("non_text_output",)}],
)
async def test_access_check_does_not_accept_a_correct_text_inside_an_incomplete_reply(
    changes,
):
    from dataclasses import replace

    provider = ControlledModel()
    provider.reply = replace(provider.reply, **changes)
    with pytest.raises(ModelError, match="incomplete or unsupported"):
        await ModelAccessService(provider).check("muse-spark-1.3")
    assert len(provider.calls) == 1
