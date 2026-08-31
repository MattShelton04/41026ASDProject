"""Read model, cursor, and evidence policy for the operations interface."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import JsonValue, ValidationError

from shared_contracts import (
    MAX_RUN_CURSOR_LENGTH,
    MAX_RUN_PAGE_SIZE,
    Adaptation,
    AdaptationEvidence,
    AgentRun,
    AgentRunDetail,
    AgentRunEvidenceDetail,
    AgentRunPage,
    AgentRunSummary,
    AgentStep,
    AgentStepEvidence,
    EvidenceSource,
    HumanReview,
    HumanReviewEvidence,
    ModelInvocationEvidence,
    Observation,
    ObservationEvidence,
    Plan,
    PlanActionEvidence,
    PlanEvidence,
    RunCorrelation,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolCall,
    ToolCallEvidence,
    ToolResult,
    trace_id_from_traceparent,
)

CURSOR_VERSION = 1
MAX_PROJECTED_DEPTH = 6
MAX_PROJECTED_PROPERTIES = 50
MAX_PROJECTED_ITEMS = 50
MAX_PROJECTED_STRING_LENGTH = 2_000
REDACTION_MARKER = "[REDACTED]"
TRUNCATION_MARKER = "[TRUNCATED]"
SENSITIVE_KEY_PARTS = frozenset(
    {
        "apikey",
        "authorization",
        "cookie",
        "credential",
        "password",
        "privatekey",
        "secret",
        "session",
        "token",
    }
)
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/=-]{8,}")
API_KEY_PATTERN = re.compile(r"\b(?:sk|api)[-_][a-zA-Z0-9_-]{12,}\b")
NAMED_SECRET_PATTERN = re.compile(r"(?i)\b(?:password|secret|token|api[_-]?key)\s*[:=]\s*[^\s,;]+")


class InvalidRunCursorError(ValueError):
    """An opaque operations cursor could not be safely decoded."""


@dataclass(frozen=True, slots=True)
class RunListQuery:
    """Validated internal query for a stable page of run snapshots."""

    statuses: tuple[RunStatus, ...] = ()
    feature_key: str | None = None
    model_profile: str | None = None
    cursor_created_at: datetime | None = None
    cursor_id: UUID | None = None
    limit: int = 50

    def __post_init__(self) -> None:
        if (self.cursor_created_at is None) != (self.cursor_id is None):
            raise ValueError("run cursor timestamp and identifier must be supplied together")
        if not 1 <= self.limit <= MAX_RUN_PAGE_SIZE:
            raise ValueError(f"run query limit must be between 1 and {MAX_RUN_PAGE_SIZE}")


@dataclass(frozen=True, slots=True)
class RunSnapshot:
    """Persisted run plus the latest step metadata required by the index."""

    run: AgentRun
    latest_phase: StepPhase | None = None
    latest_step_status: StepStatus | None = None


class RunReader(Protocol):
    """AI-mode query port kept separate from agent-core's mutation store."""

    def list_run_snapshots(self, query: RunListQuery) -> tuple[tuple[RunSnapshot, ...], bool]: ...

    def get(self, run_id: UUID) -> AgentRunDetail | None: ...


@dataclass(frozen=True, slots=True)
class EvidencePolicy:
    """Environment policy controlling restricted evidence in public projections."""

    show_objectives: bool = True
    show_tool_values: bool = True
    show_review_identity: bool = True


