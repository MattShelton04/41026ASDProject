"""Domain-neutral contracts for the Release 2 Multi-Agent Server (ADR-047).

A feature registers one declarative :class:`WorkflowTemplate`. The server coordinates a Planner,
a Worker and a Reviewer over that template and stops at ``awaiting_human`` until a person records
a :class:`HumanDecision`. These models describe the template, the persisted run, its append-only
workflow history and its coordination audit. They carry no feature entities or business rules:
a template names allowlisted tools and declarative checks, and the evidence is whatever those
feature-owned tools return.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator

from shared_contracts.base import ContractModel
from shared_contracts.http import RequestId

MULTI_AGENT_API_PREFIX = "/api/v1/multi-agent"
MULTI_AGENT_SERVICE_NAME = "multi-agent-server"
MULTI_AGENT_TOKEN_HEADER = "Authorization"  # noqa: S105 - header name, not a credential
WORKFLOW_RUN_ID_HEADER = "X-Workflow-Run-ID"
MAX_CORRECTION_ROUNDS = 1
MAX_WORKFLOW_ROUNDS = 1 + MAX_CORRECTION_ROUNDS
MAX_RUN_PAGE_LIMIT = 100
MAX_PLAN_STEPS = 10
MAX_EVIDENCE_EXCERPT_BYTES = 16_384

WorkflowIdentifier = Annotated[
    str, Field(min_length=1, max_length=100, pattern=r"^[a-z0-9][a-z0-9_.-]*$")
]
StepId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")]
InputName = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")]
CheckId = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_.-]*$")]
FieldPath = Annotated[
    str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$")
]
Actor = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[^\x00-\x1f\x7f]+$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ShortText = Annotated[str, Field(min_length=1, max_length=500)]
LongText = Annotated[str, Field(min_length=1, max_length=4_000)]
JsonObject = dict[str, JsonValue]
WorkflowAction = Literal["approve", "correct", "partial", "reject", "cancel"]

_PLACEHOLDER = re.compile(r"\{\{\s*input\.([a-z][a-z0-9_]*)\s*\}\}")


class WorkflowState(StrEnum):
    """Persisted lifecycle of one Planner → Worker → Reviewer → Human workflow run."""

    PLANNING = "planning"
    WORKING = "working"
    REVIEWING = "reviewing"
    AWAITING_HUMAN = "awaiting_human"
    APPROVED = "approved"
    CORRECTED = "corrected"
    PARTIALLY_ACCEPTED = "partially_accepted"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_WORKFLOW_STATES = frozenset(
    {
        WorkflowState.APPROVED,
        WorkflowState.CORRECTED,
        WorkflowState.PARTIALLY_ACCEPTED,
        WorkflowState.REJECTED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    }
)
ACTIVE_WORKFLOW_STATES = frozenset(
    {WorkflowState.PLANNING, WorkflowState.WORKING, WorkflowState.REVIEWING}
)


class AgentRole(StrEnum):
    """Who acted: one of the three agents, the human reviewer, or the server itself."""

    PLANNER = "planner"
    WORKER = "worker"
    REVIEWER = "reviewer"
    HUMAN = "human"
    SYSTEM = "system"


class FindingSeverity(StrEnum):
    """Reviewer finding severity, ordered from informational to blocking."""

    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


SEVERITY_RANK: dict[FindingSeverity, int] = {
    severity: rank for rank, severity in enumerate(FindingSeverity)
}


class HumanDecisionKind(StrEnum):
    """The four outcomes a human reviewer may record."""

    APPROVE = "approve"
    CORRECT = "correct"
    PARTIAL = "partial"
    REJECT = "reject"


class FindingOutcome(StrEnum):
    """Whether a reviewer check passed against the gathered evidence."""

    PASS = "pass"  # noqa: S105 - check outcome label, not a credential
    FAIL = "fail"
    NOT_EVALUATED = "not_evaluated"


class EvidenceOutcome(StrEnum):
    """Outcome of one Worker tool call (mirrors the shared tool outcome)."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    REJECTED = "rejected"


class AuditEvent(StrEnum):
    """Coordination events written to ``coordination_audit.jsonl``."""

    RUN_CREATED = "run.created"
    HANDOFF = "agent.handoff"
    MODEL_INVOCATION = "model.invocation"
    MODEL_FALLBACK = "model.fallback"
    PLAN_CREATED = "plan.created"
    TOOL_CALL = "tool.call"
    TOOL_REJECTED = "tool.rejected"
    WORKER_COMPLETED = "worker.completed"
    REVIEW_COMPLETED = "review.completed"
    DECISION_RECORDED = "decision.recorded"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"


