"""Stable, domain-neutral contracts for the shared agent harness."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from shared_contracts.base import ContractModel
from shared_contracts.grounding import GroundingRequest
from shared_contracts.http import IdempotencyKey, RequestId, Traceparent
from shared_contracts.retrieval import RetrievalResponse

Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
JsonObject = dict[str, JsonValue]
PromptSet = Literal[
    "default.v1",
    "default.v2",
    "default.v3",
    "default.v4",
    "default.v5",
    "default.v6",
    "default.v7",
    "default.v8",
]
SUPPORTED_PROMPT_SETS: tuple[PromptSet, ...] = (
    "default.v1",
    "default.v2",
    "default.v3",
    "default.v4",
    "default.v5",
    "default.v6",
    "default.v7",
    "default.v8",
)
DEFAULT_PROMPT_SET: PromptSet = "default.v7"
DEFAULT_EVENT_PAGE_SIZE = 100
MAX_EVENT_PAGE_SIZE = 200
MAX_EVENT_CURSOR = 2**63 - 1


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

    max_iterations: int = Field(default=10, ge=1, le=30)
    max_tool_calls: int = Field(default=30, ge=1, le=100)
    time_budget_ms: int = Field(default=180_000, ge=1_000, le=900_000)
    max_parallel_tools: int = Field(default=10, ge=1, le=25)
    max_model_repairs: int = Field(default=1, ge=0, le=2)


class TrustedIdentifier(ContractModel):
    """One feature-supplied identifier that orchestration may copy into a tool call."""

    kind: Identifier
    value: UUID


class AgentRunRequest(ContractModel):
    """Request accepted from a feature backend to start one agent run."""

    feature_key: Identifier
    objective: str = Field(min_length=1, max_length=16_000)
    grounding: GroundingRequest | None = None
    prompt_set: PromptSet = DEFAULT_PROMPT_SET
    model_profile: Identifier = "remote-standard.v1"
    limits: RunLimits = Field(default_factory=RunLimits)
    tool_allowlist: tuple[Identifier, ...] | None = Field(default=None, max_length=50)
    trusted_identifiers: tuple[TrustedIdentifier, ...] = Field(default=(), max_length=100)

    @field_validator("tool_allowlist")
    @classmethod
    def tool_allowlist_is_unique(cls, value: tuple[str, ...] | None) -> tuple[str, ...] | None:
        """Reject ambiguous per-run capability boundaries."""
        if value is not None and len(value) != len(set(value)):
            raise ValueError("tool_allowlist entries must be unique")
        return value

    @field_validator("trusted_identifiers")
    @classmethod
    def trusted_identifiers_are_unique(
        cls, value: tuple[TrustedIdentifier, ...]
    ) -> tuple[TrustedIdentifier, ...]:
        """Reject duplicate trust claims so the persisted boundary stays canonical."""
        identities = tuple((item.kind, item.value) for item in value)
        if len(identities) != len(set(identities)):
            raise ValueError("trusted_identifiers entries must be unique")
        return value


class PlanAction(ContractModel):
    """One allowlisted action; equal sequence values form an execution stage."""

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
        """Require deterministic, ordered, gap-free stages while allowing batching."""
        actual = [action.sequence for action in self.actions]
        expected_stages = list(range(1, max(actual) + 1))
        if actual != sorted(actual) or sorted(set(actual)) != expected_stages:
            raise ValueError("action sequences must be contiguous stages starting at 1 and ordered")
        return self


class ToolDefinition(ContractModel):
    """Allowlisted tool metadata and its JSON Schema boundary."""

    name: Identifier
    version: Identifier
    feature_key: Identifier
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
    request_id: RequestId = "unknown"
    traceparent: Traceparent | None = None
    tool_name: Identifier
    tool_version: Identifier
    arguments: JsonObject = Field(default_factory=dict, max_length=100)
    idempotency_key: IdempotencyKey | None = None
    approval_status: ApprovalStatus


class ToolError(ContractModel):
    """Safe error returned to orchestration code instead of an exception trace."""

    code: Identifier
    message: str = Field(min_length=1, max_length=2_000)


class ToolResult(ContractModel):
    """Bounded result for one invocation, including an invocation within a batch."""

    call_id: UUID
    outcome: ToolOutcome
    content: JsonObject = Field(default_factory=dict, max_length=100)
    error: ToolError | None = None
    duration_ms: int = Field(ge=0)
    retryable: bool = False
    evidence_references: tuple[str, ...] = Field(default=(), max_length=20)
    retrieval: RetrievalResponse | None = None

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
    """Safe phase summary; ACT input/output may contain ordered tool call/result batches."""

    id: UUID
    run_id: UUID
    sequence: int = Field(ge=1)
    phase: StepPhase
    status: StepStatus
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    input: JsonObject = Field(default_factory=dict, max_length=100)
    output: JsonObject = Field(default_factory=dict, max_length=100)
    error: ToolError | None = None

    @model_validator(mode="after")
    def timestamps_are_ordered(self) -> AgentStep:
        """Reject impossible negative step durations."""
        if (
            self.started_at is not None
            and self.completed_at is not None
            and self.completed_at < self.started_at
        ):
            raise ValueError("completed_at must not be earlier than started_at")
        return self


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
    reviewed_at: AwareDatetime


class AgentRun(ContractModel):
    """Public, safe snapshot of a persisted agent run."""

    id: UUID
    request_id: RequestId
    traceparent: Traceparent | None = None
    feature_key: Identifier
    objective: str = Field(min_length=1, max_length=16_000)
    status: RunStatus
    prompt_set: Identifier
    model_profile: Identifier
    limits: RunLimits
    tool_allowlist: tuple[Identifier, ...] | None = Field(default=None, max_length=50)
    trusted_identifiers: tuple[TrustedIdentifier, ...] = Field(default=(), max_length=100)
    iteration_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    version: int = Field(default=0, ge=0)
    cancel_requested: bool = False
    created_at: AwareDatetime
    updated_at: AwareDatetime
    final_result: JsonObject | None = None
    grounding: GroundingRequest | None = None
    error: ToolError | None = None

    @model_validator(mode="after")
    def snapshot_matches_lifecycle(self) -> AgentRun:
        """Keep direct construction and persistence reloads consistent with run policy."""
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not be earlier than created_at")
        if self.iteration_count > self.limits.max_iterations:
            raise ValueError("iteration_count must not exceed max_iterations")
        if self.tool_call_count > self.limits.max_tool_calls:
            raise ValueError("tool_call_count must not exceed max_tool_calls")
        if (self.status is RunStatus.SUCCEEDED) is (self.final_result is None):
            raise ValueError("only succeeded runs require a final_result")
        if (self.status is RunStatus.FAILED) is (self.error is None):
            raise ValueError("only failed runs require an error")
        return self


class AgentRunDetail(ContractModel):
    """Run snapshot plus its ordered, safe phase history."""

    run: AgentRun
    steps: tuple[AgentStep, ...] = ()
    reviews: tuple[HumanReview, ...] = ()

    @model_validator(mode="after")
    def nested_records_belong_to_run(self) -> AgentRunDetail:
        """Reject mixed-run or ambiguously ordered aggregate snapshots."""
        step_ids = [step.id for step in self.steps]
        sequences = [step.sequence for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step identifiers must be unique")
        if len(sequences) != len(set(sequences)) or sequences != sorted(sequences):
            raise ValueError("step sequences must be unique and ordered")
        if any(step.run_id != self.run.id for step in self.steps):
            raise ValueError("every step must belong to the containing run")
        review_ids = [review.id for review in self.reviews]
        if len(review_ids) != len(set(review_ids)):
            raise ValueError("review identifiers must be unique")
        known_steps = set(step_ids)
        for review in self.reviews:
            if review.run_id != self.run.id or review.tool_call.run_id != self.run.id:
                raise ValueError("every review must belong to the containing run")
            if review.step_id not in known_steps or review.tool_call.step_id != review.step_id:
                raise ValueError("every review must reference its containing run step")
        return self


class AgentRunEvent(ContractModel):
    """One safe, append-only progress event suitable for resumable clients."""

    id: int = Field(ge=1)
    run_id: UUID
    run_version: int = Field(ge=0)
    event_type: Identifier
    status: RunStatus
    occurred_at: AwareDatetime
    step_id: UUID | None = None
    step_phase: StepPhase | None = None
    step_status: StepStatus | None = None


class AgentRunEventPage(ContractModel):
    """Bounded cursor page of safe progress events."""

    items: tuple[AgentRunEvent, ...]
    next_cursor: int = Field(ge=0)
    terminal: bool
