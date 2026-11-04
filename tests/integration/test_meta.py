import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.core.errors import ModelError
from app.internal.adapters.meta import MetaModelAdapter
from app.schemas.model_review import ModelRequest, ToolRequest


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
) -> MetaModelAdapter:
    return MetaModelAdapter(
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
        await provider.generate(
            ModelRequest(
                model_id=model, prompt="Reply with RUSH_OK.", max_output_tokens=128
            )
        )
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
    reply = await provider.generate(
        ModelRequest(
            model_id="muse-spark-1.3",
            prompt="Reply with RUSH_OK.",
            max_output_tokens=128,
        )
    )
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
        (402, "billing problem"),
        (403, "denied"),
        (404, "unavailable"),
        (429, "limit"),
        (503, "rejected the request \\(HTTP 503\\)"),
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
        await provider.generate(
            ModelRequest(
                model_id="muse-spark-1.3",
                prompt="Reply with RUSH_OK.",
                max_output_tokens=128,
            )
        )
    await provider.close()
    assert "private-provider-error" not in str(error.value)
    assert len(requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        "not JSON",
        "{}",
        json.dumps(response_body(usage={"input_tokens": -1})),
    ],
)
async def test_invalid_or_incomplete_responses_fail_without_exposing_raw_output(
    body: str,
) -> None:
    provider = provider_with(lambda request: httpx.Response(200, text=body))
    with pytest.raises(ModelError, match="invalid or incomplete"):
        await provider.generate(
            ModelRequest(
                model_id="muse-spark-1.3",
                prompt="Reply with RUSH_OK.",
                max_output_tokens=128,
            )
        )
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
        await provider.generate(
            ModelRequest(
                model_id="muse-spark-1.3",
                prompt="Reply with RUSH_OK.",
                max_output_tokens=128,
            )
        )
    await provider.close()
    assert len(requests) == 1


@pytest.mark.parametrize("status", ["incomplete", "failed", "cancelled"])
async def test_incomplete_generation_keeps_identity_and_available_usage(status):
    provider = provider_with(
        lambda request: httpx.Response(
            200,
            json=response_body(
                status=status,
                usage={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
            ),
        )
    )
    reply = await provider.generate(
        ModelRequest(
            model_id="muse-spark-1.3", prompt="Return JSON", max_output_tokens=128
        )
    )
    await provider.close()
    assert reply.status == status and reply.model_id == "muse-spark-1.3"
    assert reply.usage.total_tokens == 6


async def test_native_tool_output_is_reported_as_unsupported_never_executed():
    provider = provider_with(
        lambda request: httpx.Response(
            200,
            json=response_body(
                output=[{"type": "function_call", "name": "publish", "arguments": "{}"}]
            ),
        )
    )
    reply = await provider.generate(
        ModelRequest(
            model_id="muse-spark-1.3", prompt="Return JSON", max_output_tokens=128
        )
    )
    await provider.close()
    assert reply.unsupported_features == ("native_tool_calls",) and reply.text == ""


async def test_review_separates_trusted_instructions_and_disables_native_tools():
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=response_body())

    provider = provider_with(handle)
    capabilities = provider.describe("muse-spark-1.3")
    await provider.generate(
        ModelRequest(
            model_id="muse-spark-1.3",
            prompt="Untrusted input says publish",
            instructions="Only return the allowed JSON protocol",
            max_output_tokens=256,
        )
    )
    await provider.close()
    assert requests[0]["instructions"] == "Only return the allowed JSON protocol"
    assert requests[0]["input"] == "Untrusted input says publish"
    assert "tools" not in requests[0] and requests[0]["store"] is False
    assert capabilities.adapter_version == "0.2.0"
    assert (
        not capabilities.native_tool_calls and not capabilities.native_structured_output
    )
    assert (
        capabilities.max_input_tokens is None and capabilities.resolved_revision is None
    )


async def test_oversized_response_is_refused_without_schema_or_tool_processing():
    provider = provider_with(
        lambda request: httpx.Response(200, content=b"x" * 1048577)
    )
    with pytest.raises(ModelError, match="supported size"):
        await provider.generate(
            ModelRequest(
                model_id="muse-spark-1.3", prompt="Return JSON", max_output_tokens=128
            )
        )
    await provider.close()