# --------------------------------------------------------------------------- templates


class WorkflowInputField(ContractModel):
    """One typed input a person (or backend) supplies when starting a workflow."""

    name: InputName
    type: Literal["string", "integer", "number", "boolean"] = "string"
    title: ShortText
    description: str | None = Field(default=None, max_length=1_000)
    required: bool = True
    pattern: str | None = Field(default=None, max_length=200)
    min_length: int | None = Field(default=None, ge=0, le=10_000)
    max_length: int | None = Field(default=None, ge=1, le=10_000)
    minimum: float | None = None
    maximum: float | None = None
    enum: tuple[str, ...] | None = Field(default=None, min_length=1, max_length=50)
    format: Literal["uuid", "date", "date-time", "uri"] | None = None

    @model_validator(mode="after")
    def validate_constraints(self) -> WorkflowInputField:
        """Only meaningful constraints for the declared type are accepted."""
        string_only = (self.pattern, self.min_length, self.max_length, self.enum, self.format)
        if self.type != "string" and any(value is not None for value in string_only):
            raise ValueError("pattern/length/enum/format constraints apply to string inputs")
        if self.type not in {"integer", "number"} and (
            self.minimum is not None or self.maximum is not None
        ):
            raise ValueError("minimum/maximum apply to numeric inputs")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as exc:
                raise ValueError("input pattern is not a valid regular expression") from exc
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("min_length cannot exceed max_length")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("minimum cannot exceed maximum")
        return self

    def json_schema(self) -> JsonObject:
        """Project the field onto a JSON Schema property for clients and validation."""
        schema: JsonObject = {"type": self.type, "title": self.title}
        if self.description:
            schema["description"] = self.description
        for key, value in (
            ("pattern", self.pattern),
            ("minLength", self.min_length),
            ("maxLength", self.max_length),
            ("minimum", self.minimum),
            ("maximum", self.maximum),
            ("format", self.format),
        ):
            if value is not None:
                schema[key] = value
        if self.type == "string" and self.max_length is None:
            schema["maxLength"] = 1_000
        if self.enum is not None:
            schema["enum"] = list(self.enum)
        return schema


class WorkflowStep(ContractModel):
    """A declarative evidence step: one allowlisted read-only tool and its arguments.

    String argument values may reference workflow inputs with ``{{input.<name>}}``. A value
    that is exactly one placeholder keeps the input's JSON type; an optional input that was not
    supplied removes the argument.
    """

    id: StepId
    title: ShortText
    purpose: LongText
    tool: WorkflowIdentifier
    arguments: JsonObject = Field(default_factory=dict, max_length=20)
    required: bool = True


class ReviewerCheckRule(ContractModel):
    """A deterministic rule the Reviewer evaluates against Worker evidence.

    ``all_steps_succeeded`` needs nothing else; ``step_succeeded`` needs ``step``;
    ``field_present`` needs ``step`` and ``path``; ``field_compare`` needs ``step``, ``path``,
    ``operator`` and ``value``; ``min_items`` needs ``step``, ``path`` and an integer ``value``.
    ``path`` is a dot-separated path into the tool result (numeric segments index arrays).
    """

    kind: Literal[
        "all_steps_succeeded", "step_succeeded", "field_present", "field_compare", "min_items"
    ]
    step: StepId | None = None
    path: FieldPath | None = None
    operator: Literal["eq", "ne", "gt", "ge", "lt", "le", "in", "not_in", "contains"] | None = None
    value: JsonValue = None

    @model_validator(mode="after")
    def validate_shape(self) -> ReviewerCheckRule:
        """Each rule kind accepts exactly the parameters it evaluates."""
        needs_step = self.kind != "all_steps_succeeded"
        needs_path = self.kind in {"field_present", "field_compare", "min_items"}
        needs_operator = self.kind == "field_compare"
        if needs_step != (self.step is not None):
            raise ValueError(f"{self.kind} {'requires' if needs_step else 'forbids'} step")
        if needs_path != (self.path is not None):
            raise ValueError(f"{self.kind} {'requires' if needs_path else 'forbids'} path")
        if needs_operator != (self.operator is not None):
            raise ValueError(f"{self.kind} {'requires' if needs_operator else 'forbids'} operator")
        if self.kind == "min_items" and (
            not isinstance(self.value, int) or isinstance(self.value, bool) or self.value < 0
        ):
            raise ValueError("min_items requires a non-negative integer value")
        if self.kind in {"all_steps_succeeded", "step_succeeded", "field_present"} and (
            self.value is not None
        ):
            raise ValueError(f"{self.kind} forbids value")
        if self.operator in {"in", "not_in"} and not isinstance(self.value, list):
            raise ValueError("in/not_in operators require a list value")
        return self


