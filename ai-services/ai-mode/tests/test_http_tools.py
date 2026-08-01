"""Contract tests for the allowlisted feature HTTP tool adapter."""

from uuid import uuid4

import httpx
import pytest

from ai_mode.adapters.http_tools import HttpToolBinding, HttpToolExecutor
from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    IDEMPOTENCY_KEY_HEADER,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    ApprovalStatus,
    SideEffectClass,
    ToolCall,
    ToolDefinition,
    ToolOutcome,
)

TRACEPARENT = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"


def _definition() -> ToolDefinition:
    return ToolDefinition(
        name="reference.records.search.v1",
        version="v1",
        feature_key="student-1-reference",
        description="Search reference records",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 0}},
            "required": ["count"],
            "additionalProperties": False,
        },
        side_effect=SideEffectClass.READ_ONLY,
    )


def _call(*, idempotency_key: str | None = None) -> ToolCall:
    return ToolCall(
        id=uuid4(),
        run_id=uuid4(),
        step_id=uuid4(),
        request_id="request-123",
        traceparent=TRACEPARENT,
        tool_name="reference.records.search.v1",
        tool_version="v1",
        arguments={"query": "Reference"},
        idempotency_key=idempotency_key,
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )


def _executor(handler: httpx.MockTransport, **limits: int) -> HttpToolExecutor:
    return HttpToolExecutor(
        service_base_urls={"reference-backend": "http://reference.internal:5101"},
        bindings=[
            HttpToolBinding(
                tool_name="reference.records.search.v1",
                tool_version="v1",
                service="reference-backend",
                method="POST",
                path="/api/v1/tools/records.search.v1",
            )
        ],
        client=httpx.Client(transport=handler, follow_redirects=False),
        **limits,
    )


def test_success_propagates_correlation_and_idempotency_headers() -> None:
    call = _call(idempotency_key="stable-key")

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://reference.internal:5101/api/v1/tools/records.search.v1"
        assert request.headers[REQUEST_ID_HEADER] == call.request_id
        assert request.headers[AGENT_RUN_ID_HEADER] == str(call.run_id)
        assert request.headers[TRACEPARENT_HEADER] == TRACEPARENT
        assert request.headers[IDEMPOTENCY_KEY_HEADER] == "stable-key"
        assert request.content == b'{"query":"Reference"}'
        return httpx.Response(200, json={"count": 1})

    result = _executor(httpx.MockTransport(respond)).execute(call, _definition(), timeout_ms=1_000)

    assert result.outcome is ToolOutcome.SUCCEEDED
    assert result.content == {"count": 1}
    assert result.evidence_references == ("service:reference-backend", "status:200")


@pytest.mark.parametrize(
    ("status", "code", "retryable"),
    [
        (400, "tool_request_rejected", False),
        (409, "tool_conflict", False),
        (503, "tool_unavailable", True),
    ],
)
def test_http_failures_are_mapped_without_response_body_leakage(
    status: int,
    code: str,
    retryable: bool,
) -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(status, json={"secret": "must-not-leak"})
    )

    result = _executor(transport).execute(_call(), _definition(), timeout_ms=1_000)

    assert result.error is not None
    assert result.error.code == code
    assert "must-not-leak" not in result.error.message
    assert result.retryable is retryable


def test_timeout_and_redirect_fail_closed() -> None:
    def time_out(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("private timeout detail", request=request)

    timed_out = _executor(httpx.MockTransport(time_out)).execute(
        _call(), _definition(), timeout_ms=10
    )
    redirected = _executor(
        httpx.MockTransport(
            lambda request: httpx.Response(302, headers={"Location": "http://evil"})
        )
    ).execute(_call(), _definition(), timeout_ms=1_000)

    assert timed_out.outcome is ToolOutcome.TIMED_OUT
    assert timed_out.error is not None and timed_out.error.code == "tool_timeout"
    assert redirected.error is not None and redirected.error.code == "tool_redirect_rejected"


@pytest.mark.parametrize(
    ("response", "code"),
    [
        (httpx.Response(200, text="not-json"), "tool_media_type_invalid"),
        (httpx.Response(200, json={"count": -1}), "invalid_tool_output"),
        (
            httpx.Response(200, content=b"{}", headers={"content-type": "application/json"}),
            "invalid_tool_output",
        ),
    ],
)
def test_invalid_responses_fail_at_the_adapter_boundary(
    response: httpx.Response,
    code: str,
) -> None:
    result = _executor(httpx.MockTransport(lambda request: response)).execute(
        _call(), _definition(), timeout_ms=1_000
    )

    assert result.error is not None
    assert result.error.code == code


def test_request_and_response_size_limits_are_enforced() -> None:
    request_limited = _executor(
        httpx.MockTransport(lambda request: httpx.Response(200, json={"count": 1})),
        max_request_bytes=5,
    ).execute(_call(), _definition(), timeout_ms=1_000)
    response_limited = _executor(
        httpx.MockTransport(lambda request: httpx.Response(200, json={"count": 1000})),
        max_response_bytes=5,
    ).execute(_call(), _definition(), timeout_ms=1_000)

    assert request_limited.error is not None
    assert request_limited.error.code == "tool_request_too_large"
    assert response_limited.error is not None
    assert response_limited.error.code == "tool_response_too_large"


@pytest.mark.parametrize(
    "base_url",
    ["file:///tmp", "http://user:pass@internal", "http://internal/base", "//internal"],
)
def test_unsafe_service_origins_are_rejected_at_startup(base_url: str) -> None:
    with pytest.raises(ValueError, match="fixed HTTP"):
        HttpToolExecutor(service_base_urls={"service": base_url}, bindings=[])
