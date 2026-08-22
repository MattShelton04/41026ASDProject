from __future__ import annotations

import uuid

import httpx

from propertyscope_data_platform.approval import approved_tool_call
from propertyscope_data_platform.clients import AiModeClient


def test_approval_requires_exact_run_tool_and_arguments() -> None:
    run_id = uuid.uuid4()
    observed: list[httpx.Request] = []

    def ai_mode(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        return httpx.Response(
            200,
            json={
                "reviews": [
                    "invalid review",
                    {
                        "decision": "approve",
                        "tool_call": {
                            "tool_name": "data.run_retry.v1",
                            "arguments": {"run_id": "source-run", "idempotency_key": "retry-1"},
                        },
                    },
                ]
            },
        )

    with httpx.Client(transport=httpx.MockTransport(ai_mode)) as client:
        ai_client = AiModeClient("http://ai", client=client)
        headers = {"X-Agent-Run-ID": str(run_id), "X-Request-ID": "request-1"}
        assert approved_tool_call(
            ai_client,
            headers,
            "data.run_retry.v1",
            {"run_id": "source-run", "idempotency_key": "retry-1"},
        )
        assert not approved_tool_call(
            ai_client,
            headers,
            "data.run_retry.v1",
            {"run_id": "different", "idempotency_key": "retry-1"},
        )

    assert observed[0].url.path == f"/api/v1/agent-runs/{run_id}"
    assert observed[0].headers["X-Request-ID"] == "request-1"


def test_approval_fails_closed_before_network_for_invalid_run_id() -> None:
    def unexpected(_: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid approval identity must not call AI-mode")

    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        ai_client = AiModeClient("http://ai", client=client)
        assert not approved_tool_call(
            ai_client,
            {"X-Agent-Run-ID": "not-a-uuid"},
            "data.run_retry.v1",
            {},
        )
