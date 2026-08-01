"""Allowlisted tool registry, schema validation, and effect policy."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

from agent_core.errors import (
    ToolPolicyError,
    ToolRegistrationError,
    ToolSchemaValidationError,
    UnknownToolError,
)
from shared_contracts import ApprovalStatus, SideEffectClass, ToolDefinition


class ToolPolicyDecision(StrEnum):
    """Deterministic authorization result for a proposed tool call."""

    ALLOW = "allow"
    REQUIRE_REVIEW = "require_review"
    DENY = "deny"


class ToolRegistry:
    """Immutable allowlist of versioned tools with pre-checked schemas."""

    def __init__(self, definitions: Iterable[ToolDefinition]) -> None:
        tools: dict[str, ToolDefinition] = {}
        for definition in definitions:
            if definition.name in tools:
                raise ToolRegistrationError(f"duplicate tool name: {definition.name}")
            self._check_schema(definition.name, "input", definition.input_schema)
            self._check_schema(definition.name, "output", definition.output_schema)
            tools[definition.name] = definition
        self._tools: Mapping[str, ToolDefinition] = tools

    @staticmethod
    def _check_schema(tool_name: str, boundary: str, schema: Mapping[str, object]) -> None:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            raise ToolRegistrationError(
                f"{tool_name} has an invalid {boundary} schema: {exc.message}"
            ) from exc

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        """Return definitions in deterministic registration order."""
        return tuple(self._tools.values())

    def resolve(self, name: str) -> ToolDefinition:
        """Resolve an allowlisted tool or fail with a stable domain error."""
        try:
            return self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"tool is not allowlisted: {name}") from exc

    def validate_input(self, definition: ToolDefinition, arguments: Mapping[str, object]) -> None:
        """Validate model-proposed arguments at the final execution boundary."""
        self._validate(definition.name, "input", definition.input_schema, arguments)

    def validate_output(self, definition: ToolDefinition, output: Mapping[str, object]) -> None:
        """Validate a feature-owned tool response before model observation."""
        self._validate(definition.name, "output", definition.output_schema, output)

    @staticmethod
    def _validate(
        tool_name: str,
        boundary: str,
        schema: Mapping[str, object],
        value: Mapping[str, object],
    ) -> None:
        try:
            Draft202012Validator(schema).validate(value)
        except ValidationError as exc:
            path = ".".join(str(part) for part in exc.absolute_path) or "$"
            raise ToolSchemaValidationError(
                f"{tool_name} {boundary} failed at {path}: {exc.message}"
            ) from exc


def authorize_tool(
    definition: ToolDefinition,
    *,
    idempotency_key: str | None,
    approval_status: ApprovalStatus,
    external_effects_enabled: bool = False,
) -> ToolPolicyDecision:
    """Authorize a tool without trusting model-provided policy claims."""
    if definition.side_effect is SideEffectClass.EXTERNAL_EFFECT and not external_effects_enabled:
        return ToolPolicyDecision.DENY

    is_write = definition.side_effect in {
        SideEffectClass.REVERSIBLE_WRITE,
        SideEffectClass.DESTRUCTIVE_WRITE,
        SideEffectClass.EXTERNAL_EFFECT,
    }
    if is_write and not idempotency_key:
        raise ToolPolicyError("write tools require an idempotency key")

    requires_review = definition.requires_approval or definition.side_effect in {
        SideEffectClass.DESTRUCTIVE_WRITE,
        SideEffectClass.EXTERNAL_EFFECT,
    }
    if not requires_review:
        return ToolPolicyDecision.ALLOW
    if approval_status is ApprovalStatus.APPROVED:
        return ToolPolicyDecision.ALLOW
    if approval_status is ApprovalStatus.REJECTED:
        return ToolPolicyDecision.DENY
    return ToolPolicyDecision.REQUIRE_REVIEW
