"""Tests for bounded structured-output validation and repair."""

from uuid import uuid4

import pytest

from agent_core import (
    ModelMessage,
    ModelMetrics,
    ModelOutputValidationError,
    ModelRole,
    StructuredModelRequest,
    StructuredModelResult,
    generate_validated,
)
from shared_contracts import Plan, PlanAction
from shared_testkit import ScriptedLLMProvider


def _request() -> StructuredModelRequest:
    return StructuredModelRequest(
        run_id=uuid4(),
        role=ModelRole.PLANNER,
        model_profile="local-small.v1",
        messages=(ModelMessage(role="system", content="Return a safe plan."),),
        output_schema={},
        prompt_id="planner",
        prompt_version="v1",
        prompt_hash="a" * 64,
        rendered_input_hash="b" * 64,
    )


def _result(content: dict[str, object]) -> StructuredModelResult:
    return StructuredModelResult(
        content=content,
        provider="scripted",
        model="fake",
        metrics=ModelMetrics(total_duration_ms=1),
    )


VALID_PLAN = {
    "goal": "Find records",
    "actions": [
        {
            "sequence": 1,
            "tool_name": "student_1.records.search.v1",
            "arguments": {"query": "verified"},
            "purpose": "Search verified records",
        }
    ],
    "success_criteria": ["At least one verified record"],
    "risk_level": "low",
    "assumptions": [],
}


def test_valid_output_is_returned_without_repair() -> None:
    provider = ScriptedLLMProvider([_result(VALID_PLAN)])

    output = generate_validated(provider, _request(), Plan, max_repairs=1)

    assert output.value.actions[0] == PlanAction.model_validate(VALID_PLAN["actions"][0])
    assert output.repair_count == 0
    assert provider.requests[0].output_schema["title"] == "Plan"


def test_invalid_output_gets_exactly_one_schema_informed_repair() -> None:
    provider = ScriptedLLMProvider([_result({"goal": "missing fields"}), _result(VALID_PLAN)])

    output = generate_validated(provider, _request(), Plan, max_repairs=1)

    assert output.repair_count == 1
    assert len(provider.requests) == 2
    assert provider.requests[1].repair_attempt == 1
    assert "Validation errors" in provider.requests[1].messages[-1].content


def test_invalid_repair_is_terminal_and_never_loops() -> None:
    provider = ScriptedLLMProvider(
        [_result({"goal": "invalid"}), _result({"goal": "still invalid"})]
    )

    with pytest.raises(ModelOutputValidationError, match="Plan validation"):
        generate_validated(provider, _request(), Plan, max_repairs=1)

    assert len(provider.requests) == 2
    assert provider.remaining_outcomes == 0


def test_repairs_can_be_disabled() -> None:
    provider = ScriptedLLMProvider([_result({"goal": "invalid"}), _result(VALID_PLAN)])

    with pytest.raises(ModelOutputValidationError):
        generate_validated(provider, _request(), Plan, max_repairs=0)

    assert len(provider.requests) == 1
    assert provider.remaining_outcomes == 1
