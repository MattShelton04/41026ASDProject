"""Planner, Worker and Reviewer agents over the provider port.

Each agent renders its versioned prompt and a JSON context, asks the provider for structured
output, validates that output against a strict schema and the workflow's policy, and retries a
bounded number of times. When a model keeps failing, the agent falls back to the deterministic
provider (and says so in the audit and the attribution) or, if fallback is disabled, raises
:class:`AgentStageError` so the run ends as ``failed``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from typing import Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from agent_core import (
    LLMProvider,
    ModelMessage,
    ModelProviderError,
    StructuredModelRequest,
    StructuredModelResult,
)
from multi_agent_server.checks import evaluate_checks, recommend
from multi_agent_server.errors import AgentStageError
from multi_agent_server.prompts import AgentPrompt, AgentPromptRole, PromptRegistry
from multi_agent_server.providers import (
    AGENT_MODEL_ROLES,
    DETERMINISTIC_PROFILE,
    DeterministicProvider,
    ProviderMode,
)
from multi_agent_server.tools import TemplateToolbox, ToolInvocation, ToolRejectedError
from shared_contracts.multi_agent import (
    MAX_PLAN_STEPS,
    SEVERITY_RANK,
    AgentRole,
    AuditEvent,
    EvidenceOutcome,
    FindingOutcome,
    FindingSeverity,
    HumanDecisionKind,
    JsonObject,
    ModelAttribution,
    PlanStep,
    ReviewFinding,
    ReviewReport,
    WorkerOutput,
    WorkerStepResult,
    WorkflowPlan,
    WorkflowTemplate,
    resolve_placeholders,
)

T = TypeVar("T")
AuditSink = Callable[[AuditEvent, AgentRole, JsonObject], None]
CancelCheck = Callable[[], None]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _PlannerStep(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=64)
    title: str = Field(min_length=1, max_length=500)
    purpose: str = Field(min_length=1, max_length=4000)
    tool: str = Field(min_length=1, max_length=100)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)
    required: bool = True
    expected_evidence: str | None = Field(default=None, max_length=1000)


class _PlannerOutput(_Strict):
    summary: str = Field(min_length=1, max_length=4000)
    steps: list[_PlannerStep] = Field(min_length=1, max_length=MAX_PLAN_STEPS)
    evidence_needed: list[str] = Field(min_length=1, max_length=MAX_PLAN_STEPS)


class _WorkerStep(_Strict):
    step_id: str = Field(min_length=1, max_length=64)
    findings: list[str] = Field(min_length=1, max_length=5)


class _WorkerOutput(_Strict):
    summary: str = Field(min_length=1, max_length=4000)
    steps: list[_WorkerStep] = Field(max_length=MAX_PLAN_STEPS)


class _ReviewerFinding(_Strict):
    severity: FindingSeverity
    message: str = Field(min_length=1, max_length=4000)
    recommendation: str = Field(min_length=1, max_length=4000)
    step_ids: list[str] = Field(default_factory=list, max_length=MAX_PLAN_STEPS)
    evidence_ids: list[str] = Field(default_factory=list, max_length=10)


class _ReviewerOutput(_Strict):
    summary: str = Field(min_length=1, max_length=4000)
    recommendation: HumanDecisionKind
    findings: list[_ReviewerFinding] = Field(default_factory=list, max_length=20)


@dataclass(frozen=True, slots=True)
class AgentSettings:
    """Bounds for model calls."""

    model_attempts: int = 2
    model_timeout_seconds: float = 60.0
    fallback: Literal["deterministic", "fail"] = "deterministic"
    max_output_tokens: int = 4_096


class StructuredCaller:
    """Call the provider with validation, bounded retries and an audited fallback."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        mode: ProviderMode,
        model_profile: str,
        settings: AgentSettings,
        prompts: PromptRegistry,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if not 1 <= settings.model_attempts <= 3:
            raise ValueError("model attempts must be between 1 and 3")
        self._provider = provider
        self._mode = mode
        self._profile = model_profile
        self._settings = settings
        self._prompts = prompts
        self._clock = clock
        self._fallback = DeterministicProvider()

    @property
    def mode(self) -> ProviderMode:
        return self._mode

    def call(
        self,
        *,
        run_id: UUID,
        role: AgentPromptRole,
        payload: Mapping[str, JsonValue],
        output_model: type[BaseModel],
        parse: Callable[[BaseModel], T],
        audit: AuditSink,
    ) -> tuple[T, ModelAttribution]:
        """Return parsed output plus attribution, or raise ``AgentStageError``."""
        prompt = self._prompts.current(role)
        content = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        agent_role = AgentRole(role)
        attempts = self._settings.model_attempts if self._mode == "model" else 1
        last_error = "no attempt made"
        for attempt in range(1, attempts + 1):
            request = self._request(run_id, role, prompt, content, output_model, attempt - 1)
            # Recorded before the call so a live view can show what it is waiting on.
            audit(AuditEvent.MODEL_STARTED, agent_role, self._started_detail(request, attempt))
            started = monotonic()
            try:
                result = self._provider.generate_structured(request)
            except ModelProviderError as exc:
                last_error = exc.code
                audit(
                    AuditEvent.MODEL_INVOCATION,
                    agent_role,
                    self._invocation_detail(request, attempt, started, "provider_error", exc.code),
                )
                if not exc.retryable:
                    break
                continue
            except Exception:
                # A provider adapter defect is recorded like any other provider failure.
                last_error = "provider_exception"
                audit(
                    AuditEvent.MODEL_INVOCATION,
                    agent_role,
                    self._invocation_detail(
                        request, attempt, started, "provider_error", last_error
                    ),
                )
                break
            try:
                parsed = parse(output_model.model_validate(result.content))
            except (ValidationError, ValueError, ToolRejectedError) as exc:
                last_error = "invalid_output"
                audit(
                    AuditEvent.MODEL_INVOCATION,
                    agent_role,
                    self._invocation_detail(
                        request, attempt, started, "invalid_output", _safe_reason(exc), result
                    ),
                )
                continue
            audit(
                AuditEvent.MODEL_INVOCATION,
                agent_role,
                self._invocation_detail(request, attempt, started, "succeeded", None, result),
            )
            return parsed, self._attribution(agent_role, prompt, result, attempt, fallback=False)
        if self._mode == "model" and self._settings.fallback == "deterministic":
            audit(
                AuditEvent.MODEL_FALLBACK,
                agent_role,
                {"reason": last_error, "fallback_provider": "deterministic"},
            )
            request = self._request(run_id, role, prompt, content, output_model, 0)
            request = request.model_copy(update={"model_profile": DETERMINISTIC_PROFILE})
            result = self._fallback.generate_structured(request)
            try:
                parsed = parse(output_model.model_validate(result.content))
            except (ValidationError, ValueError, ToolRejectedError) as exc:
                raise AgentStageError(
                    f"{role}_fallback_invalid", f"{role} deterministic fallback was invalid"
                ) from exc
            return parsed, self._attribution(agent_role, prompt, result, attempts, fallback=True)
        raise AgentStageError(
            f"{role}_output_unavailable", f"{role} produced no valid output ({last_error})"
        )

    def _request(
        self,
        run_id: UUID,
        role: AgentPromptRole,
        prompt: AgentPrompt,
        content: str,
        output_model: type[BaseModel],
        repair_attempt: int,
    ) -> StructuredModelRequest:
        return StructuredModelRequest(
            run_id=run_id,
            role=AGENT_MODEL_ROLES[role],
            model_profile=self._profile,
            messages=(
                ModelMessage(role="system", content=prompt.content),
                ModelMessage(role="user", content=content[:100_000]),
            ),
            output_schema=output_model.model_json_schema(),
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            prompt_hash=prompt.content_hash,
            rendered_input_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            max_output_tokens=self._settings.max_output_tokens,
            repair_attempt=min(repair_attempt, 2),
            deadline_at=self._clock() + timedelta(seconds=self._settings.model_timeout_seconds),
        )

    @staticmethod
    def _started_detail(request: StructuredModelRequest, attempt: int) -> JsonObject:
        return {
            "attempt": attempt,
            "model_profile": request.model_profile,
            "prompt_id": request.prompt_id,
            "prompt_version": request.prompt_version,
            "repair_attempt": request.repair_attempt,
        }

    @staticmethod
    def _invocation_detail(
        request: StructuredModelRequest,
        attempt: int,
        started: float,
        outcome: str,
        error: str | None,
        result: StructuredModelResult | None = None,
    ) -> JsonObject:
        detail: JsonObject = {
            "attempt": attempt,
            "outcome": outcome,
            "model_profile": request.model_profile,
            "prompt_id": request.prompt_id,
            "prompt_version": request.prompt_version,
            "prompt_hash": request.prompt_hash,
            "rendered_input_hash": request.rendered_input_hash,
            "duration_ms": max(0, int((monotonic() - started) * 1000)),
        }
        if error is not None:
            detail["error"] = error
        if result is not None:
            detail["provider"] = result.provider
            detail["model"] = result.model
            detail["prompt_tokens"] = result.metrics.prompt_tokens
            detail["output_tokens"] = result.metrics.output_tokens
            detail["provider_request_id"] = result.provider_request_id
        return detail

    @staticmethod
    def _attribution(
        role: AgentRole,
        prompt: AgentPrompt,
        result: StructuredModelResult,
        invocations: int,
        *,
        fallback: bool,
    ) -> ModelAttribution:
        return ModelAttribution(
            role=role,
            provider=result.provider,
            model=result.model,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            prompt_hash=prompt.content_hash,
            invocations=invocations,
            fallback=fallback,
        )