class ReviewerCheck(ContractModel):
    """One named reviewer check: the rule, how serious a failure is, and what to do."""

    id: CheckId
    description: LongText
    severity: FindingSeverity
    recommendation: LongText
    rule: ReviewerCheckRule


class WorkflowTemplate(ContractModel):
    """A feature's versioned, declarative multi-agent workflow manifest."""

    schema_version: Literal[1] = 1
    id: WorkflowIdentifier
    version: WorkflowIdentifier
    feature_id: WorkflowIdentifier
    title: ShortText
    objective: LongText
    description: str | None = Field(default=None, max_length=4_000)
    inputs: tuple[WorkflowInputField, ...] = Field(default=(), max_length=10)
    planner_guidance: LongText
    allowed_tools: tuple[WorkflowIdentifier, ...] = Field(min_length=1, max_length=10)
    steps: tuple[WorkflowStep, ...] = Field(min_length=1, max_length=MAX_PLAN_STEPS)
    reviewer_checks: tuple[ReviewerCheck, ...] = Field(min_length=1, max_length=20)
    human_review_guidance: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_references(self) -> WorkflowTemplate:
        """Keep tool, step, input and check references internally consistent."""
        _require_unique("allowed tool", self.allowed_tools)
        _require_unique("input", (field.name for field in self.inputs))
        _require_unique("step", (step.id for step in self.steps))
        _require_unique("reviewer check", (check.id for check in self.reviewer_checks))
        allowed = set(self.allowed_tools)
        inputs = {field.name for field in self.inputs}
        steps = {step.id for step in self.steps}
        for step in self.steps:
            if step.tool not in allowed:
                raise ValueError(f"step {step.id} uses tool {step.tool} outside allowed_tools")
            for name in _placeholders(step.arguments):
                if name not in inputs:
                    raise ValueError(f"step {step.id} references undeclared input {name}")
        for check in self.reviewer_checks:
            if check.rule.step is not None and check.rule.step not in steps:
                raise ValueError(f"check {check.id} references unknown step {check.rule.step}")
            for name in _placeholders(check.rule.value):
                if name not in inputs:
                    raise ValueError(f"check {check.id} references undeclared input {name}")
        return self

    def input_schema(self) -> JsonObject:
        """Return the closed JSON Schema object that run inputs must satisfy."""
        return {
            "type": "object",
            "properties": {field.name: field.json_schema() for field in self.inputs},
            "required": [field.name for field in self.inputs if field.required],
            "additionalProperties": False,
        }


class WorkflowToolDescriptor(ContractModel):
    """What the server knows about one allowlisted tool at runtime."""

    name: WorkflowIdentifier
    description: str | None = Field(default=None, max_length=1_000)
    side_effect: str | None = Field(default=None, max_length=50)
    available: bool


class WorkflowTemplateDescriptor(ContractModel):
    """A registered template plus its derived input schema and tool availability."""

    template: WorkflowTemplate
    input_schema: JsonObject
    tools: tuple[WorkflowToolDescriptor, ...]
    source: str | None = Field(default=None, max_length=500)


class WorkflowTemplateList(ContractModel):
    """Every registered template, in stable feature/template order."""

    items: tuple[WorkflowTemplateDescriptor, ...]
    count: int = Field(ge=0)


# --------------------------------------------------------------------------- run content


class ModelAttribution(ContractModel):
    """Which provider, model and prompt version produced an agent's output."""

    role: AgentRole
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    prompt_id: WorkflowIdentifier
    prompt_version: WorkflowIdentifier
    prompt_hash: Sha256
    invocations: int = Field(default=1, ge=0, le=5)
    fallback: bool = False


