"""Tests for the deterministic scripted model provider."""

from uuid import uuid4

import pytest

from agent_core import (
    ModelMessage,
    ModelMetrics,
    ModelRole,
    StructuredModelRequest,
    StructuredModelResult,
)
from shared_testkit import ScriptedLLMProvider


def _request() -> StructuredModelRequest:
    return StructuredModelRequest(
        run_id=uuid4(),
        role=ModelRole.PLANNER,
        model_profile="test.v1",
        messages=(ModelMessage(role="user", content="plan"),),
        output_schema={"type": "object"},
        prompt_id="planner",
        prompt_version="v1",
        prompt_hash="a" * 64,
        rendered_input_hash="b" * 64,
    )


def test_scripted_provider_records_requests_and_returns_metadata() -> None:
    expected = StructuredModelResult(
        content={"ok": True},
        provider="scripted",
        model="fake",
        metrics=ModelMetrics(total_duration_ms=1),
    )
    provider = ScriptedLLMProvider([expected])

    assert provider.generate_structured(_request()) == expected
    assert len(provider.requests) == 1
    assert provider.health().reachable is True


def test_scripted_provider_raises_scripted_and_unscripted_failures() -> None:
    provider = ScriptedLLMProvider([RuntimeError("offline")])

    with pytest.raises(RuntimeError, match="offline"):
        provider.generate_structured(_request())
    with pytest.raises(AssertionError, match="unexpected invocation"):
        provider.generate_structured(_request())