class OperationsService:
    """Build safe operations contracts from AI-mode-owned durable state."""

    def __init__(self, reader: RunReader, policy: EvidencePolicy | None = None) -> None:
        self._reader = reader
        self._policy = policy or EvidencePolicy()

    def list_runs(self, query: RunListQuery, *, as_of: datetime) -> AgentRunPage:
        """Return one stable page with an opaque cursor for the next position."""
        snapshots, has_more = self._reader.list_run_snapshots(query)
        items = tuple(self._summary(snapshot, as_of=as_of) for snapshot in snapshots)
        next_cursor = None
        if has_more and snapshots:
            final = snapshots[-1].run
            next_cursor = encode_run_cursor(final.created_at, final.id)
        return AgentRunPage(items=items, next_cursor=next_cursor, as_of=as_of)

    def get_evidence(self, run_id: UUID, *, as_of: datetime) -> AgentRunEvidenceDetail | None:
        """Project allowlisted evidence for one run, or return absent."""
        detail = self._reader.get(run_id)
        if detail is None:
            return None
        latest = detail.steps[-1] if detail.steps else None
        summary = self._summary(
            RunSnapshot(
                run=detail.run,
                latest_phase=latest.phase if latest else None,
                latest_step_status=latest.status if latest else None,
            ),
            as_of=as_of,
        )
        objective = _safe_text(detail.run.objective) if self._policy.show_objectives else None
        final_result = (
            _redacted_object(detail.run.final_result)
            if self._policy.show_tool_values and detail.run.final_result is not None
            else None
        )
        return AgentRunEvidenceDetail(
            run=summary,
            objective=objective,
            limits=detail.run.limits,
            cancel_requested=detail.run.cancel_requested,
            final_result=final_result,
            error=detail.run.error,
            steps=tuple(self._step(step) for step in detail.steps),
            reviews=tuple(self._review(review) for review in detail.reviews),
            correlation=RunCorrelation(
                request_id=detail.run.request_id,
                run_id=detail.run.id,
                traceparent=detail.run.traceparent,
                trace_id=trace_id_from_traceparent(detail.run.traceparent),
            ),
        )

    def _summary(self, snapshot: RunSnapshot, *, as_of: datetime) -> AgentRunSummary:
        run = snapshot.run
        end = run.updated_at if run.status in _terminal_statuses() else as_of
        duration_ms = max(0, int((end - run.created_at).total_seconds() * 1_000))
        preview = None
        if self._policy.show_objectives:
            safe_objective = _safe_text(run.objective)
            preview = (
                safe_objective
                if len(safe_objective) <= 160
                else f"{safe_objective[:159].rstrip()}…"
            )
        return AgentRunSummary(
            id=run.id,
            feature_key=run.feature_key,
            objective_preview=preview,
            status=run.status,
            latest_phase=snapshot.latest_phase,
            latest_step_status=snapshot.latest_step_status,
            model_profile=run.model_profile,
            prompt_set=run.prompt_set,
            iteration_count=run.iteration_count,
            tool_call_count=run.tool_call_count,
            version=run.version,
            review_required=run.status is RunStatus.REVIEW_REQUIRED,
            error_code=run.error.code if run.error else None,
            created_at=run.created_at,
            updated_at=run.updated_at,
            duration_ms=duration_ms,
        )

    def _step(self, step: AgentStep) -> AgentStepEvidence:
        invocation = _model_invocation(step.output.get("model_invocation"))
        source = _step_source(step.phase, invocation is not None)
        duration_ms = None
        if step.started_at is not None and step.completed_at is not None:
            duration_ms = max(0, int((step.completed_at - step.started_at).total_seconds() * 1_000))
        return AgentStepEvidence(
            id=step.id,
            sequence=step.sequence,
            phase=step.phase,
            status=step.status,
            started_at=step.started_at,
            completed_at=step.completed_at,
            duration_ms=duration_ms,
            source=source,
            summary=f"{step.phase.value.title()} step {step.status.value.replace('_', ' ')}",
            plan=_plan_evidence(step.output.get("plan")),
            tool=self._tool_evidence(step),
            observation=_observation_evidence(step.output.get("observation")),
            adaptation=self._adaptation_evidence(step.output.get("adaptation")),
            model_invocation=invocation,
            error=step.error,
        )

    def _tool_evidence(self, step: AgentStep) -> ToolCallEvidence | None:
        call_value = step.input.get("tool_call")
        if call_value is None:
            calls = step.input.get("tool_calls")
            call_value = calls[0] if isinstance(calls, list) and calls else None
        try:
            call = ToolCall.model_validate(call_value)
        except ValidationError:
            return None
        result_value = step.output.get("tool_result")
        if result_value is None:
            results = step.output.get("tool_results")
            result_value = results[0] if isinstance(results, list) and results else None
        try:
            result = ToolResult.model_validate(result_value)
        except ValidationError:
            result = None
        return ToolCallEvidence(
            call_id=call.id,
            step_id=call.step_id,
            tool_name=call.tool_name,
            tool_version=call.tool_version,
            approval_status=call.approval_status,
            outcome=result.outcome if result else None,
            duration_ms=result.duration_ms if result else None,
            retryable=result.retryable if result else None,
            error_code=result.error.code if result and result.error else None,
            evidence_references=result.evidence_references if result else (),
            redacted_arguments=(
                _redacted_object(call.arguments) if self._policy.show_tool_values else None
            ),
            redacted_result=(
                _redacted_object(result.content)
                if self._policy.show_tool_values and result
                else None
            ),
        )

    def _adaptation_evidence(self, value: JsonValue | None) -> AdaptationEvidence | None:
        try:
            adaptation = Adaptation.model_validate(value)
        except ValidationError:
            return None
        return AdaptationEvidence(
            decision=adaptation.decision,
            justification=_safe_text(adaptation.justification),
            redacted_final_result=(
                _redacted_object(adaptation.final_result)
                if self._policy.show_tool_values and adaptation.final_result is not None
                else None
            ),
        )

    def _review(self, review: HumanReview) -> HumanReviewEvidence:
        return HumanReviewEvidence(
            id=review.id,
            step_id=review.step_id,
            call_id=review.tool_call.id,
            tool_name=review.tool_call.tool_name,
            tool_version=review.tool_call.tool_version,
            approval_status=review.tool_call.approval_status,
            decision=review.decision,
            reviewer=(
                _safe_text(review.reviewer)
                if self._policy.show_review_identity
                else REDACTION_MARKER
            ),
            comment=_safe_text(review.comment) if review.comment else None,
            reviewed_at=review.reviewed_at,
        )