class PlanStep(ContractModel):
    """One step of the Planner's plan: the evidence to gather and why."""

    id: StepId
    index: int = Field(ge=1, le=MAX_PLAN_STEPS)
    title: ShortText
    purpose: LongText
    tool: WorkflowIdentifier
    arguments: JsonObject = Field(default_factory=dict, max_length=20)
    required: bool = True
    expected_evidence: str | None = Field(default=None, max_length=1_000)


class WorkflowPlan(ContractModel):
    """The Planner's plan: summary, ordered steps and the evidence it names."""

    summary: LongText
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=MAX_PLAN_STEPS)
    evidence_needed: tuple[ShortText, ...] = Field(min_length=1, max_length=MAX_PLAN_STEPS)
    produced_by: ModelAttribution

    @model_validator(mode="after")
    def validate_steps(self) -> WorkflowPlan:
        """Plans are ordered and uniquely identified so evidence can reference them."""
        _require_unique("plan step", (step.id for step in self.steps))
        if [step.index for step in self.steps] != list(range(1, len(self.steps) + 1)):
            raise ValueError("plan step indexes must be 1..n in order")
        return self


class EvidenceReference(ContractModel):
    """One tool call the Worker made, with a digest that pins the exact result."""

    id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^ev-[a-z0-9_-]+$")]
    step_id: StepId
    tool_name: WorkflowIdentifier
    tool_version: WorkflowIdentifier
    arguments: JsonObject = Field(default_factory=dict, max_length=20)
    outcome: EvidenceOutcome
    transport: Literal["mcp", "http", "fake", "none"]
    result_digest: Sha256
    duration_ms: int = Field(ge=0)
    excerpt: JsonObject = Field(default_factory=dict)
    excerpt_truncated: bool = False
    error_code: str | None = Field(default=None, max_length=100)
    error_message: str | None = Field(default=None, max_length=500)
    tool_call_id: UUID

    @model_validator(mode="after")
    def validate_error(self) -> EvidenceReference:
        """A failed call names its error; a successful call does not."""
        if (self.outcome is EvidenceOutcome.SUCCEEDED) == (self.error_code is not None):
            raise ValueError("error_code must be present exactly when the call did not succeed")
        return self


class WorkerStepResult(ContractModel):
    """The Worker's findings for one plan step."""

    step_id: StepId
    status: Literal["completed", "failed", "skipped"]
    findings: tuple[Annotated[str, Field(min_length=1, max_length=1_000)], ...] = Field(
        max_length=20
    )
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=10)


class WorkerOutput(ContractModel):
    """Everything the Worker produced in one round."""

    round: int = Field(ge=1, le=MAX_WORKFLOW_ROUNDS)
    summary: LongText
    steps: tuple[WorkerStepResult, ...] = Field(min_length=1, max_length=MAX_PLAN_STEPS)
    evidence: tuple[EvidenceReference, ...] = Field(max_length=MAX_PLAN_STEPS * 2)
    correction_note: str | None = Field(default=None, max_length=2_000)
    produced_by: ModelAttribution

    @model_validator(mode="after")
    def validate_evidence_links(self) -> WorkerOutput:
        """Step findings may only cite evidence that exists in this output."""
        ids = {evidence.id for evidence in self.evidence}
        _require_unique("evidence", (evidence.id for evidence in self.evidence))
        for step in self.steps:
            missing = set(step.evidence_ids) - ids
            if missing:
                raise ValueError(f"step {step.step_id} cites unknown evidence")
        return self


class ReviewFinding(ContractModel):
    """One Reviewer finding with severity, recommendation and evidence references."""

    id: Annotated[str, Field(min_length=1, max_length=100, pattern=r"^f-[a-z0-9_.-]+$")]
    check_id: CheckId | None = None
    severity: FindingSeverity
    outcome: FindingOutcome
    message: LongText
    recommendation: str | None = Field(default=None, max_length=4_000)
    evidence_ids: tuple[str, ...] = Field(default=(), max_length=10)
    step_ids: tuple[StepId, ...] = Field(default=(), max_length=MAX_PLAN_STEPS)
    source: Literal["check", "model"] = "check"


class ReviewReport(ContractModel):
    """The Reviewer's assessment of one Worker round."""

    round: int = Field(ge=1, le=MAX_WORKFLOW_ROUNDS)
    summary: LongText
    recommendation: HumanDecisionKind
    findings: tuple[ReviewFinding, ...] = Field(max_length=40)
    produced_by: ModelAttribution

    @model_validator(mode="after")
    def validate_findings(self) -> ReviewReport:
        """Finding identifiers are unique within one report."""
        _require_unique("finding", (finding.id for finding in self.findings))
        return self

    def failed_counts(self) -> dict[str, int]:
        """Count failed findings by severity for summaries."""
        counts = {severity.value: 0 for severity in FindingSeverity}
        for finding in self.findings:
            if finding.outcome is FindingOutcome.FAIL:
                counts[finding.severity.value] += 1
        return counts


