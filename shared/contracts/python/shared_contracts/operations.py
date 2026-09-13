"""Safe, domain-neutral contracts for the AI-mode operations interface."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, Field

from shared_contracts.agent import (
    AdaptationDecision,
    ApprovalStatus,
    Identifier,
    JsonObject,
    ReviewDecision,
    RunLimits,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolError,
    ToolOutcome,
)
from shared_contracts.base import ContractModel
from shared_contracts.http import RequestId, Traceparent

DEFAULT_RUN_PAGE_SIZE = 50
MAX_RUN_PAGE_SIZE = 100
MAX_RUN_CURSOR_LENGTH = 512


class EvidenceSource(StrEnum):
    """Origin of evidence displayed by the operations interface."""

    USER = "user"
    ORCHESTRATION = "orchestration"
    MODEL = "model"
    TOOL = "tool"
    HUMAN = "human"


class PlanActionEvidence(ContractModel):
    """Safe, argument-free summary of one planned tool action."""

    sequence: int = Field(ge=1, le=50)
    tool_name: Identifier
    purpose: str = Field(min_length=1, max_length=1_000)


class PlanEvidence(ContractModel):
    """Safe planner output without private reasoning or tool arguments."""

    goal: str = Field(min_length=1, max_length=2_000)
    actions: tuple[PlanActionEvidence, ...] = Field(default=(), max_length=50)
    success_criteria: tuple[str, ...] = Field(default=(), max_length=20)
    risk_level: str | None = Field(default=None, max_length=20)


class ToolCallEvidence(ContractModel):
    """Policy-projected tool request and result evidence."""

    call_id: UUID
    step_id: UUID
    tool_name: Identifier
    tool_version: Identifier
    approval_status: ApprovalStatus
    outcome: ToolOutcome | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    retryable: bool | None = None
    error_code: Identifier | None = None
    evidence_references: tuple[str, ...] = Field(default=(), max_length=20)
    redacted_arguments: JsonObject | None = None
    redacted_result: JsonObject | None = None


class ObservationEvidence(ContractModel):
    """Bounded facts produced from persisted tool evidence."""

    facts: tuple[str, ...] = Field(default=(), max_length=50)
    satisfied_criteria: tuple[str, ...] = Field(default=(), max_length=20)
    unsatisfied_criteria: tuple[str, ...] = Field(default=(), max_length=20)
    unassessed_criteria: tuple[str, ...] = Field(default=(), max_length=20)
    new_constraints: tuple[str, ...] = Field(default=(), max_length=20)


class AdaptationEvidence(ContractModel):
    """Safe post-observation decision and optional projected result."""

    decision: AdaptationDecision
    justification: str = Field(min_length=1, max_length=2_000)
    redacted_final_result: JsonObject | None = None


class ModelMetricsEvidence(ContractModel):
    """Portable model timings and counts safe for developer display."""

    total_duration_ms: int = Field(ge=0)
    load_duration_ms: int | None = Field(default=None, ge=0)
    prompt_eval_duration_ms: int | None = Field(default=None, ge=0)
    eval_duration_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_prompt_tokens: int | None = Field(default=None, ge=0)
    cache_write_prompt_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    retry_count: int = Field(default=0, ge=0, le=5)


class ModelInvocationEvidence(ContractModel):
    """Reproducibility metadata that intentionally excludes prompt content."""

    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    model_digest: str | None = Field(default=None, max_length=200)
    provider_request_id: str | None = Field(default=None, min_length=1, max_length=200)
    prompt_id: Identifier
    prompt_version: Identifier
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rendered_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    repair_count: int = Field(ge=0, le=2)
    provider_retry_count: int = Field(default=0, ge=0, le=1)
    metrics: ModelMetricsEvidence


class AgentStepEvidence(ContractModel):
    """One attributed step in the operations timeline."""

    id: UUID
    sequence: int = Field(ge=1)
    phase: StepPhase
    status: StepStatus
    started_at: AwareDatetime | None = None
    completed_at: AwareDatetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    source: EvidenceSource
    summary: str = Field(min_length=1, max_length=500)
    plan: PlanEvidence | None = None
    tool: ToolCallEvidence | None = None
    tools: tuple[ToolCallEvidence, ...] = ()
    observation: ObservationEvidence | None = None
    adaptation: AdaptationEvidence | None = None
    model_invocation: ModelInvocationEvidence | None = None
    error: ToolError | None = None


class HumanReviewEvidence(ContractModel):
    """Immutable, projected human decision for one protected action."""

    id: UUID
    step_id: UUID
    call_id: UUID
    tool_name: Identifier
    tool_version: Identifier
    approval_status: ApprovalStatus
    decision: ReviewDecision
    reviewer: str = Field(min_length=1, max_length=200)
    comment: str | None = Field(default=None, max_length=2_000)
    reviewed_at: AwareDatetime


class RunCorrelation(ContractModel):
    """Safe identifiers used to correlate a run across service boundaries."""

    request_id: RequestId
    run_id: UUID
    traceparent: Traceparent | None = None
    trace_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    telemetry_url: str | None = Field(default=None, max_length=2_000)


class AgentRunSummary(ContractModel):
    """Compact, safe row returned by the operations run index."""

    id: UUID
    feature_key: Identifier
    objective_preview: str | None = Field(default=None, max_length=160)
    status: RunStatus
    latest_phase: StepPhase | None = None
    latest_step_status: StepStatus | None = None
    model_profile: Identifier
    prompt_set: Identifier
    iteration_count: int = Field(ge=0)
    tool_call_count: int = Field(ge=0)
    version: int = Field(ge=0)
    review_required: bool
    error_code: Identifier | None = None
    created_at: AwareDatetime
    updated_at: AwareDatetime
    duration_ms: int | None = Field(default=None, ge=0)


class AgentRunPage(ContractModel):
    """Stable cursor page of operations summaries."""

    items: tuple[AgentRunSummary, ...] = Field(default=(), max_length=MAX_RUN_PAGE_SIZE)
    next_cursor: str | None = Field(default=None, max_length=MAX_RUN_CURSOR_LENGTH)
    as_of: AwareDatetime


class AgentRunEvidenceDetail(ContractModel):
    """Allowlisted read projection used by the operations interface."""

    run: AgentRunSummary
    objective: str | None = Field(default=None, max_length=4_000)
    limits: RunLimits
    cancel_requested: bool
    final_result: JsonObject | None = None
    error: ToolError | None = None
    steps: tuple[AgentStepEvidence, ...] = Field(default=(), max_length=500)
    reviews: tuple[HumanReviewEvidence, ...] = Field(default=(), max_length=100)
    correlation: RunCorrelation