def _safe_reason(error: Exception) -> str:
    if isinstance(error, ValidationError):
        return f"schema_violation:{error.error_count()}"
    return str(error)[:200]


def resolved_template_steps(template: WorkflowTemplate, inputs: JsonObject) -> list[PlanStep]:
    """Template steps with ``{{input.*}}`` placeholders substituted."""
    steps: list[PlanStep] = []
    for index, step in enumerate(template.steps, start=1):
        arguments = resolve_placeholders(step.arguments, inputs)
        steps.append(
            PlanStep(
                id=step.id,
                index=index,
                title=step.title,
                purpose=step.purpose,
                tool=step.tool,
                arguments=arguments if isinstance(arguments, dict) else {},
                required=step.required,
            )
        )
    return steps


class Planner:
    """Turns the template objective and inputs into an ordered evidence plan."""

    def __init__(self, caller: StructuredCaller) -> None:
        self._caller = caller

    def plan(
        self,
        *,
        run_id: UUID,
        template: WorkflowTemplate,
        inputs: JsonObject,
        toolbox: TemplateToolbox,
        audit: AuditSink,
    ) -> WorkflowPlan:
        """Produce a validated plan that only uses allowlisted read-only tools."""
        template_steps = resolved_template_steps(template, inputs)
        tools: list[JsonValue] = []
        for name in template.allowed_tools:
            try:
                definition = toolbox.authorise(name)
            except ToolRejectedError:
                continue
            tools.append(
                {
                    "name": definition.name,
                    "description": definition.description,
                    "input_schema": definition.input_schema,
                }
            )
        payload: dict[str, JsonValue] = {
            "template": {
                "id": template.id,
                "version": template.version,
                "title": template.title,
                "objective": template.objective,
                "planner_guidance": template.planner_guidance,
                "steps": [step.model_dump(mode="json") for step in template_steps],
            },
            "inputs": inputs,
            "tools": tools,
        }

        def parse(output: BaseModel) -> _PlannerOutput:
            if not isinstance(output, _PlannerOutput):
                raise TypeError("expected isinstance(output, _PlannerOutput)")
            self._validate(output, template_steps, toolbox)
            return output

        parsed, attribution = self._caller.call(
            run_id=run_id,
            role="planner",
            payload=payload,
            output_model=_PlannerOutput,
            parse=parse,
            audit=audit,
        )
        return WorkflowPlan(
            summary=parsed.summary,
            steps=tuple(
                PlanStep(
                    id=step.id,
                    index=index,
                    title=step.title,
                    purpose=step.purpose,
                    tool=step.tool,
                    arguments=step.arguments,
                    required=step.required,
                    expected_evidence=step.expected_evidence,
                )
                for index, step in enumerate(parsed.steps, start=1)
            ),
            evidence_needed=tuple(item[:500] for item in parsed.evidence_needed if item.strip()),
            produced_by=attribution,
        )

    @staticmethod
    def _validate(
        output: _PlannerOutput, template_steps: Sequence[PlanStep], toolbox: TemplateToolbox
    ) -> None:
        ids = [step.id for step in output.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("plan step identifiers must be unique")
        planned = {step.id: step for step in output.steps}
        for required in (step for step in template_steps if step.required):
            match = planned.get(required.id)
            if match is None or match.tool != required.tool:
                raise ValueError(f"plan omits required template step {required.id}")
        for step in output.steps:
            definition = toolbox.authorise(step.tool)
            toolbox.validate_arguments(definition, step.arguments)
        if not [item for item in output.evidence_needed if item.strip()]:
            raise ValueError("plan must name the evidence it needs")


class Worker:
    """Executes every plan step through the toolbox and reports grounded findings."""

    def __init__(self, caller: StructuredCaller) -> None:
        self._caller = caller

    def work(
        self,
        *,
        run_id: UUID,
        request_id: str,
        round_number: int,
        template: WorkflowTemplate,
        plan: WorkflowPlan,
        toolbox: TemplateToolbox,
        correction_note: str | None,
        audit: AuditSink,
        ensure_active: CancelCheck,
    ) -> tuple[WorkerOutput, dict[str, ToolInvocation]]:
        """Gather evidence for each step, then summarise it through the provider."""
        invocations: dict[str, ToolInvocation] = {}
        for step in plan.steps:
            ensure_active()
            invocation = toolbox.invoke(
                run_id=run_id, request_id=request_id, round_number=round_number, step=step
            )
            evidence = invocation.evidence
            event = (
                AuditEvent.TOOL_REJECTED
                if evidence.outcome is EvidenceOutcome.REJECTED
                else AuditEvent.TOOL_CALL
            )
            audit(
                event,
                AgentRole.WORKER,
                {
                    "step_id": step.id,
                    "evidence_id": evidence.id,
                    "tool_name": evidence.tool_name,
                    "tool_version": evidence.tool_version,
                    "arguments": evidence.arguments,
                    "outcome": evidence.outcome.value,
                    "transport": evidence.transport,
                    "result_digest": evidence.result_digest,
                    "duration_ms": evidence.duration_ms,
                    "error_code": evidence.error_code,
                    "tool_call_id": str(evidence.tool_call_id),
                },
            )
            invocations[step.id] = invocation
        ensure_active()
        evidence_payload: list[JsonValue] = [
            invocations[step.id].evidence.model_dump(mode="json") for step in plan.steps
        ]
        payload: dict[str, JsonValue] = {
            "objective": template.objective,
            "plan": [step.model_dump(mode="json") for step in plan.steps],
            "evidence": evidence_payload,
            "correction_note": correction_note,
        }
        step_ids = {step.id for step in plan.steps}

        def parse(output: BaseModel) -> _WorkerOutput:
            if not isinstance(output, _WorkerOutput):
                raise TypeError("expected isinstance(output, _WorkerOutput)")
            unknown = {step.step_id for step in output.steps} - step_ids
            if unknown:
                raise ValueError("worker output references unknown plan steps")
            return output

        parsed, attribution = self._caller.call(
            run_id=run_id,
            role="worker",
            payload=payload,
            output_model=_WorkerOutput,
            parse=parse,
            audit=audit,
        )
        findings = {step.step_id: step.findings for step in parsed.steps}
        results: list[WorkerStepResult] = []
        for step in plan.steps:
            evidence = invocations[step.id].evidence
            succeeded = evidence.outcome is EvidenceOutcome.SUCCEEDED
            step_findings = findings.get(step.id) or [
                "The Worker reported no findings for this step."
            ]
            results.append(
                WorkerStepResult(
                    step_id=step.id,
                    status="completed" if succeeded else "failed",
                    findings=tuple(finding[:1000] for finding in step_findings[:5]),
                    evidence_ids=(evidence.id,),
                )
            )
        output = WorkerOutput(
            round=round_number,
            summary=parsed.summary,
            steps=tuple(results),
            evidence=tuple(invocations[step.id].evidence for step in plan.steps),
            correction_note=correction_note,
            produced_by=attribution,
        )
        return output, invocations


class Reviewer:
    """Checks Worker output against the plan, the evidence and the template's checks."""

    def __init__(self, caller: StructuredCaller) -> None:
        self._caller = caller

    def review(
        self,
        *,
        run_id: UUID,
        round_number: int,
        template: WorkflowTemplate,
        inputs: JsonObject,
        plan: WorkflowPlan,
        worker_output: WorkerOutput,
        invocations: Mapping[str, ToolInvocation],
        correction_note: str | None,
        audit: AuditSink,
    ) -> ReviewReport:
        """Evaluate checks deterministically, then ask the provider for its assessment."""
        check_findings = evaluate_checks(template.reviewer_checks, plan.steps, invocations, inputs)
        deterministic = recommend(check_findings)
        payload: dict[str, JsonValue] = {
            "objective": template.objective,
            "human_review_guidance": template.human_review_guidance,
            "plan": [step.model_dump(mode="json") for step in plan.steps],
            "worker_output": {
                "summary": worker_output.summary,
                "steps": [step.model_dump(mode="json") for step in worker_output.steps],
            },
            "evidence": [evidence.model_dump(mode="json") for evidence in worker_output.evidence],
            "check_results": [finding.model_dump(mode="json") for finding in check_findings],
            "deterministic_recommendation": deterministic.value,
            "correction_note": correction_note,
        }

        def parse(output: BaseModel) -> _ReviewerOutput:
            if not isinstance(output, _ReviewerOutput):
                raise TypeError("expected isinstance(output, _ReviewerOutput)")
            return output

        parsed, attribution = self._caller.call(
            run_id=run_id,
            role="reviewer",
            payload=payload,
            output_model=_ReviewerOutput,
            parse=parse,
            audit=audit,
        )
        step_ids = {step.id for step in plan.steps}
        evidence_ids = {evidence.id for evidence in worker_output.evidence}
        model_findings = tuple(
            ReviewFinding(
                id=f"f-model-{index}",
                severity=finding.severity,
                outcome=(
                    FindingOutcome.PASS
                    if finding.severity is FindingSeverity.INFO
                    else FindingOutcome.FAIL
                ),
                message=finding.message,
                recommendation=finding.recommendation,
                evidence_ids=tuple(item for item in finding.evidence_ids if item in evidence_ids),
                step_ids=tuple(item for item in finding.step_ids if item in step_ids),
                source="model",
            )
            for index, finding in enumerate(parsed.findings, start=1)
        )
        recommendation = parsed.recommendation
        summary = parsed.summary
        blocking = any(
            finding.outcome is FindingOutcome.FAIL
            and SEVERITY_RANK[finding.severity] >= SEVERITY_RANK[FindingSeverity.HIGH]
            for finding in check_findings
        )
        if blocking and recommendation is HumanDecisionKind.APPROVE:
            recommendation = deterministic
            summary = (
                f"{summary} (Recommendation changed to {deterministic.value}: a high or critical "
                "check failed.)"
            )[:4000]
        return ReviewReport(
            round=round_number,
            summary=summary,
            recommendation=recommendation,
            findings=(*check_findings, *model_findings),
            produced_by=attribution,
        )