class WorkflowAttempt(ContractModel):
    """A Worker/Reviewer round that a human correction superseded."""

    round: int = Field(ge=1, le=MAX_WORKFLOW_ROUNDS)
    worker_output: WorkerOutput
    review: ReviewReport


class HumanDecisionRequest(ContractModel):
    """Body of ``POST /runs/{run_id}/decision``."""

    decision: HumanDecisionKind
    note: str = Field(default="", max_length=2_000)
    actor: Actor
    accepted_step_ids: tuple[StepId, ...] = Field(default=(), max_length=MAX_PLAN_STEPS)

    @field_validator("note")
    @classmethod
    def strip_note(cls, value: str) -> str:
        """Notes are free text; surrounding whitespace carries no meaning."""
        return value.strip()

    @model_validator(mode="after")
    def validate_decision(self) -> HumanDecisionRequest:
        """Corrections, partial acceptance and rejection must say why."""
        if self.decision is not HumanDecisionKind.APPROVE and not self.note:
            raise ValueError(f"a {self.decision.value} decision requires a note")
        if (self.decision is HumanDecisionKind.PARTIAL) != bool(self.accepted_step_ids):
            raise ValueError("accepted_step_ids are required for, and only for, partial")
        _require_unique("accepted step", self.accepted_step_ids)
        return self


class HumanDecision(HumanDecisionRequest):
    """A recorded human decision and the state it moved the run to."""

    round: int = Field(ge=1, le=MAX_WORKFLOW_ROUNDS)
    decided_at: AwareDatetime
    resulting_state: WorkflowState
    request_id: RequestId | None = None


class StageRecord(ContractModel):
    """One entry in the run's stage timeline (for live progress views)."""

    stage: AgentRole
    round: int = Field(ge=1, le=MAX_WORKFLOW_ROUNDS)
    status: Literal["running", "completed", "failed", "cancelled"]
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    detail: str | None = Field(default=None, max_length=500)


class WorkflowError(ContractModel):
    """Safe failure description for a run that ended in ``failed``."""

    code: WorkflowIdentifier
    message: str = Field(min_length=1, max_length=500)
    stage: AgentRole | None = None


class WorkflowRunRequest(ContractModel):
    """Body of ``POST /runs``."""

    template_id: WorkflowIdentifier
    input: JsonObject = Field(default_factory=dict, max_length=20)
    requested_by: Actor | None = None


class WorkflowRun(ContractModel):
    """The complete persisted state of one workflow run."""

    id: UUID
    template_id: WorkflowIdentifier
    template_version: WorkflowIdentifier
    feature_id: WorkflowIdentifier
    state: WorkflowState
    round: int = Field(ge=1, le=MAX_WORKFLOW_ROUNDS)
    input: JsonObject = Field(default_factory=dict)
    requested_by: Actor
    request_id: RequestId
    provider_mode: Literal["deterministic", "model"]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    plan: WorkflowPlan | None = None
    worker_output: WorkerOutput | None = None
    review: ReviewReport | None = None
    superseded: tuple[WorkflowAttempt, ...] = Field(default=(), max_length=MAX_CORRECTION_ROUNDS)
    decisions: tuple[HumanDecision, ...] = Field(default=(), max_length=MAX_WORKFLOW_ROUNDS)
    stages: tuple[StageRecord, ...] = Field(default=(), max_length=20)
    error: WorkflowError | None = None
    available_actions: tuple[WorkflowAction, ...] = ()

    @model_validator(mode="after")
    def validate_lifecycle(self) -> WorkflowRun:
        """Reject snapshots whose content contradicts their state."""
        terminal = self.state in TERMINAL_WORKFLOW_STATES
        if terminal != (self.completed_at is not None):
            raise ValueError("completed_at must be present exactly for terminal runs")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        if (self.state is WorkflowState.FAILED) != (self.error is not None):
            raise ValueError("error must be present exactly for failed runs")
        if self.state is WorkflowState.AWAITING_HUMAN and (
            self.plan is None or self.worker_output is None or self.review is None
        ):
            raise ValueError("awaiting_human requires a plan, worker output and review")
        if terminal and self.available_actions:
            raise ValueError("terminal runs have no available actions")
        human_states = {
            WorkflowState.APPROVED,
            WorkflowState.CORRECTED,
            WorkflowState.PARTIALLY_ACCEPTED,
            WorkflowState.REJECTED,
        }
        if self.state in human_states and not self.decisions:
            raise ValueError("a human outcome requires a recorded decision")
        return self


