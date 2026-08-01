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

    def __init__(
        self,
        definitions: Iterable[ToolDefinition],
        *,
        shared_tools: Iterable[str] = (),
    ) -> None:
        tools: dict[str, ToolDefinition] = {}
        shared_names = tuple(shared_tools)
        approved_shared = frozenset(shared_names)
        if len(shared_names) != len(approved_shared):
            raise ToolRegistrationError("approved shared tool names must be unique")
        for definition in definitions:
            if definition.name in tools:
                raise ToolRegistrationError(f"duplicate tool name: {definition.name}")
            if not definition.name.endswith(f".{definition.version}"):
                raise ToolRegistrationError(
                    f"tool name {definition.name} must end with its immutable version"
                )
            self._check_schema(definition.name, "input", definition.input_schema)
            self._check_schema(definition.name, "output", definition.output_schema)
            tools[definition.name] = definition
        unknown_shared = approved_shared.difference(tools)
        if unknown_shared:
            raise ToolRegistrationError(
                f"approved shared tools are not registered: {', '.join(sorted(unknown_shared))}"
            )
        invalid_shared = tuple(
            name for name in approved_shared if tools[name].feature_key != "shared"
        )
        if invalid_shared:
            raise ToolRegistrationError(
                f"shared tools must use feature_key 'shared': {', '.join(sorted(invalid_shared))}"
            )
        unapproved_shared = tuple(
            definition.name
            for definition in tools.values()
            if definition.feature_key == "shared" and definition.name not in approved_shared
        )
        if unapproved_shared:
            raise ToolRegistrationError(
                "shared tools require explicit approval: " + ", ".join(sorted(unapproved_shared))
            )
        self._tools: Mapping[str, ToolDefinition] = tools
        self._shared_tools = approved_shared

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

    def definitions_for(self, feature_key: str) -> tuple[ToolDefinition, ...]:
        """Return only tools owned by a run's feature plus approved shared tools."""
        return tuple(
            definition
            for definition in self._tools.values()
            if definition.feature_key == feature_key or definition.name in self._shared_tools
        )

    def resolve(
        self,
        feature_key: str,
        name: str,
        *,
        version: str | None = None,
    ) -> ToolDefinition:
        """Resolve a tool only when it is visible to the requesting feature."""
        try:
            definition = self._tools[name]
        except KeyError as exc:
            raise UnknownToolError(f"tool is not allowlisted: {name}") from exc
        if definition.feature_key != feature_key and name not in self._shared_tools:
            raise UnknownToolError(f"tool is not allowlisted for feature {feature_key}: {name}")
        if version is not None and definition.version != version:
            raise UnknownToolError(f"tool version is not allowlisted: {name}@{version}")
        return definition

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
