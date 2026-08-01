"""Persistence-independent ports implemented by service-layer adapters."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import Field, JsonValue

from agent_core.models import CoreModel
from shared_contracts import (
    AgentRun,
    AgentRunDetail,
    AgentStep,
    HumanReview,
    Observation,
    Plan,
    ToolCall,
    ToolDefinition,
    ToolResult,
)


class ModelRole(StrEnum):
    """Logical role requesting structured model output."""

    PLANNER = "planner"
    ADAPTER = "adapter"
    REVIEWER = "reviewer"


class ModelMessage(CoreModel):
    """One provider-neutral chat message."""

    role: str = Field(pattern=r"^(system|user|assistant)$")
    content: str = Field(min_length=1, max_length=100_000)


class StructuredModelRequest(CoreModel):
    """Provider-neutral request for JSON-schema-constrained output."""

    run_id: UUID
    role: ModelRole
    model_profile: str = Field(min_length=1, max_length=100)
    messages: tuple[ModelMessage, ...] = Field(min_length=1, max_length=50)
    output_schema: dict[str, JsonValue]
    prompt_id: str = Field(min_length=1, max_length=100)
    prompt_version: str = Field(min_length=1, max_length=100)
    prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rendered_input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=1_024, ge=1, le=32_768)
    repair_attempt: int = Field(default=0, ge=0, le=1)


class ModelMetrics(CoreModel):
    """Portable timings and counts reported for one model invocation."""

    total_duration_ms: int = Field(ge=0)
    load_duration_ms: int | None = Field(default=None, ge=0)
    prompt_eval_duration_ms: int | None = Field(default=None, ge=0)
    eval_duration_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class StructuredModelResult(CoreModel):
    """Structured provider response plus reproducibility metadata."""

    content: dict[str, JsonValue]
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    model_digest: str | None = Field(default=None, max_length=200)
    metrics: ModelMetrics


class ProviderHealth(CoreModel):
    """Non-throwing provider readiness snapshot."""

    reachable: bool
    detail: str = Field(min_length=1, max_length=500)


class StoreHealth(CoreModel):
    """Non-throwing state-store readiness snapshot."""

    ready: bool
    detail: str = Field(min_length=1, max_length=500)


class LLMProvider(Protocol):
    """Port for structured generation and readiness without provider SDK leakage."""

    def generate_structured(self, request: StructuredModelRequest) -> StructuredModelResult:
        """Generate one structured response or raise a typed provider error."""
        ...

    def health(self) -> ProviderHealth:
        """Return provider reachability without raising transport errors."""
        ...


class ToolExecutor(Protocol):
    """Port for invoking a validated, allowlisted feature-owned tool."""

    def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
        """Execute within the definition timeout and return a safe result."""
        ...


class PromptBuilder(Protocol):
    """Port separating versioned prompt rendering from orchestration policy."""

    def build_plan_request(
        self, run: AgentRun, definitions: tuple[ToolDefinition, ...]
    ) -> StructuredModelRequest:
        """Build a schema-constrained planner request."""
        ...

    def build_adaptation_request(
        self,
        run: AgentRun,
        plan: Plan,
        tool_result: ToolResult,
        observation: Observation,
    ) -> StructuredModelRequest:
        """Build a schema-constrained adaptation request."""
        ...


class RunStore(Protocol):
    """Single-owner persistence port with optimistic concurrency."""

    def create(self, run: AgentRun) -> None:
        """Persist a new queued run."""
        ...

    def get(self, run_id: UUID) -> AgentRunDetail | None:
        """Load one run and its ordered safe steps."""
        ...

    def save(
        self,
        run: AgentRun,
        *,
        expected_version: int,
        step: AgentStep | None = None,
        review: HumanReview | None = None,
    ) -> None:
        """Atomically update a run and optionally one step and review."""
        ...

    def request_cancellation(self, run_id: UUID, *, now: datetime) -> AgentRun | None:
        """Idempotently record cancellation intent."""
        ...

    def health(self) -> StoreHealth:
        """Return connectivity and schema readiness without mutation."""
        ...


class RunQueue(Protocol):
    """Small queue seam for a controlled background executor."""

    def enqueue(self, run_id: UUID) -> None:
        """Schedule a persisted run for execution."""
        ...


class Clock(Protocol):
    """Injectable wall clock for deterministic state and timeout tests."""

    def now(self) -> datetime:
        """Return an aware UTC timestamp."""
        ...


class IdGenerator(Protocol):
    """Injectable identifier source."""

    def new(self) -> UUID:
        """Return a globally unique identifier."""
        ...
