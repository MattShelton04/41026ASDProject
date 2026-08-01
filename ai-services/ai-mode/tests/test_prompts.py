"""Tests for versioned prompt loading, hashing, and stable-prefix request construction."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core import create_run
from ai_mode.prompts import PromptRegistry, PromptRegistryError, RegistryPromptBuilder
from shared_contracts import (
    AgentRunRequest,
    Observation,
    Plan,
    SideEffectClass,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
)

PROMPT_ROOT = Path(__file__).resolve().parents[1] / "src" / "ai_mode" / "prompt_assets"


def _run():  # type: ignore[no-untyped-def]
    return create_run(
        AgentRunRequest(feature_key="student-1-feature", objective="Find records"),
        run_id=uuid4(),
        request_id="request-1",
        now=datetime(2026, 8, 1, tzinfo=UTC),
    )


def test_registry_loads_and_caches_reproducibly_hashed_prompt() -> None:
    registry = PromptRegistry(PROMPT_ROOT)

    first = registry.load("planner", "v1")
    second = registry.load("planner", "v1")

    assert first is second
    assert first.metadata.prompt_id == "planner"
    assert len(first.content_hash) == 64


def test_registry_rejects_path_traversal() -> None:
    with pytest.raises(PromptRegistryError, match="identifier or version is invalid"):
        PromptRegistry(PROMPT_ROOT).load("../planner", "v1")


def test_builder_keeps_stable_instructions_before_untrusted_dynamic_data() -> None:
    definition = ToolDefinition(
        name="student_1.records.search.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Search records",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )

    request = RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT)).build_plan_request(
        _run(), (definition,)
    )

    assert request.messages[0].role == "system"
    assert "software-controlled" in request.messages[0].content
    assert request.messages[1].role == "user"
    assert "untrusted task data" in request.messages[1].content
    assert request.prompt_hash == PromptRegistry(PROMPT_ROOT).load("planner", "v1").content_hash
    assert len(request.rendered_input_hash) == 64


def test_builder_constructs_evidence_based_adaptation_request() -> None:
    run = _run()
    plan = Plan(
        goal="Find records",
        actions=(
            {
                "sequence": 1,
                "tool_name": "student_1.records.search.v1",
                "purpose": "Search records",
            },
        ),
        success_criteria=("A record is returned",),
        risk_level="low",
    )
    result = ToolResult(
        call_id=uuid4(),
        outcome=ToolOutcome.SUCCEEDED,
        content={"count": 1},
        duration_ms=1,
    )
    observation = Observation(facts=("Tool call succeeded.",))

    request = RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT)).build_adaptation_request(
        run, plan, result, observation
    )

    assert request.role.value == "adapter"
    assert '"count":1' in request.messages[1].content
    assert request.prompt_id == "adapter"
    assert request.prompt_version == "v1"
