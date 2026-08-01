"""Stable, domain-neutral contracts for the shared agent harness."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import Field, JsonValue, model_validator

from shared_contracts.base import ContractModel

Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
JsonObject = dict[str, JsonValue]


class RunStatus(StrEnum):
    """Persisted lifecycle of an agent run."""

    QUEUED = "queued"
    PLANNING = "planning"
    READY = "ready"
    ACTING = "acting"
    OBSERVING = "observing"
    ADAPTING = "adapting"
    REVIEW_REQUIRED = "review_required"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepPhase(StrEnum):
    """Four auditable phases of the shared agentic loop."""

    PLAN = "plan"
    ACT = "act"
    OBSERVE = "observe"
    ADAPT = "adapt"


class StepStatus(StrEnum):
    """Execution status of one persisted phase step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SideEffectClass(StrEnum):
    """Policy classification for model-callable tools."""

    READ_ONLY = "read_only"
    REVERSIBLE_WRITE = "reversible_write"
    DESTRUCTIVE_WRITE = "destructive_write"
    EXTERNAL_EFFECT = "external_effect"


class ApprovalStatus(StrEnum):
    """Human approval state for a protected tool call."""

    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ToolOutcome(StrEnum):
    """Portable outcome of a tool invocation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"


class AdaptationDecision(StrEnum):
    """Validated decision made after observing an action."""

    CONTINUE = "continue"
    REPLAN = "replan"
    REQUEST_REVIEW = "request_review"
    COMPLETE = "complete"
    FAIL = "fail"


class ReviewDecision(StrEnum):
    """Human decision for exactly one pending protected action."""

    APPROVE = "approve"
    REJECT = "reject"


class RunLimits(ContractModel):
    """Hard execution limits controlled by deterministic code."""

    max_iterations: int = Field(default=6, ge=1, le=20)
    max_tool_calls: int = Field(default=12, ge=1, le=50)
    time_budget_ms: int = Field(default=120_000, ge=1_000, le=900_000)
    max_model_repairs: int = Field(default=1, ge=0, le=1)


class AgentRunRequest(ContractModel):
    """Request accepted from a feature backend to start one agent run."""

    feature_key: Identifier
    objective: str = Field(min_length=1, max_length=4_000)
    prompt_set: Identifier = "default.v1"
    model_profile: Identifier = "local-small.v1"
    limits: RunLimits = Field(default_factory=RunLimits)


class PlanAction(ContractModel):
    """One allowlisted, typed action proposed by the planner."""

    sequence: int = Field(ge=1, le=50)
    tool_name: Identifier
    arguments: JsonObject = Field(default_factory=dict, max_length=100)
    purpose: str = Field(min_length=1, max_length=1_000)


class Plan(ContractModel):
    """Auditable planner output; it intentionally excludes private reasoning."""

    goal: str = Field(min_length=1, max_length=2_000)
    actions: tuple[PlanAction, ...] = Field(min_length=1, max_length=50)
    success_criteria: tuple[str, ...] = Field(min_length=1, max_length=20)
    risk_level: str = Field(pattern=r"^(low|medium|high)$")
    assumptions: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def actions_have_contiguous_sequences(self) -> Plan:
        """Reject ambiguous action ordering before any effect can execute."""
        expected = list(range(1, len(self.actions) + 1))
        actual = [action.sequence for action in self.actions]
        if actual != expected:
            raise ValueError("action sequences must be contiguous and start at 1")
        return self


class ToolDefinition(ContractModel):
    """Allowlisted tool metadata and its JSON Schema boundary."""

    name: Identifier
    version: Identifier
    description: str = Field(min_length=1, max_length=1_000)
    input_schema: JsonObject
    output_schema: JsonObject
    side_effect: SideEffectClass
    timeout_ms: int = Field(default=10_000, ge=100, le=120_000)
    requires_approval: bool = False


class ToolCall(ContractModel):
    """Validated request to execute one tool."""

    id: UUID
    run_id: UUID
    step_id: UUID
    tool_name: Identifier
    tool_version: Identifier
    arguments: JsonObject = Field(default_factory=dict, max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    approval_status: ApprovalStatus


class ToolError(ContractModel):
    """Safe error returned to orchestration code instead of an exception trace."""

    code: Identifier
    message: str = Field(min_length=1, max_length=2_000)


class ToolResult(ContractModel):
    """Bounded, structured observation source from one tool invocation."""

    call_id: UUID
    outcome: ToolOutcome
    content: JsonObject = Field(default_factory=dict, max_length=100)
    error: ToolError | None = None
    duration_ms: int = Field(ge=0)
    retryable: bool = False
    evidence_references: tuple[str, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def error_matches_outcome(self) -> ToolResult:
        """Require a safe error exactly when the invocation did not succeed."""
        if self.outcome is ToolOutcome.SUCCEEDED and self.error is not None:
            raise ValueError("successful tool results cannot contain an error")
        if self.outcome is not ToolOutcome.SUCCEEDED and self.error is None:
            raise ValueError("unsuccessful tool results must contain an error")
        return self


class Observation(ContractModel):
    """Facts derived from a persisted tool result."""

    facts: tuple[str, ...] = Field(min_length=1, max_length=50)
    satisfied_criteria: tuple[str, ...] = Field(default=(), max_length=20)
    unsatisfied_criteria: tuple[str, ...] = Field(default=(), max_length=20)
    unassessed_criteria: tuple[str, ...] = Field(default=(), max_length=20)
    new_constraints: tuple[str, ...] = Field(default=(), max_length=20)


class Adaptation(ContractModel):
    """Concise, structured post-observation decision."""

    decision: AdaptationDecision
    justification: str = Field(min_length=1, max_length=2_000)
    final_result: JsonObject | None = None

    @model_validator(mode="after")
    def final_result_only_on_completion(self) -> Adaptation:
        """Keep terminal output semantics unambiguous."""
        if self.decision is AdaptationDecision.COMPLETE and self.final_result is None:
            raise ValueError("complete adaptations require a final_result")
        if self.decision is not AdaptationDecision.COMPLETE and self.final_result is not None:
            raise ValueError("only complete adaptations may include a final_result")
        return self


class AgentStep(ContractModel):
    """Safe persisted summary of one run phase."""

    id: UUID
    run_id: UUID
    sequence: int = Field(ge=1)
    phase: StepPhase
    status: StepStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    input: JsonObject = Field(default_factory=dict, max_length=100)
    output: JsonObject = Field(default_factory=dict, max_length=100)
    error: ToolError | None = None


class HumanReviewRequest(ContractModel):
    """Authenticated human decision submitted for a pending action."""

    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=200)
    comment: str | None = Field(default=None, max_length=2_000)


class HumanReview(ContractModel):
    """Immutable audit record for a protected-action decision."""

    id: UUID
    run_id: UUID
    step_id: UUID
    tool_call: ToolCall
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=200)
    comment: str | None = Field(default=None, max_length=2_000)
    reviewed_at: datetime


class AgentRun(ContractModel):
    """Public, safe snapshot of a persisted agent run."""

    id: UUID
    request_id: str = Field(min_length=1, max_length=200)
    feature_key: Identifier
    objective: str = Field(min_length=1, max_length=4_000)
    status: RunStatus
    prompt_set: Identifier
    model_profile: Identifier
    limits: RunLimits
    iteration_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    version: int = Field(default=0, ge=0)
    cancel_requested: bool = False
    created_at: datetime
    updated_at: datetime
    final_result: JsonObject | None = None
    error: ToolError | None = None


class AgentRunDetail(ContractModel):
    """Run snapshot plus its ordered, safe phase history."""

    run: AgentRun
    steps: tuple[AgentStep, ...] = ()
    reviews: tuple[HumanReview, ...] = ()
