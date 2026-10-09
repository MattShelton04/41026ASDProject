"""Evidence gathering through allowlisted, read-only feature tools.

The Worker never calls a feature directly. It asks a :class:`TemplateToolbox`, which enforces
the template allowlist and the read-only policy, then delegates to a :class:`ToolGateway`
port. Production gateways call the shared MCP server (``mcp``) or, when MCP is disabled in a
local ``direct`` runtime, the feature's catalogued HTTP tool endpoint (``http``). Tests and
offline demos use a fixture gateway (``fake``).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal, Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import JsonValue
from shared_tool_runtime import ToolCatalog

from agent_core import ToolExecutor
from shared_contracts import (
    ApprovalStatus,
    SideEffectClass,
    ToolCall,
    ToolDefinition,
    ToolError,
    ToolOutcome,
    ToolResult,
)
from shared_contracts.multi_agent import (
    MAX_EVIDENCE_EXCERPT_BYTES,
    EvidenceOutcome,
    EvidenceReference,
    PlanStep,
    WorkflowTemplate,
    WorkflowToolDescriptor,
)

Transport = Literal["mcp", "http", "fake", "none"]
SHARED_FEATURE_KEY = "shared"
MAX_STRING_EXCERPT = 500


class ToolGateway(Protocol):
    """Port through which the Worker reaches feature-owned tools."""

    @property
    def transport(self) -> Transport:
        """Transport identity recorded on every evidence reference."""
        ...

    def definition(self, name: str) -> ToolDefinition | None:
        """Return the registered definition for ``name``, if any."""
        ...

    def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
        """Invoke one already-authorised call and return a bounded typed result."""
        ...

    def health(self) -> tuple[bool, str]:
        """Return non-throwing availability and a short safe description."""
        ...


class CatalogToolGateway:
    """Resolve definitions from feature tool catalogues and call through an executor."""

    def __init__(
        self, catalog: ToolCatalog, executor: ToolExecutor, *, transport: Transport
    ) -> None:
        self._definitions = {
            registration.definition.name: registration.definition for registration in catalog.tools
        }
        self._executor = executor
        self._transport: Transport = transport

    @property
    def transport(self) -> Transport:
        return self._transport

    def definition(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
        return self._executor.execute(call, definition, timeout_ms=definition.timeout_ms)

    def health(self) -> tuple[bool, str]:
        return True, f"{len(self._definitions)} catalogued tools via {self._transport}"


class UnavailableToolGateway:
    """Used when no tool transport is configured: every call fails safely and visibly."""

    def __init__(self, definitions: Iterable[ToolDefinition] = (), *, reason: str) -> None:
        self._definitions = {definition.name: definition for definition in definitions}
        self._reason = reason

    @property
    def transport(self) -> Transport:
        return "none"

    def definition(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
        return ToolResult(
            call_id=call.id,
            outcome=ToolOutcome.FAILED,
            error=ToolError(code="tools_unavailable", message=self._reason),
            duration_ms=0,
        )

    def health(self) -> tuple[bool, str]:
        return False, self._reason


class FixtureToolGateway:
    """Deterministic tool results for tests, CI and offline terminal demonstrations.

    A fixture file is JSON: ``{"tools": [{"definition": <ToolDefinition>, "result": {...}}]}``.
    An entry may use ``"error": {"code": ..., "message": ...}`` instead of ``result``.
    """

    def __init__(
        self,
        definitions: Iterable[ToolDefinition],
        results: Mapping[str, Mapping[str, JsonValue]],
        errors: Mapping[str, ToolError] | None = None,
    ) -> None:
        self._definitions = {definition.name: definition for definition in definitions}
        self._results = {name: dict(value) for name, value in results.items()}
        self._errors = dict(errors or {})
        self.calls: list[ToolCall] = []

    @classmethod
    def from_file(cls, path: Path) -> FixtureToolGateway:
        """Load a fixture gateway from a JSON document."""
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not isinstance(payload.get("tools"), list):
            raise ValueError("tool fixture must contain a tools list")
        definitions: list[ToolDefinition] = []
        results: dict[str, Mapping[str, JsonValue]] = {}
        errors: dict[str, ToolError] = {}
        for entry in payload["tools"]:
            definition = ToolDefinition.model_validate(entry["definition"])
            definitions.append(definition)
            if "error" in entry:
                errors[definition.name] = ToolError.model_validate(entry["error"])
            else:
                results[definition.name] = dict(entry.get("result", {}))
        return cls(definitions, results, errors)

    @property
    def transport(self) -> Transport:
        return "fake"

    def definition(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)

    def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
        self.calls.append(call)
        if call.tool_name in self._errors:
            return ToolResult(
                call_id=call.id,
                outcome=ToolOutcome.FAILED,
                error=self._errors[call.tool_name],
                duration_ms=1,
            )
        return ToolResult(
            call_id=call.id,
            outcome=ToolOutcome.SUCCEEDED,
            content=dict(self._results.get(call.tool_name, {})),
            duration_ms=1,
            evidence_references=("transport:fixture",),
        )

    def health(self) -> tuple[bool, str]:
        return True, f"{len(self._definitions)} fixture tools"


class ToolRejectedError(Exception):
    """A tool request violates the template allowlist or the read-only policy."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """Persisted evidence reference plus the complete result for the Reviewer."""

    evidence: EvidenceReference
    content: Mapping[str, JsonValue]


def canonical_json(value: object) -> str:
    """Key-sorted compact JSON used for digests and size bounds."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: object) -> str:
    """SHA-256 of the canonical JSON representation."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def bounded_excerpt(content: Mapping[str, JsonValue]) -> tuple[dict[str, JsonValue], bool]:
    """Keep a result small enough to persist and show, flagging any reduction."""
    full = dict(content)
    if len(canonical_json(full).encode()) <= MAX_EVIDENCE_EXCERPT_BYTES:
        return full, False
    for items in (10, 5, 2, 0):
        shrunk = _shrink(full, items, depth=0)
        if isinstance(shrunk, dict) and (
            len(canonical_json(shrunk).encode()) <= MAX_EVIDENCE_EXCERPT_BYTES
        ):
            return shrunk, True
    return {"note": "Result exceeds the excerpt budget; see result_digest"}, True


def _shrink(value: JsonValue, items: int, *, depth: int) -> JsonValue:
    if depth > 4:
        return "…"
    if isinstance(value, dict):
        return {key: _shrink(item, items, depth=depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [_shrink(item, items, depth=depth + 1) for item in value[:items]]
    if isinstance(value, str) and len(value) > MAX_STRING_EXCERPT:
        return value[:MAX_STRING_EXCERPT] + "…"
    return value


class TemplateToolbox:
    """Enforce one template's allowlist and read-only policy over a gateway."""

    def __init__(self, template: WorkflowTemplate, gateway: ToolGateway) -> None:
        self._template = template
        self._gateway = gateway

    @property
    def transport(self) -> Transport:
        return self._gateway.transport

    def descriptors(self) -> tuple[WorkflowToolDescriptor, ...]:
        """Describe each allowlisted tool and whether the gateway can run it."""
        result: list[WorkflowToolDescriptor] = []
        for name in self._template.allowed_tools:
            definition = self._gateway.definition(name)
            result.append(
                WorkflowToolDescriptor(
                    name=name,
                    description=definition.description if definition else None,
                    side_effect=definition.side_effect.value if definition else None,
                    available=definition is not None and self._policy_issue(definition) is None,
                )
            )
        return tuple(result)

    def authorise(self, tool_name: str) -> ToolDefinition:
        """Return the definition of an allowlisted read-only tool, or raise."""
        if tool_name not in self._template.allowed_tools:
            raise ToolRejectedError(
                "tool_not_allowlisted", f"{tool_name} is not allowlisted by the template"
            )
        definition = self._gateway.definition(tool_name)
        if definition is None:
            raise ToolRejectedError("tool_not_registered", f"{tool_name} is not registered")
        issue = self._policy_issue(definition)
        if issue is not None:
            raise ToolRejectedError("tool_not_read_only", issue)
        return definition

    def validate_arguments(
        self, definition: ToolDefinition, arguments: Mapping[str, JsonValue]
    ) -> None:
        """Validate arguments against the tool's own input schema."""
        try:
            Draft202012Validator(definition.input_schema, format_checker=FormatChecker()).validate(
                dict(arguments)
            )
        except SchemaValidationError as exc:
            raise ToolRejectedError(
                "tool_arguments_invalid",
                f"{definition.name} arguments violate its input schema: {exc.message[:200]}",
            ) from exc

    def template_issues(self) -> list[str]:
        """Static issues: unknown, non-read-only or foreign tools and unknown step arguments."""
        issues: list[str] = []
        for name in self._template.allowed_tools:
            definition = self._gateway.definition(name)
            if definition is None:
                issues.append(f"allowed tool {name} is not registered in any tool catalogue")
                continue
            issue = self._policy_issue(definition)
            if issue is not None:
                issues.append(issue)
        for step in self._template.steps:
            definition = self._gateway.definition(step.tool)
            if definition is None:
                continue
            properties = definition.input_schema.get("properties", {})
            closed = definition.input_schema.get("additionalProperties") is False
            if closed and isinstance(properties, dict):
                unknown = sorted(set(step.arguments) - set(properties))
                if unknown:
                    issues.append(
                        f"step {step.id} passes unknown {step.tool} arguments: {', '.join(unknown)}"
                    )
        return issues

    def _policy_issue(self, definition: ToolDefinition) -> str | None:
        if definition.side_effect is not SideEffectClass.READ_ONLY:
            return f"{definition.name} is {definition.side_effect.value}; only read_only is allowed"
        if definition.requires_approval:
            return f"{definition.name} requires approval; workflow tools must not"
        if definition.feature_key not in {self._template.feature_id, SHARED_FEATURE_KEY}:
            return f"{definition.name} belongs to {definition.feature_key}, not this feature"
        return None

    def invoke(
        self,
        *,
        run_id: UUID,
        request_id: str,
        round_number: int,
        step: PlanStep,
    ) -> ToolInvocation:
        """Run one plan step's tool call, or record a rejection, as evidence."""
        evidence_id = f"ev-{step.id}-r{round_number}"
        call_id = uuid4()
        started = monotonic()
        try:
            definition = self.authorise(step.tool)
            self.validate_arguments(definition, step.arguments)
        except ToolRejectedError as rejected:
            return ToolInvocation(
                evidence=EvidenceReference(
                    id=evidence_id,
                    step_id=step.id,
                    tool_name=step.tool,
                    tool_version="rejected",
                    arguments=dict(step.arguments),
                    outcome=EvidenceOutcome.REJECTED,
                    transport=self.transport,
                    result_digest=digest({}),
                    duration_ms=0,
                    error_code=rejected.code,
                    error_message=rejected.message[:500],
                    tool_call_id=call_id,
                ),
                content={},
            )
        call = ToolCall(
            id=call_id,
            run_id=run_id,
            step_id=uuid5(NAMESPACE_URL, f"multi-agent:{run_id}:{step.id}:{round_number}"),
            request_id=request_id,
            tool_name=definition.name,
            tool_version=definition.version,
            arguments=dict(step.arguments),
            approval_status=ApprovalStatus.NOT_REQUIRED,
        )
        try:
            result = self._gateway.execute(call, definition)
        except Exception:
            # A gateway adapter defect must become failed evidence, never a broken workflow.
            result = ToolResult(
                call_id=call.id,
                outcome=ToolOutcome.FAILED,
                error=ToolError(code="tool_gateway_error", message="Tool gateway failed"),
                duration_ms=max(0, int((monotonic() - started) * 1000)),
            )
        content = dict(result.content) if result.outcome is ToolOutcome.SUCCEEDED else {}
        excerpt, truncated = bounded_excerpt(content)
        error = result.error
        return ToolInvocation(
            evidence=EvidenceReference(
                id=evidence_id,
                step_id=step.id,
                tool_name=definition.name,
                tool_version=definition.version,
                arguments=dict(step.arguments),
                outcome=EvidenceOutcome(result.outcome.value),
                transport=self.transport,
                result_digest=digest(content),
                duration_ms=result.duration_ms,
                excerpt=excerpt,
                excerpt_truncated=truncated,
                error_code=error.code if error else None,
                error_message=error.message[:500] if error else None,
                tool_call_id=call.id,
            ),
            content=content,
        )
