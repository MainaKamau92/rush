import re
from typing import Annotated, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.core.errors import ModelError
from app.models.model_access import ModelReply, TokenUsage


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
    status: Literal["completed"]
    model: Annotated[str, Field(min_length=1)]
    output: list[_Output]
    usage: _Usage | None = None


def _parse_reply(response: httpx.Response) -> ModelReply:
    try:
        data = _Response.model_validate_json(response.content)
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
        value = response.headers.get(name, "")
        if value.isascii() and value.isdigit():
            rates[name] = int(value)
    return ModelReply("meta", data.model, text, usage, rates)


class MetaModelProvider:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def generate(
        self, model_id: str, prompt: str, max_output_tokens: int
    ) -> ModelReply:
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,127}", model_id):
            raise ModelError("Specify a valid Meta model ID")
        if "contributor" in model_id:
            raise ModelError("Contributor mode is not enabled; select a Standard model")
        try:
            response = await self._client.post(
                "responses",
                json={
                    "model": model_id,
                    "input": prompt,
                    "max_output_tokens": max_output_tokens,
                    "reasoning": {"effort": "minimal"},
                    "store": False,
                },
            )
        except httpx.TimeoutException:
            raise ModelError(
                "Meta request timed out; no fallback was attempted"
            ) from None
        except httpx.HTTPError:
            raise ModelError(
                "Meta connection failed; no fallback was attempted"
            ) from None
        errors = {
            401: "Meta authentication failed; check META_AI_KEY",
            403: "Meta access denied; check account and model permissions",
            404: "Selected Meta model is unavailable",
            429: "Meta request limit reached; retry later",
        }
        if response.status_code != 200:
            raise ModelError(
                errors.get(response.status_code, "Meta rejected the request")
            )
        return _parse_reply(response)

    async def close(self) -> None:
        await self._client.aclose()
