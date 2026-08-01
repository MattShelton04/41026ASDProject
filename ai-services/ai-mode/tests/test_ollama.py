"""Contract tests for the native Ollama structured-output adapter."""

from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from agent_core import ModelMessage, ModelProviderError, ModelRole, StructuredModelRequest
from ai_mode.adapters.ollama import OllamaModelProfile, OllamaProvider


def _request(profile: str = "local-small.v1") -> StructuredModelRequest:
    return StructuredModelRequest(
        run_id=uuid4(),
        role=ModelRole.PLANNER,
        model_profile=profile,
        messages=(ModelMessage(role="system", content="Return JSON."),),
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        prompt_id="planner",
        prompt_version="v1",
        prompt_hash="a" * 64,
        rendered_input_hash="b" * 64,
        max_output_tokens=128,
    )


def _provider(handler: httpx.MockTransport) -> OllamaProvider:
    client = httpx.Client(base_url="http://ollama.test", transport=handler)
    return OllamaProvider(
        base_url="http://ignored.test",
        profiles={"local-small.v1": OllamaModelProfile(model="qwen2.5:0.5b")},
        timeout_seconds=5,
        max_response_bytes=100_000,
        client=client,
    )


def test_structured_chat_payload_and_metrics_use_native_api() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "model": "qwen2.5:0.5b",
                "message": {"role": "assistant", "content": '{"ok":true}'},
                "total_duration": 12_000_000,
                "load_duration": 2_000_000,
                "prompt_eval_duration": 3_000_000,
                "eval_duration": 7_000_000,
                "prompt_eval_count": 20,
                "eval_count": 4,
            },
        )

    result = _provider(httpx.MockTransport(handler)).generate_structured(_request())

    assert captured["stream"] is False
    assert captured["format"] == _request().output_schema
    assert captured["keep_alive"] == "5m"
    assert result.content == {"ok": True}
    assert result.metrics.total_duration_ms == 12
    assert result.metrics.prompt_tokens == 20


def test_malformed_model_content_is_returned_as_invalid_structured_data_for_repair() -> None:
    provider = _provider(
        httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={"model": "qwen", "message": {"content": "not json"}},
            )
        )
    )

    result = provider.generate_structured(_request())

    assert result.content == {"invalid_model_output": "not json"}


def test_unknown_profile_fails_without_network_io() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    provider = _provider(httpx.MockTransport(handler))

    with pytest.raises(ModelProviderError) as raised:
        provider.generate_structured(_request("unknown.v1"))

    assert raised.value.code == "model_profile_not_found"
    assert raised.value.retryable is False
    assert calls == 0


def test_transport_timeout_is_typed_and_retryable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ModelProviderError) as raised:
        _provider(httpx.MockTransport(handler)).generate_structured(_request())

    assert raised.value.code == "model_timeout"
    assert raised.value.retryable is True


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [(503, "model_overloaded", True), (400, "model_request_rejected", False)],
)
def test_http_failures_are_safely_classified(status: int, code: str, retryable: bool) -> None:
    provider = _provider(
        httpx.MockTransport(lambda request: httpx.Response(status, request=request))
    )

    with pytest.raises(ModelProviderError) as raised:
        provider.generate_structured(_request())

    assert raised.value.code == code
    assert raised.value.retryable is retryable


def test_network_failure_and_oversized_response_are_typed() -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    with pytest.raises(ModelProviderError) as network_error:
        _provider(httpx.MockTransport(offline)).generate_structured(_request())
    assert network_error.value.code == "model_unavailable"

    client = httpx.Client(
        base_url="http://ollama.test",
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                content=b"x" * 100,
                headers={"content-type": "application/json"},
            )
        ),
    )
    provider = OllamaProvider(
        base_url="http://ignored",
        profiles={"local-small.v1": OllamaModelProfile(model="qwen")},
        timeout_seconds=1,
        max_response_bytes=10,
        client=client,
    )
    with pytest.raises(ModelProviderError) as size_error:
        provider.generate_structured(_request())
    assert size_error.value.code == "model_response_too_large"


@pytest.mark.parametrize(
    "body",
    [[], {"model": "qwen"}, {"message": {"content": "[]"}}],
)
def test_invalid_success_responses_are_rejected_or_marked_invalid(body: object) -> None:
    provider = _provider(httpx.MockTransport(lambda request: httpx.Response(200, json=body)))

    if body == {"message": {"content": "[]"}}:
        assert "invalid_model_output" in provider.generate_structured(_request()).content
    else:
        with pytest.raises(ModelProviderError, match=r"Ollama returned|omitted"):
            provider.generate_structured(_request())


@pytest.mark.parametrize(
    ("models", "reachable"),
    [([{"name": "qwen2.5:0.5b"}], True), ([], False)],
)
def test_health_includes_configured_model_availability(
    models: list[dict[str, str]], reachable: bool
) -> None:
    provider = _provider(
        httpx.MockTransport(lambda request: httpx.Response(200, json={"models": models}))
    )

    assert provider.health().reachable is reachable


def test_health_uses_its_short_independent_timeout() -> None:
    captured_timeout = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_timeout
        captured_timeout = request.extensions["timeout"]
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:0.5b"}]})

    provider = _provider(httpx.MockTransport(handler))

    assert provider.health().reachable is True
    assert isinstance(captured_timeout, dict)
    assert captured_timeout["read"] == 2.0


def test_health_contains_invalid_or_failed_responses() -> None:
    invalid = _provider(httpx.MockTransport(lambda request: httpx.Response(200, json=[])))
    failed = _provider(httpx.MockTransport(lambda request: httpx.Response(503)))

    assert invalid.health().reachable is False
    assert failed.health().reachable is False