class WorkflowRunSummary(ContractModel):
    """Compact run row for listings."""

    id: UUID
    template_id: WorkflowIdentifier
    template_version: WorkflowIdentifier
    feature_id: WorkflowIdentifier
    state: WorkflowState
    round: int = Field(ge=1, le=MAX_WORKFLOW_ROUNDS)
    requested_by: Actor
    provider_mode: Literal["deterministic", "model"]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    recommendation: HumanDecisionKind | None = None
    failed_findings: dict[str, int] = Field(default_factory=dict)
    decision: HumanDecisionKind | None = None


class WorkflowRunPage(ContractModel):
    """Newest-first page of run summaries."""

    items: tuple[WorkflowRunSummary, ...] = Field(max_length=MAX_RUN_PAGE_LIMIT)
    count: int = Field(ge=0, le=MAX_RUN_PAGE_LIMIT)


# --------------------------------------------------------------------------- evidence logs


class WorkflowHistoryEntry(ContractModel):
    """One state transition, as appended to ``workflow_history.jsonl``."""

    sequence: int = Field(ge=1)
    run_id: UUID
    request_id: RequestId
    at: AwareDatetime
    from_state: WorkflowState | None
    to_state: WorkflowState
    round: int = Field(ge=1, le=MAX_WORKFLOW_ROUNDS)
    actor: Actor
    role: AgentRole
    reason: str = Field(min_length=1, max_length=500)


class CoordinationAuditEntry(ContractModel):
    """One coordination event, as appended to ``coordination_audit.jsonl``."""

    sequence: int = Field(ge=1)
    run_id: UUID
    request_id: RequestId
    at: AwareDatetime
    event: AuditEvent
    role: AgentRole
    actor: Actor
    round: int = Field(ge=1, le=MAX_WORKFLOW_ROUNDS)
    detail: JsonObject = Field(default_factory=dict)


class WorkflowRunHistory(ContractModel):
    """Body of ``GET /runs/{run_id}/history``: the run's transitions and audit trail."""

    run_id: UUID
    state: WorkflowState
    history: tuple[WorkflowHistoryEntry, ...]
    audit: tuple[CoordinationAuditEntry, ...]


# --------------------------------------------------------------------------- helpers


def _require_unique(label: str, values: Iterable[object]) -> None:
    seen: set[object] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)


def _placeholders(value: JsonValue) -> set[str]:
    if isinstance(value, str):
        return set(_PLACEHOLDER.findall(value))
    if isinstance(value, list):
        return set().union(*(_placeholders(item) for item in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(_placeholders(item) for item in value.values())) if value else set()
    return set()


class _Missing:
    """Sentinel type for an optional input that was not supplied."""

    def __repr__(self) -> str:
        return "<missing input>"


MISSING_INPUT = _Missing()


def resolve_placeholders(value: JsonValue, inputs: JsonObject) -> JsonValue | _Missing:
    """Substitute ``{{input.<name>}}`` references; return ``MISSING_INPUT`` for an absent input.

    A string that is exactly one placeholder takes the input's JSON value and type. Embedded
    placeholders are rendered as text. Dict entries and list items whose value resolves to an
    absent optional input are removed.
    """
    if isinstance(value, str):
        whole = _PLACEHOLDER.fullmatch(value.strip())
        if whole is not None:
            return inputs.get(whole.group(1), MISSING_INPUT)
        return _PLACEHOLDER.sub(lambda match: str(inputs.get(match.group(1), "")), value)
    if isinstance(value, list):
        items: list[JsonValue] = []
        for item in value:
            resolved = resolve_placeholders(item, inputs)
            if not isinstance(resolved, _Missing):
                items.append(resolved)
        return items
    if isinstance(value, dict):
        entries: dict[str, JsonValue] = {}
        for key, item in value.items():
            resolved = resolve_placeholders(item, inputs)
            if not isinstance(resolved, _Missing):
                entries[key] = resolved
        return entries
    return value
