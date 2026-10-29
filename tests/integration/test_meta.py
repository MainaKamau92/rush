import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.errors import ModelError
from app.internal.adapters.meta import MetaModelProvider


def response_body(**changes: Any) -> dict[str, Any]:
    return {
        "status": "completed",
        "model": "muse-spark-1.3",
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "RUSH_OK"}],
            },
        ],
        **changes,
    }


def provider_with(
    handler: Callable[[httpx.Request], httpx.Response],
) -> MetaModelProvider:
    return MetaModelProvider(
        httpx.AsyncClient(
            base_url="https://api.meta.ai/v1/",
            headers={"Authorization": "Bearer fixture-token"},
            follow_redirects=False,
            transport=httpx.MockTransport(handler),
        )
    )


@pytest.mark.parametrize("model", ["bad/model", "muse-spark-1.3-contributor"])
async def test_meta_rejects_invalid_ids_and_unapproved_data_mode_before_sending(
    model: str,
) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_body())

    provider = provider_with(handle)
    with pytest.raises(ModelError):
        await provider.generate(model, "Reply with RUSH_OK.", 128)
    await provider.close()
    assert requests == []


async def test_meta_request_and_response_mapping_preserves_privacy_and_usage() -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=response_body(
                usage={
                    "input_tokens": 10,
                    "output_tokens": 4,
                    "total_tokens": 14,
                }
            ),
            headers={
                "x-ratelimit-limit-tokens": "4000000",
                "x-ratelimit-remaining-tokens": "private-invalid-value",
                "x-request-id": "private-request-id",
            },
        )

    provider = provider_with(handle)
    reply = await provider.generate("muse-spark-1.3", "Reply with RUSH_OK.", 128)
    await provider.close()
    (request,) = requests
    assert str(request.url) == "https://api.meta.ai/v1/responses"
    assert request.headers["Authorization"] == "Bearer fixture-token"
    assert json.loads(request.content) == {
        "model": "muse-spark-1.3",
        "input": "Reply with RUSH_OK.",
        "max_output_tokens": 128,
        "reasoning": {"effort": "minimal"},
        "store": False,
    }
    assert reply.provider == "meta" and reply.text == "RUSH_OK"
    assert reply.usage is not None and reply.usage.total_tokens == 14
    assert reply.rate_limits == {"x-ratelimit-limit-tokens": 4000000}


@pytest.mark.parametrize(
    ("status", "message"),
    [
        (401, "authentication"),
        (403, "denied"),
        (404, "unavailable"),
        (429, "limit"),
        (503, "rejected"),
        (302, "rejected"),
    ],
)
async def test_http_failures_are_safe_and_never_follow_redirects_or_retry(
    status: int, message: str
) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            status,
            text="private-provider-error",
            headers={
                "Location": "https://another-provider.example/responses",
            },
        )

    provider = provider_with(handle)
    with pytest.raises(ModelError, match=message) as error:
        await provider.generate("muse-spark-1.3", "Reply with RUSH_OK.", 128)
    await provider.close()
    assert "private-provider-error" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        "not JSON",
        "{}",
        json.dumps(response_body(status="incomplete")),
        json.dumps(response_body(usage={"input_tokens": -1})),
    ],
)
async def test_invalid_or_incomplete_responses_fail_without_exposing_raw_output(
    body: str,
) -> None:
    provider = provider_with(lambda request: httpx.Response(200, text=body))
    with pytest.raises(ModelError, match="invalid or incomplete"):
        await provider.generate("muse-spark-1.3", "Reply with RUSH_OK.", 128)
    await provider.close()


@pytest.mark.parametrize("kind", ["timeout", "connection", "cancellation"])
async def test_transport_failures_and_cancellation_do_not_retry(kind: str) -> None:
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("private-timeout")
        if kind == "connection":
            raise httpx.ConnectError("private-connection")
        raise asyncio.CancelledError

    provider = provider_with(handle)
    error = asyncio.CancelledError if kind == "cancellation" else ModelError
    with pytest.raises(error):
        await provider.generate("muse-spark-1.3", "Reply with RUSH_OK.", 128)
    await provider.close()
    assert len(requests) == 1
