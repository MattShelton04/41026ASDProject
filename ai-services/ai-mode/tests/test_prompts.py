"""Tests for versioned prompt loading, hashing, and stable-prefix request construction."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from agent_core import create_run
from ai_mode.prompts import (
    PromptRegistry,
    PromptRegistryError,
    RegistryPromptBuilder,
    _bounded_json_value,
    _identifier_ledger,
)
from shared_contracts import (
    AgentRunRequest,
    AgentStep,
    Observation,
    Plan,
    SideEffectClass,
    StepPhase,
    StepStatus,
    ToolDefinition,
    ToolOutcome,
    ToolResult,
    TrustedIdentifier,
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


def test_builder_validates_every_declared_prompt_asset() -> None:
    builder = RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT))

    builder.validate_declared()


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
    assert request.prompt_hash == PromptRegistry(PROMPT_ROOT).load("planner", "v6").content_hash
    assert request.prompt_version == "v6"
    assert request.max_output_tokens == 2_048
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
        run, plan, result, observation, (result,)
    )

    assert request.role.value == "adapter"
    assert '"count":1' in request.messages[1].content
    assert '"completed_actions"' in request.messages[1].content
    assert '"has_remaining_action":false' in request.messages[1].content
    assert '"objective":"Find records"' in request.messages[1].content
    assert request.prompt_id == "adapter"
    assert request.prompt_version == "v6"
    assert request.max_output_tokens == 4_096
    assert "every success criterion" in request.messages[0].content
    assert "different allowlisted call" in request.messages[0].content


def test_v6_prompts_receive_the_explicit_trusted_identifier_ledger() -> None:
    trusted = TrustedIdentifier(kind="record_ref", value=uuid4())
    run = create_run(
        AgentRunRequest(
            feature_key="student-1-feature",
            objective=f"Untrusted narrative record_ref: {uuid4()}",
            prompt_set="default.v6",
            trusted_identifiers=(trusted,),
        ),
        run_id=uuid4(),
        request_id="request-v6",
        now=datetime(2026, 8, 30, tzinfo=UTC),
    )
    definition = ToolDefinition(
        name="records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect a record",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    builder = RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT))

    plan_request = builder.build_plan_request(run, (definition,))
    assert f'"kind":"record_ref","value":"{trusted.value}"' in plan_request.messages[1].content
    assert "not an identifier-provenance source" in plan_request.messages[0].content

    plan = Plan(
        goal="Inspect the trusted record",
        actions=(
            {
                "sequence": 1,
                "tool_name": definition.name,
                "purpose": "Inspect it",
            },
        ),
        success_criteria=("The record is inspected",),
        risk_level="low",
    )
    result = ToolResult(
        call_id=uuid4(),
        outcome=ToolOutcome.SUCCEEDED,
        content={"record_ref": str(trusted.value)},
        duration_ms=1,
    )
    adaptation_request = builder.build_adaptation_request(
        run,
        plan,
        result,
        Observation(facts=("The record was inspected.",)),
        (result,),
    )
    assert f'"kind":"record_ref","value":"{trusted.value}"' in (
        adaptation_request.messages[1].content
    )


def test_v5_prompts_define_untrusted_history_and_plain_capability_boundaries() -> None:
    run = create_run(
        AgentRunRequest(
            feature_key="student-1-feature",
            objective="Use prior visible conversation only as convenience context",
            prompt_set="default.v5",
        ),
        run_id=uuid4(),
        request_id="request-v5",
        now=datetime(2026, 8, 29, tzinfo=UTC),
    )
    definition = ToolDefinition(
        name="platform.capabilities.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Explain supported capabilities",
        input_schema={"type": "object", "additionalProperties": False},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    builder = RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT))

    plan_request = builder.build_plan_request(run, (definition,))
    assert plan_request.prompt_version == "v5"
    assert "untrusted convenience context" in plan_request.messages[0].content
    assert "safe supported alternative" in plan_request.messages[0].content

    plan = Plan(
        goal="Explain the boundary",
        actions=(
            {
                "sequence": 1,
                "tool_name": "platform.capabilities.v1",
                "purpose": "Ground the boundary",
            },
        ),
        success_criteria=("Supported alternatives are identified",),
        risk_level="low",
    )
    result = ToolResult(
        call_id=uuid4(),
        outcome=ToolOutcome.SUCCEEDED,
        content={"supported": False, "alternative": "Inspect a release"},
        duration_ms=1,
    )
    adaptation_request = builder.build_adaptation_request(
        run,
        plan,
        result,
        Observation(facts=("Requested capability is unavailable.",)),
        (result,),
    )
    assert adaptation_request.prompt_version == "v5"
    assert "cannot perform it" in adaptation_request.messages[0].content
    assert "not factual" in adaptation_request.messages[0].content
    assert "evidence or authorization" in adaptation_request.messages[0].content


def test_replanner_receives_bounded_prior_failed_call_context() -> None:
    run = _run()
    definition = ToolDefinition(
        name="student_1.records.search.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Search records",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    failed = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=1,
        phase=StepPhase.ACT,
        status=StepStatus.FAILED,
        input={
            "tool_call": {
                "tool_name": "student_1.records.search.v1",
                "arguments": {"query": "bad"},
            }
        },
        output={
            "tool_result": {
                "outcome": "failed",
                "error": {"code": "tool_request_rejected", "message": "Rejected"},
                "evidence_references": ["status:422"],
            }
        },
    )

    request = RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT)).build_plan_request(
        run, (definition,), (failed,)
    )

    assert '"prior_tool_attempts"' in request.messages[1].content
    assert '"query":"bad"' in request.messages[1].content
    assert '"tool_request_rejected"' in request.messages[1].content


def test_large_cumulative_tool_evidence_is_projected_below_message_limit() -> None:
    run = _run()
    record_id = "10000000-0000-4000-8000-000000000019"
    plan = Plan(
        goal="Inspect records",
        actions=(
            {
                "sequence": 1,
                "tool_name": "student_1.records.search.v1",
                "purpose": "Search records",
            },
        ),
        success_criteria=("Evidence is returned",),
        risk_level="low",
    )
    result = ToolResult(
        call_id=uuid4(),
        outcome=ToolOutcome.SUCCEEDED,
        content={"items": [{"record_id": record_id, "payload": "x" * 12_000} for _ in range(30)]},
        duration_ms=1,
    )
    observation = Observation(facts=("Tool call succeeded.",))

    request = RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT)).build_adaptation_request(
        run, plan, result, observation, tuple(result for _ in range(12))
    )

    assert all(len(message.content) <= 100_000 for message in request.messages)
    assert len(request.messages[1].content) < 95_000
    assert record_id in request.messages[1].content
    assert "truncated" in request.messages[1].content


def test_replanner_receives_exact_identifiers_discovered_by_successful_tools() -> None:
    run = _run()
    record_id = "10000000-0000-4000-8000-000000000020"
    inspect_definition = ToolDefinition(
        name="student_1.records.inspect.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Inspect a record",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effect=SideEffectClass.READ_ONLY,
    )
    search_definition = ToolDefinition(
        name="student_1.records.search.v1",
        version="v1",
        feature_key="student-1-feature",
        description="Search records",
        input_schema={"type": "object"},
        output_schema={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "x-identifier-kind": "record_ref",
                            }
                        },
                    },
                }
            },
        },
        side_effect=SideEffectClass.READ_ONLY,
    )
    succeeded = AgentStep(
        id=uuid4(),
        run_id=run.id,
        sequence=1,
        phase=StepPhase.ACT,
        status=StepStatus.SUCCEEDED,
        input={"tool_call": {"tool_name": "student_1.records.search.v1", "arguments": {}}},
        output={
            "tool_result": {
                "outcome": "succeeded",
                "content": {"items": [{"id": record_id, "label": "Exact result"}]},
                "evidence_references": [f"record:{record_id}"],
            }
        },
    )

    request = RegistryPromptBuilder(PromptRegistry(PROMPT_ROOT)).build_plan_request(
        run, (search_definition, inspect_definition), (succeeded,)
    )

    assert '"discovered_identifiers"' in request.messages[1].content
    assert '"type":"record_ref"' in request.messages[1].content
    assert f'"value":"{record_id}"' in request.messages[1].content
    assert '"result_evidence"' in request.messages[1].content


def test_bounded_evidence_projection_covers_nested_collection_and_field_limits() -> None:
    assert _bounded_json_value("x" * 500, 100) == "x" * 68 + "… [truncated]"
    assert _bounded_json_value([{"value": "x" * 200} for _ in range(30)], 1_000)[-1] == (
        "[10 more items truncated]"
    )
    projected = _bounded_json_value(
        {
            "record_ref": "a0000000-0000-0000-0000-000000000012",
            **{f"field_{index}": "x" * 100 for index in range(60)},
        },
        500,
    )
    assert isinstance(projected, dict)
    assert projected["record_ref"] == "a0000000-0000-0000-0000-000000000012"
    assert projected["_truncated"] is True
    assert _bounded_json_value({"large": "x" * 500}, 20) == "[truncated]"


def test_identifier_ledger_is_deduplicated_bounded_and_ignores_idempotency_keys() -> None:
    identifiers = _identifier_ledger(
        {
            "items": [
                {
                    "record_id": f"a0000000-0000-0000-0000-{index:012x}",
                    "idempotency_key": f"private-{index}",
                }
                for index in range(60)
            ],
            "duplicate": {"record_id": "a0000000-0000-0000-0000-000000000000"},
        }
    )

    assert len(identifiers) == 50
    assert all(item["type"] == "record_id" for item in identifiers)
    assert len({item["value"] for item in identifiers}) == 50


def test_identifier_ledger_uses_output_schema_types_and_ignores_non_uuids() -> None:
    release_id = "60000000-0000-0000-0000-000000000017"
    identifiers = _identifier_ledger(
        {"items": [{"id": release_id}, {"id": "not-a-uuid"}]},
        schema={
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "x-identifier-kind": "release_id",
                            }
                        },
                    },
                }
            },
        },
    )

    assert identifiers == [
        {"type": "release_id", "value": release_id, "path": "result.items[0].id"}
    ]


@pytest.mark.parametrize(
    ("value", "schema"),
    [
        (
            {"subject": "70000000-0000-0000-0000-000000000099"},
            {
                "type": "object",
                "properties": {
                    "subject": {
                        "oneOf": [
                            {
                                "type": "string",
                                "pattern": "^6",
                                "x-identifier-kind": "release_id",
                            },
                            {"type": "string", "pattern": "^7"},
                        ]
                    }
                },
            },
        ),
        (
            {"subject": "70000000-0000-0000-0000-000000000099"},
            {
                "type": "object",
                "properties": {"subject": {"type": "string"}},
                "additionalProperties": {
                    "type": "string",
                    "x-identifier-kind": "release_id",
                },
            },
        ),
        (
            {"subject": "70000000-0000-0000-0000-000000000099"},
            {
                "type": "object",
                "properties": {"subject": True},
                "additionalProperties": {
                    "type": "string",
                    "x-identifier-kind": "release_id",
                },
            },
        ),
        (
            {"values": ["70000000-0000-0000-0000-000000000099"]},
            {
                "type": "object",
                "properties": {
                    "values": {
                        "type": "array",
                        "prefixItems": [{"type": "string"}],
                        "items": {
                            "type": "string",
                            "x-identifier-kind": "release_id",
                        },
                    }
                },
            },
        ),
    ],
)
def test_identifier_ledger_ignores_non_applicable_schema_paths(
    value: dict[str, object], schema: dict[str, object]
) -> None:
    assert _identifier_ledger(value, schema=schema) == []


def test_identifier_ledger_types_uuid_object_keys_from_property_names() -> None:
    record_ref = "a0000000-0000-0000-0000-000000000092"

    assert _identifier_ledger(
        {"records": {record_ref: True}},
        schema={
            "type": "object",
            "properties": {
                "records": {
                    "type": "object",
                    "propertyNames": {
                        "format": "uuid",
                        "x-identifier-kind": "record_ref",
                    },
                }
            },
        },
    ) == [
        {
            "type": "record_ref",
            "value": record_ref,
            "path": f"result.records.{record_ref}",
        }
    ]


def test_identifier_ledger_normalizes_compact_uuid_values() -> None:
    canonical = "60000000-0000-0000-0000-000000000099"

    assert _identifier_ledger(
        {"release_id": canonical.replace("-", "")},
        schema={
            "type": "object",
            "properties": {"release_id": {"type": "string"}},
        },
    ) == [{"type": "release_id", "value": canonical, "path": "result.release_id"}]