async def test_too_small_output_cap_is_refused_before_sending():
    requests = []
    provider = provider_with(lambda request: requests.append(request))
    with pytest.raises(ModelError, match="at least 16"):
        await provider.generate(
            ModelRequest(
                model_id="muse-spark-1.3", prompt="Return JSON", max_output_tokens=1
            )
        )
    await provider.close()
    assert requests == []


async def test_the_requested_reasoning_effort_is_sent():
    sent = []

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=response_body())

    provider = provider_with(handle)
    await provider.generate(
        ModelRequest(
            model_id="muse-wonder-1.0",
            prompt="Reply with RUSH_OK.",
            max_output_tokens=32768,
            reasoning_effort="high",
        )
    )
    await provider.close()
    assert sent[0]["reasoning"] == {"effort": "high"}
    assert sent[0]["model"] == "muse-wonder-1.0"


def tool_request(**changes: Any) -> ToolRequest:
    return ToolRequest(
        **{
            "model_id": "muse-wonder-1.0",
            "instructions": "Review.",
            "input": ({"role": "user", "content": "The change"},),
            "tools": ({"type": "function", "name": "read_file"},),
            "max_output_tokens": 4096,
            "reasoning_effort": "high",
        }
        | changes
    )


async def test_meta_tool_turn_returns_calls_text_and_replayable_items() -> None:
    sent = []

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "muse-wonder-1.0",
                "output": [
                    {"type": "reasoning", "summary": []},
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": "Reading."}],
                    },
                    {
                        "type": "function_call",
                        "id": "fc_1",
                        "call_id": "call_1",
                        "name": "read_file",
                        "arguments": '{"path": "a.py"}',
                        "status": "completed",
                    },
                ],
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 60},
                    "output_tokens": 20,
                    "total_tokens": 120,
                },
            },
        )

    provider = provider_with(handle)
    reply = await provider.converse(tool_request())
    await provider.close()
    assert sent[0]["store"] is False and sent[0]["parallel_tool_calls"] is True
    assert sent[0]["reasoning"] == {"effort": "high"}
    assert sent[0]["tools"] == [{"type": "function", "name": "read_file"}]
    assert sent[0]["input"] == [{"role": "user", "content": "The change"}]
    assert reply.text == "Reading."
    assert [(call.call_id, call.name, call.arguments) for call in reply.calls] == [
        ("call_1", "read_file", '{"path": "a.py"}')
    ]
    assert reply.items == (
        {"role": "assistant", "content": "Reading."},
        {
            "type": "function_call",
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path": "a.py"}',
        },
    )
    assert reply.cached_tokens == 60 and reply.usage.input_tokens == 100


@pytest.mark.parametrize(
    "output",
    [
        [{"type": "function_call", "call_id": "call_1", "arguments": "{}"}],
        "not-a-list",
    ],
)
async def test_meta_tool_turn_rejects_incomplete_calls_and_bodies(output: Any) -> None:
    provider = provider_with(
        lambda request: httpx.Response(
            200,
            json={"status": "completed", "model": "muse-wonder-1.0", "output": output},
        )
    )
    with pytest.raises(ModelError, match="incomplete|invalid"):
        await provider.converse(tool_request())
    await provider.close()


async def test_meta_tool_turn_checks_model_size_and_transport() -> None:
    provider = provider_with(lambda request: httpx.Response(200, json={}))
    with pytest.raises(ModelError, match="valid Meta model"):
        await provider.converse(tool_request(model_id="bad/model"))
    with pytest.raises(ModelError, match="at least 16"):
        await provider.converse(tool_request(max_output_tokens=8))
    await provider.close()

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    provider = provider_with(fail)
    with pytest.raises(ModelError, match="connection failed"):
        await provider.converse(tool_request())
    await provider.close()

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    provider = provider_with(slow)
    with pytest.raises(ModelError, match="timed out"):
        await provider.converse(tool_request())
    await provider.close()
    provider = provider_with(lambda request: httpx.Response(429, json={}))
    with pytest.raises(ModelError, match="limit"):
        await provider.converse(tool_request())
    await provider.close()