def encode_run_cursor(created_at: datetime, run_id: UUID) -> str:
    """Encode a stable run position as a small URL-safe opaque token."""
    payload = json.dumps(
        {"v": CURSOR_VERSION, "created_at": created_at.isoformat(), "id": str(run_id)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_run_cursor(value: str) -> tuple[datetime, UUID]:
    """Validate and decode an operations cursor without leaking parser errors."""
    if not value or len(value) > MAX_RUN_CURSOR_LENGTH:
        raise InvalidRunCursorError("run cursor is invalid")
    try:
        padding = "=" * (-len(value) % 4)
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
        payload = json.loads(decoded)
        if not isinstance(payload, dict) or set(payload) != {"v", "created_at", "id"}:
            raise ValueError
        if payload["v"] != CURSOR_VERSION:
            raise ValueError
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            raise ValueError
        return created_at, UUID(payload["id"])
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidRunCursorError("run cursor is invalid") from exc


def _terminal_statuses() -> frozenset[RunStatus]:
    return frozenset({RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED})


def _step_source(phase: StepPhase, has_model_invocation: bool) -> EvidenceSource:
    if has_model_invocation:
        return EvidenceSource.MODEL
    if phase is StepPhase.ACT:
        return EvidenceSource.TOOL
    return EvidenceSource.ORCHESTRATION


def _plan_evidence(value: JsonValue | None) -> PlanEvidence | None:
    try:
        plan = Plan.model_validate(value)
    except ValidationError:
        return None
    return PlanEvidence(
        goal=_safe_text(plan.goal),
        actions=tuple(
            PlanActionEvidence(
                sequence=action.sequence,
                tool_name=action.tool_name,
                purpose=_safe_text(action.purpose),
            )
            for action in plan.actions
        ),
        success_criteria=tuple(_safe_text(item) for item in plan.success_criteria),
        risk_level=plan.risk_level,
    )


def _observation_evidence(value: JsonValue | None) -> ObservationEvidence | None:
    try:
        observation = Observation.model_validate(value)
    except ValidationError:
        return None
    return ObservationEvidence(
        facts=tuple(_safe_text(item) for item in observation.facts),
        satisfied_criteria=tuple(_safe_text(item) for item in observation.satisfied_criteria),
        unsatisfied_criteria=tuple(_safe_text(item) for item in observation.unsatisfied_criteria),
        unassessed_criteria=tuple(_safe_text(item) for item in observation.unassessed_criteria),
        new_constraints=tuple(_safe_text(item) for item in observation.new_constraints),
    )


def _model_invocation(value: JsonValue | None) -> ModelInvocationEvidence | None:
    try:
        return ModelInvocationEvidence.model_validate(value)
    except ValidationError:
        return None


def _safe_text(value: str) -> str:
    bounded = value[:MAX_PROJECTED_STRING_LENGTH]
    bounded = BEARER_PATTERN.sub(REDACTION_MARKER, bounded)
    bounded = API_KEY_PATTERN.sub(REDACTION_MARKER, bounded)
    bounded = NAMED_SECRET_PATTERN.sub(REDACTION_MARKER, bounded)
    return bounded if len(value) <= MAX_PROJECTED_STRING_LENGTH else f"{bounded}{TRUNCATION_MARKER}"


def _redacted_object(value: object) -> dict[str, JsonValue]:
    projected = _redact(value, depth=0)
    return projected if isinstance(projected, dict) else {"value": projected}


def _redact(value: object, *, depth: int) -> JsonValue:
    if depth >= MAX_PROJECTED_DEPTH:
        return TRUNCATION_MARKER
    if isinstance(value, dict):
        projected: dict[str, JsonValue] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= MAX_PROJECTED_PROPERTIES:
                projected[TRUNCATION_MARKER] = TRUNCATION_MARKER
                break
            key_text = _safe_text(str(key))
            normalized = re.sub(r"[^a-z0-9]", "", key_text.lower())
            projected[key_text] = (
                REDACTION_MARKER
                if any(part in normalized for part in SENSITIVE_KEY_PARTS)
                else _redact(item, depth=depth + 1)
            )
        return projected
    if isinstance(value, (list, tuple)):
        result = [_redact(item, depth=depth + 1) for item in value[:MAX_PROJECTED_ITEMS]]
        if len(value) > MAX_PROJECTED_ITEMS:
            result.append(TRUNCATION_MARKER)
        return result
    if isinstance(value, str):
        return _safe_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _safe_text(str(value))
