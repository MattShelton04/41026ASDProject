"""Tests for allowlisting, JSON Schema boundaries, and effect authorization."""

import pytest

from agent_core import (
    ToolPolicyDecision,
    ToolPolicyError,
    ToolRegistrationError,
    ToolRegistry,
    ToolSchemaValidationError,
    UnknownToolError,
    authorize_tool,
)
from shared_contracts import ApprovalStatus, SideEffectClass, ToolDefinition


def _definition(
    *,
    name: str = "student_1.records.search.v1",
    side_effect: SideEffectClass = SideEffectClass.READ_ONLY,
    requires_approval: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        version="v1",
        feature_key="student-1-feature",
        description="Search feature-owned records",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string", "minLength": 1}},
            "required": ["query"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"count": {"type": "integer", "minimum": 0}},
            "required": ["count"],
            "additionalProperties": False,
        },
        side_effect=side_effect,
        requires_approval=requires_approval,
    )


def test_registry_rejects_duplicates_and_invalid_schemas() -> None:
    definition = _definition()
    with pytest.raises(ToolRegistrationError, match="duplicate tool name"):
        ToolRegistry([definition, definition])

    invalid = definition.model_copy(update={"input_schema": {"type": "not-a-json-type"}})
    with pytest.raises(ToolRegistrationError, match="invalid input schema"):
        ToolRegistry([invalid])


def test_registry_rejects_unknown_tools_and_invalid_values() -> None:
    registry = ToolRegistry([_definition()])
    with pytest.raises(UnknownToolError, match="not allowlisted"):
        registry.resolve("student-1-feature", "student_2.unknown.v1")

    with pytest.raises(ToolSchemaValidationError, match="input failed at query"):
        registry.validate_input(registry.definitions[0], {"query": "", "extra": True})

    with pytest.raises(ToolSchemaValidationError, match="output failed at count"):
        registry.validate_output(registry.definitions[0], {"count": -1})


def test_read_only_tools_execute_without_approval() -> None:
    decision = authorize_tool(
        _definition(),
        idempotency_key=None,
        approval_status=ApprovalStatus.NOT_REQUIRED,
    )

    assert decision is ToolPolicyDecision.ALLOW


def test_writes_require_idempotency_and_protected_writes_require_review() -> None:
    write = _definition(side_effect=SideEffectClass.REVERSIBLE_WRITE)
    with pytest.raises(ToolPolicyError, match="idempotency key"):
        authorize_tool(
            write,
            idempotency_key=None,
            approval_status=ApprovalStatus.NOT_REQUIRED,
        )

    protected = _definition(side_effect=SideEffectClass.DESTRUCTIVE_WRITE)
    pending = authorize_tool(
        protected,
        idempotency_key="run:action:1",
        approval_status=ApprovalStatus.PENDING,
    )
    approved = authorize_tool(
        protected,
        idempotency_key="run:action:1",
        approval_status=ApprovalStatus.APPROVED,
    )

    assert pending is ToolPolicyDecision.REQUIRE_REVIEW
    assert approved is ToolPolicyDecision.ALLOW


def test_external_effects_are_disabled_by_default() -> None:
    decision = authorize_tool(
        _definition(side_effect=SideEffectClass.EXTERNAL_EFFECT),
        idempotency_key="run:action:1",
        approval_status=ApprovalStatus.APPROVED,
    )

    assert decision is ToolPolicyDecision.DENY


def test_registry_scopes_feature_tools_and_requires_explicit_shared_approval() -> None:
    student_one = _definition()
    student_two = _definition(name="student_2.records.search.v1").model_copy(
        update={"feature_key": "student-2-feature"}
    )
    shared = _definition(name="shared.lookup.v1").model_copy(update={"feature_key": "shared"})
    registry = ToolRegistry(
        [student_one, student_two, shared],
        shared_tools=[shared.name],
    )

    visible = registry.definitions_for("student-1-feature")

    assert [definition.name for definition in visible] == [student_one.name, shared.name]
    with pytest.raises(UnknownToolError, match="not allowlisted for feature"):
        registry.resolve("student-1-feature", student_two.name)
    with pytest.raises(UnknownToolError, match="version"):
        registry.resolve("student-1-feature", student_one.name, version="v2")
    with pytest.raises(ToolRegistrationError, match="explicit approval"):
        ToolRegistry([shared])


def test_registry_rejects_a_name_that_does_not_encode_its_version() -> None:
    definition = _definition(name="student_1.records.search").model_copy(update={"version": "v1"})

    with pytest.raises(ToolRegistrationError, match="immutable version"):
        ToolRegistry([definition])
