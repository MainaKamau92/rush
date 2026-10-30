import re
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.errors import ModelError
from app.models.model_access import ModelReply, TokenUsage
from app.provider.model.abstract import ModelProviderAbstract
from app.schemas.model_review import ModelRequest
from app.schemas.review import ModelCapabilities

ADAPTER_VERSION = "0.2.0"
MAX_RESPONSE_BYTES = 1048576


class _Content(BaseModel):
    type: str
    text: str = ""


class _Output(BaseModel):
    type: str
    role: str | None = None
    content: list[_Content] = Field(default_factory=list)


class _Usage(BaseModel):
    input_tokens: Annotated[int, Field(strict=True, ge=0)]
    output_tokens: Annotated[int, Field(strict=True, ge=0)]
    total_tokens: Annotated[int, Field(strict=True, ge=0)]


class _Response(BaseModel):
    status: Literal["completed", "incomplete", "failed", "cancelled"]
    model: Annotated[str, Field(min_length=1)]
    output: list[_Output]
    usage: _Usage | None = None


def _parse_reply(body: bytes, headers: httpx.Headers) -> ModelReply:
    try:
        data = _Response.model_validate_json(body)
    except ValidationError:
        raise ModelError("Meta returned an invalid or incomplete response") from None
    text = "".join(
        content.text
        for item in data.output
        if item.type == "message" and item.role == "assistant"
        for content in item.content
        if content.type == "output_text"
    )
    usage = None
    if data.usage is not None:
        usage = TokenUsage(**data.usage.model_dump())
    rates = {}
    for name in (
        "x-ratelimit-limit-tokens",
        "x-ratelimit-remaining-tokens",
        "x-ratelimit-limit-requests",
        "x-ratelimit-remaining-requests",
    ):
        value = headers.get(name, "")
        if value.isascii() and value.isdigit():
            rates[name] = int(value)
    unsupported = set()
    for item in data.output:
        if item.type not in {"message", "reasoning"}:
            unsupported.add(
                "native_tool_calls"
                if item.type == "function_call"
                else "non_text_output"
            )
        if any(content.type != "output_text" for content in item.content):
            unsupported.add("non_text_output")
    return ModelReply(
        "meta",
        data.model,
        text,
        usage,
        rates,
        status=data.status,
        unsupported_features=tuple(sorted(unsupported)),
    )


def _validate_model(model_id: str) -> None:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,127}", model_id):
        raise ModelError("Specify a valid Meta model ID")
    if "contributor" in model_id:
        raise ModelError("Contributor mode is not enabled; select a Standard model")


class MetaModelAdapter(ModelProviderAbstract):
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    def describe(self, model_id: str) -> ModelCapabilities:
        _validate_model(model_id)
        return ModelCapabilities(
            provider="meta",
            model_id=model_id,
            adapter_version=ADAPTER_VERSION,
            native_tool_calls=False,
            native_structured_output=False,
        )

    async def generate(self, request: ModelRequest) -> ModelReply:
        _validate_model(request.model_id)
        if request.max_output_tokens < 16:
            raise ModelError("Meta requires at least 16 output tokens")
        payload: dict[str, object] = {
            "model": request.model_id,
            "input": request.prompt,
            "max_output_tokens": request.max_output_tokens,
            "reasoning": {"effort": "minimal"},
            "store": False,
        }
        if request.instructions is not None:
            payload["instructions"] = request.instructions
        try:
            async with self._client.stream(
                "POST", "responses", json=payload
            ) as response:
                _check_status(response.status_code)
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ModelError("Meta response exceeds the supported size")
                    body.extend(chunk)
                return _parse_reply(bytes(body), response.headers)
        except httpx.TimeoutException:
            raise ModelError(
                "Meta request timed out; no fallback was attempted"
            ) from None
        except httpx.HTTPError:
            raise ModelError(
                "Meta connection failed; no fallback was attempted"
            ) from None

    async def close(self) -> None:
        await self._client.aclose()


def _check_status(status: int) -> None:
    errors = {
        401: "Meta authentication failed; check META_AI_KEY",
        403: "Meta access denied; check account and model permissions",
        404: "Selected Meta model is unavailable",
        429: "Meta request limit reached; retry later",
    }
    if status != 200:
        raise ModelError(errors.get(status, "Meta rejected the request"))
