"""Contract tests for the OpenAI Responses API adapter."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest

from agent_core import ModelMessage, ModelProviderError, ModelRole, StructuredModelRequest
from ai_mode.adapters.openai import OpenAIModelProfile, OpenAIProvider
from shared_contracts import ModelReasoningEffort


def _request(
    profile: str = "remote-standard.v1",
    *,
    role: ModelRole = ModelRole.PLANNER,
    deadline_at: datetime | None = None,
) -> StructuredModelRequest:
    return StructuredModelRequest(
        run_id=uuid4(),
        role=role,
        model_profile=profile,
        messages=(
            ModelMessage(role="system", content="Return JSON."),
            ModelMessage(role="user", content="Confirm readiness."),
        ),
        output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        prompt_id="planner",
        prompt_version="v1",
        prompt_hash="a" * 64,
        rendered_input_hash="b" * 64,
        max_output_tokens=128,
        deadline_at=deadline_at,
    )


def _success_body(*, text: str = '{"ok":true}') -> dict[str, object]:
    return {
        "id": "resp_test",
        "status": "completed",
        "model": "gpt-5.6-luna",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": text}],
            }
        ],
        "usage": {
            "input_tokens": 20,
            "output_tokens": 7,
            "input_tokens_details": {"cached_tokens": 5},
            "output_tokens_details": {"reasoning_tokens": 3},
        },
    }


def _provider(
    handler: httpx.MockTransport,
    *,
    api_key: str | None = "test-key",
    max_retries: int = 0,
    sleeper: Callable[[float], None] | None = None,
) -> OpenAIProvider:
    client = httpx.Client(base_url="https://api.openai.test/v1", transport=handler)
    provider_options = {} if sleeper is None else {"sleeper": sleeper}
    return OpenAIProvider(
        api_key=api_key,
        base_url="https://ignored.test/v1",
        profiles={
            "remote-standard.v1": OpenAIModelProfile(
                models={ModelRole.PLANNER: "gpt-5.6-luna"},
                reasoning_effort=ModelReasoningEffort.LOW,
            )
        },
        timeout_seconds=5,
        max_retries=max_retries,
        max_response_bytes=100_000,
        client=client,
        **provider_options,
    )


def test_responses_payload_auth_and_metrics_are_provider_native() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        captured["authorization"] = request.headers.get("authorization")
        captured["client_request_id"] = request.headers.get("x-client-request-id")
        return httpx.Response(200, json=_success_body())

    result = _provider(httpx.MockTransport(handler)).generate_structured(_request())

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert payload["model"] == "gpt-5.6-luna"
    assert payload["instructions"] == "Return JSON."
    assert payload["input"] == [{"role": "user", "content": "Confirm readiness."}]
    assert payload["reasoning"] == {"effort": "low"}
    assert payload["store"] is False
    assert payload["text"]["format"] == {
        "type": "json_schema",
        "name": "planner_planner_v1",
        "schema": _request().output_schema,
        "strict": False,
    }
    assert "temperature" not in payload
    assert captured["authorization"] == "Bearer test-key"
    assert isinstance(captured["client_request_id"], str)
    assert result.content == {"ok": True}
    assert result.provider == "openai"
    assert result.metrics.prompt_tokens == 20
    assert result.metrics.output_tokens == 7
    assert result.metrics.cached_prompt_tokens == 5
    assert result.metrics.reasoning_tokens == 3


def test_profile_routes_implementer_and_reviewer_roles_to_distinct_models() -> None:
    requested_models: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requested_models.append(payload["model"])
        return httpx.Response(200, json=_success_body())

    provider = OpenAIProvider(
        api_key="test-key",
        base_url="https://ignored.test/v1",
        profiles={
            "remote-standard.v1": OpenAIModelProfile(
                models={
                    ModelRole.PLANNER: "gpt-5.6-luna",
                    ModelRole.ADAPTER: "gpt-5.6-terra",
                    ModelRole.REVIEWER: "gpt-5.6-terra",
                },
                maximum_output_tokens=2_048,
            )
        },
        timeout_seconds=5,
        max_retries=0,
        max_response_bytes=100_000,
        client=httpx.Client(
            base_url="https://api.openai.test/v1",
            transport=httpx.MockTransport(handler),
        ),
    )

    provider.generate_structured(_request(role=ModelRole.PLANNER))
    provider.generate_structured(_request(role=ModelRole.ADAPTER))
    provider.generate_structured(_request(role=ModelRole.REVIEWER))

    assert requested_models == ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-terra"]


def test_none_reasoning_preserves_requested_temperature() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_success_body())

    provider = OpenAIProvider(
        api_key="test-key",
        base_url="https://ignored.test/v1",
        profiles={
            "remote-standard.v1": OpenAIModelProfile(
                models={ModelRole.PLANNER: "gpt-5.6-luna"},
                reasoning_effort=ModelReasoningEffort.NONE,
            )
        },
        timeout_seconds=5,
        max_retries=0,
        max_response_bytes=100_000,
        client=httpx.Client(
            base_url="https://api.openai.test/v1",
            transport=httpx.MockTransport(handler),
        ),
    )

    provider.generate_structured(_request())

    assert captured["temperature"] == 0


def test_missing_credentials_fail_without_network_or_secret_repr() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    provider = _provider(httpx.MockTransport(handler), api_key=None)

    with pytest.raises(ModelProviderError) as raised:
        provider.generate_structured(_request())

    assert raised.value.code == "model_credentials_missing"
    assert provider.health().reachable is False
    assert calls == 0


def test_unknown_profile_role_and_output_limit_fail_before_network() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    provider = OpenAIProvider(
        api_key="test-key",
        base_url="https://ignored.test/v1",
        profiles={
            "remote-standard.v1": OpenAIModelProfile(
                models={ModelRole.PLANNER: "gpt-5.6-luna"},
                maximum_output_tokens=64,
            )
        },
        timeout_seconds=5,
        max_retries=0,
        max_response_bytes=100_000,
        client=httpx.Client(
            base_url="https://api.openai.test/v1",
            transport=httpx.MockTransport(handler),
        ),
    )

    with pytest.raises(ModelProviderError) as unknown:
        provider.generate_structured(_request("unknown.v1"))
    with pytest.raises(ModelProviderError) as role:
        provider.generate_structured(_request(role=ModelRole.REVIEWER))
    with pytest.raises(ModelProviderError) as output:
        provider.generate_structured(_request())

    assert unknown.value.code == "model_profile_not_found"
    assert role.value.code == "model_role_not_supported"
    assert output.value.code == "model_output_limit_exceeded"
    assert calls == 0


def test_timeout_and_deadline_failures_are_typed() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(ModelProviderError) as transport:
        _provider(httpx.MockTransport(timeout)).generate_structured(_request())
    assert transport.value.code == "model_timeout"
    assert transport.value.retryable is True

    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    with pytest.raises(ModelProviderError) as deadline:
        _provider(httpx.MockTransport(handler)).generate_structured(
            _request(deadline_at=datetime.now(UTC) - timedelta(seconds=1))
        )
    assert deadline.value.code == "model_timeout"
    assert calls == 0


def test_generation_timeout_is_capped_by_run_deadline() -> None:
    captured_timeout: object = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_timeout
        captured_timeout = request.extensions["timeout"]
        return httpx.Response(200, json=_success_body())

    deadline = datetime.now(UTC) + timedelta(seconds=1)
    _provider(httpx.MockTransport(handler)).generate_structured(_request(deadline_at=deadline))

    assert isinstance(captured_timeout, dict)
    assert 0 < captured_timeout["read"] <= 1


def test_retryable_responses_use_bounded_retry_after_and_one_correlation_id() -> None:
    calls = 0
    client_request_ids: list[str | None] = []
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        client_request_ids.append(request.headers.get("x-client-request-id"))
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "1.5"})
        return httpx.Response(200, json=_success_body())

    result = _provider(
        httpx.MockTransport(handler),
        max_retries=1,
        sleeper=delays.append,
    ).generate_structured(_request())

    assert result.content == {"ok": True}
    assert calls == 2
    assert delays == [1.5]
    assert len(set(client_request_ids)) == 1


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (401, "model_authentication_failed", False),
        (404, "model_not_found", False),
        (503, "model_overloaded", True),
        (400, "model_request_rejected", False),
    ],
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

    provider = OpenAIProvider(
        api_key="test-key",
        base_url="https://ignored.test/v1",
        profiles={
            "remote-standard.v1": OpenAIModelProfile(models={ModelRole.PLANNER: "gpt-5.6-luna"})
        },
        timeout_seconds=1,
        max_retries=0,
        max_response_bytes=10,
        client=httpx.Client(
            base_url="https://api.openai.test/v1",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    content=b"x" * 100,
                    headers={"content-type": "application/json"},
                )
            ),
        ),
    )
    with pytest.raises(ModelProviderError) as size_error:
        provider.generate_structured(_request())
    assert size_error.value.code == "model_response_too_large"


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ([], "invalid_model_response"),
        ({"status": "completed", "model": "gpt-5.6-luna"}, "invalid_model_response"),
        (
            {
                "status": "incomplete",
                "model": "gpt-5.6-luna",
                "output": [],
                "incomplete_details": {"reason": "max_output_tokens"},
            },
            "model_response_incomplete",
        ),
        (
            {
                "status": "completed",
                "model": "gpt-5.6-luna",
                "output": [{"type": "message", "content": [{"type": "refusal", "refusal": "no"}]}],
            },
            "model_refused",
        ),
    ],
)
def test_invalid_or_refused_success_responses_are_rejected(body: object, code: str) -> None:
    provider = _provider(httpx.MockTransport(lambda request: httpx.Response(200, json=body)))

    with pytest.raises(ModelProviderError) as raised:
        provider.generate_structured(_request())

    assert raised.value.code == code


def test_malformed_model_text_is_returned_for_bounded_repair() -> None:
    provider = _provider(
        httpx.MockTransport(lambda request: httpx.Response(200, json=_success_body(text="no")))
    )

    assert provider.generate_structured(_request()).content == {"invalid_model_output": "no"}


def test_health_checks_only_selected_models_with_short_timeout() -> None:
    requested_paths: list[str] = []
    captured_timeout: object = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_timeout
        requested_paths.append(request.url.path)
        captured_timeout = request.extensions["timeout"]
        model = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"id": model, "object": "model"})

    provider = OpenAIProvider(
        api_key="test-key",
        base_url="https://ignored.test/v1",
        profiles={
            "remote-standard.v1": OpenAIModelProfile(
                models={
                    ModelRole.PLANNER: "gpt-5.6-luna",
                    ModelRole.REVIEWER: "gpt-5.6-terra",
                }
            ),
            "remote-other.v1": OpenAIModelProfile(models={ModelRole.PLANNER: "gpt-5.6-sol"}),
        },
        readiness_profiles=frozenset({"remote-standard.v1"}),
        timeout_seconds=5,
        health_timeout_seconds=1.25,
        max_response_bytes=100_000,
        client=httpx.Client(
            base_url="https://api.openai.test/v1",
            transport=httpx.MockTransport(handler),
        ),
    )

    assert provider.health().reachable is True
    assert requested_paths == ["/v1/models/gpt-5.6-luna", "/v1/models/gpt-5.6-terra"]
    assert isinstance(captured_timeout, dict)
    assert captured_timeout["read"] == 1.25


@pytest.mark.parametrize("status", [401, 404, 429])
def test_health_contains_auth_model_and_rate_failures(status: int) -> None:
    provider = _provider(httpx.MockTransport(lambda request: httpx.Response(status)))

    assert provider.health().reachable is False
