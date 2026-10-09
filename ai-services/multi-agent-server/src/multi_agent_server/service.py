"""Workflow coordination: Planner → Worker → Reviewer → Human Review.

The service owns every state change. Agents produce content; the service validates the
transition with :mod:`multi_agent_server.state_machine`, persists the snapshot, and records a
history entry and the coordination audit (handoffs, tool calls, model calls, decisions) in the
same transaction.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from multi_agent_server.agents import Planner, Reviewer, StructuredCaller, Worker
from multi_agent_server.errors import (
    AgentStageError,
    CapacityExceededError,
    ConcurrentUpdateError,
    InvalidDecisionError,
    InvalidTransitionError,
    MultiAgentError,
    RunCancelledSignal,
)
from multi_agent_server.execution import StageExecutor
from multi_agent_server.state_machine import (
    available_actions,
    decision_target,
    require_transition,
)
from multi_agent_server.store import AuditDraft, HistoryDraft, WorkflowStore
from multi_agent_server.templates import TemplateRegistry, validate_input
from multi_agent_server.tools import TemplateToolbox, ToolGateway, digest
from shared_contracts.multi_agent import (
    ACTIVE_WORKFLOW_STATES,
    TERMINAL_WORKFLOW_STATES,
    AgentRole,
    AuditEvent,
    HumanDecision,
    HumanDecisionRequest,
    JsonObject,
    ModelAttribution,
    StageRecord,
    WorkflowAttempt,
    WorkflowError,
    WorkflowPlan,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunPage,
    WorkflowRunRequest,
    WorkflowRunSummary,
    WorkflowState,
    WorkflowTemplate,
    WorkflowTemplateDescriptor,
    WorkflowTemplateList,
)

LOGGER = logging.getLogger(__name__)
SERVER_ACTOR = "multi-agent-server"
MAX_SAVE_ATTEMPTS = 3


def _attribution_detail(attribution: ModelAttribution) -> JsonObject:
    return {
        "provider": attribution.provider,
        "model": attribution.model,
        "prompt_id": attribution.prompt_id,
        "prompt_version": attribution.prompt_version,
        "prompt_hash": attribution.prompt_hash,
        "invocations": attribution.invocations,
        "fallback": attribution.fallback,
    }


def _handoff(source: AgentRole, target: AgentRole, **detail: Any) -> AuditDraft:
    return AuditDraft(
        AuditEvent.HANDOFF,
        source,
        source.value if source is not AgentRole.SYSTEM else SERVER_ACTOR,
        {"from": source.value, "to": target.value, **detail},
    )


class WorkflowService:
    """Create, execute, decide, cancel and read workflow runs."""

    def __init__(
        self,
        *,
        registry: TemplateRegistry,
        store: WorkflowStore,
        gateway: ToolGateway,
        caller: StructuredCaller,
        executor: StageExecutor,
    ) -> None:
        self._registry = registry
        self._store = store
        self._gateway = gateway
        self._caller = caller
        self._executor = executor
        self._planner = Planner(caller)
        self._worker = Worker(caller)
        self._reviewer = Reviewer(caller)

    @property
    def registry(self) -> TemplateRegistry:
        return self._registry

    @property
    def store(self) -> WorkflowStore:
        return self._store

    @property
    def gateway(self) -> ToolGateway:
        return self._gateway

    @property
    def provider_mode(self) -> str:
        return self._caller.mode

    def close(self) -> None:
        """Stop background work and close the store."""
        self._executor.shutdown()
        self._store.close()

    # ------------------------------------------------------------------ templates

    def describe_template(self, template_id: str) -> WorkflowTemplateDescriptor:
        """One template with its input schema and live tool availability."""
        entry = self._registry.get(template_id)
        return WorkflowTemplateDescriptor(
            template=entry.template,
            input_schema=entry.template.input_schema(),
            tools=TemplateToolbox(entry.template, self._gateway).descriptors(),
            source=entry.source,
        )

    def describe_templates(self) -> WorkflowTemplateList:
        """Every registered template."""
        items = tuple(self.describe_template(entry.template.id) for entry in self._registry.all())
        return WorkflowTemplateList(items=items, count=len(items))

    # ------------------------------------------------------------------ runs

    def create_run(self, request: WorkflowRunRequest, *, request_id: str) -> WorkflowRun:
        """Validate, persist in ``planning`` and hand the run to the Planner."""
        template = self._registry.get(request.template_id).template
        values = validate_input(template, request.input)
        if not self._executor.has_capacity():
            raise CapacityExceededError("The workflow queue is full; try again shortly")
        now = self._store.now()
        requested_by = request.requested_by or "anonymous"
        run = WorkflowRun(
            id=uuid4(),
            template_id=template.id,
            template_version=template.version,
            feature_id=template.feature_id,
            state=WorkflowState.PLANNING,
            round=1,
            input=values,
            requested_by=requested_by,
            request_id=request_id,
            provider_mode="model" if self._caller.mode == "model" else "deterministic",
            created_at=now,
            updated_at=now,
            stages=(
                StageRecord(stage=AgentRole.PLANNER, round=1, status="running", started_at=now),
            ),
            available_actions=available_actions(WorkflowState.PLANNING),
        )
        self._store.create(
            run,
            history=HistoryDraft(
                None, WorkflowState.PLANNING, SERVER_ACTOR, AgentRole.SYSTEM, "Run accepted"
            ),
            audit=(
                AuditDraft(
                    AuditEvent.RUN_CREATED,
                    AgentRole.SYSTEM,
                    requested_by,
                    {
                        "template_id": template.id,
                        "template_version": template.version,
                        "feature_id": template.feature_id,
                        "input_digest": digest(values),
                        "provider_mode": run.provider_mode,
                        "tool_transport": self._gateway.transport,
                        "requested_by": requested_by,
                    },
                ),
                _handoff(AgentRole.SYSTEM, AgentRole.PLANNER, objective=template.objective),
            ),
        )
        try:
            self._executor.submit(lambda: self._execute(run.id))
        except CapacityExceededError:
            self._fail(run.id, "workflow_capacity_exceeded", "The workflow queue was full")
            raise
        return self.get_run(run.id)

    def get_run(self, run_id: UUID) -> WorkflowRun:
        """The current snapshot."""
        return self._store.get(run_id)[0]

    def list_runs(
        self,
        *,
        template_id: str | None = None,
        feature_id: str | None = None,
        state: str | None = None,
        limit: int = 20,
    ) -> WorkflowRunPage:
        """Newest-first run summaries."""
        runs = self._store.list_runs(
            template_id=template_id, feature_id=feature_id, state=state, limit=limit
        )
        items = tuple(summarize(run) for run in runs)
        return WorkflowRunPage(items=items, count=len(items))

    def history(self, run_id: UUID) -> WorkflowRunHistory:
        """The run's transitions and coordination audit."""
        run = self.get_run(run_id)
        return WorkflowRunHistory(
            run_id=run.id,
            state=run.state,
            history=self._store.history(run_id),
            audit=self._store.audit(run_id),
        )

    def wait(self, run_id: UUID, *, timeout: float = 60.0, interval: float = 0.05) -> WorkflowRun:
        """Poll until no agent is working on the run (or the timeout passes)."""
        deadline = time.monotonic() + timeout
        run = self.get_run(run_id)
        while run.state in ACTIVE_WORKFLOW_STATES and time.monotonic() < deadline:
            time.sleep(interval)
            run = self.get_run(run_id)
        return run

    def decide(
        self, run_id: UUID, request: HumanDecisionRequest, *, request_id: str
    ) -> WorkflowRun:
        """Record the human decision; a first ``correct`` re-runs Worker and Reviewer."""
        for _ in range(MAX_SAVE_ATTEMPTS):
            run, version = self._store.get(run_id)
            if run.state is not WorkflowState.AWAITING_HUMAN:
                raise InvalidTransitionError(
                    run.state.value,
                    "decision",
                    "A decision can be recorded only while the run is awaiting_human "
                    f"(current state: {run.state.value})",
                )
            assert run.plan is not None and run.worker_output is not None
            assert run.review is not None
            unknown = set(request.accepted_step_ids) - {step.id for step in run.plan.steps}
            if unknown:
                raise InvalidDecisionError(
                    f"accepted_step_ids contains unknown plan steps: {', '.join(sorted(unknown))}"
                )
            target = decision_target(request.decision, run.round)
            require_transition(run.state, target)
            rerun = target is WorkflowState.WORKING
            if rerun and not self._executor.has_capacity():
                raise CapacityExceededError("The workflow queue is full; try again shortly")
            now = self._store.now()
            decision = HumanDecision(
                **request.model_dump(),
                round=run.round,
                decided_at=now,
                resulting_state=target,
                request_id=request_id,
            )
            stages = _finish_stage(run.stages, AgentRole.HUMAN, "completed", now, request.decision)
            changes: dict[str, object] = {
                "decisions": (*run.decisions, decision),
                "state": target,
                "updated_at": now,
                "available_actions": available_actions(target),
            }
            if rerun:
                changes.update(
                    round=run.round + 1,
                    superseded=(
                        *run.superseded,
                        WorkflowAttempt(
                            round=run.round, worker_output=run.worker_output, review=run.review
                        ),
                    ),
                    worker_output=None,
                    review=None,
                )
                stages = (
                    *stages,
                    StageRecord(
                        stage=AgentRole.WORKER,
                        round=run.round + 1,
                        status="running",
                        started_at=now,
                    ),
                )
            else:
                changes["completed_at"] = now
            changes["stages"] = stages
            updated = run.evolve(**changes)
            audit = [
                AuditDraft(
                    AuditEvent.DECISION_RECORDED,
                    AgentRole.HUMAN,
                    request.actor,
                    {
                        "decision": request.decision.value,
                        "note": request.note,
                        "accepted_step_ids": list(request.accepted_step_ids),
                        "decided_at": now.isoformat(),
                        "decision_round": run.round,
                        "resulting_state": target.value,
                        "reviewer_recommendation": run.review.recommendation.value,
                    },
                    request_id,
                )
            ]
            if rerun:
                audit.append(
                    AuditDraft(
                        AuditEvent.HANDOFF,
                        AgentRole.HUMAN,
                        request.actor,
                        {"from": "human", "to": "worker", "correction_note": request.note},
                        request_id,
                    )
                )
            try:
                self._store.save(
                    updated,
                    expected_version=version,
                    history=(
                        HistoryDraft(
                            run.state,
                            target,
                            request.actor,
                            AgentRole.HUMAN,
                            f"Human decision: {request.decision.value}"
                            + (
                                " (Worker and Reviewer re-run with the correction)" if rerun else ""
                            ),
                            request_id,
                        ),
                    ),
                    audit=audit,
                )
            except ConcurrentUpdateError:
                continue
            if rerun:
                self._executor.submit(lambda: self._rework(run_id))
            return self.get_run(run_id)
        raise ConcurrentUpdateError("Workflow run was concurrently updated")

    def cancel(self, run_id: UUID, *, actor: str, request_id: str) -> WorkflowRun:
        """Cancel a run that has not finished; running agents stop at their next checkpoint."""
        for _ in range(MAX_SAVE_ATTEMPTS):
            run, version = self._store.get(run_id)
            require_transition(run.state, WorkflowState.CANCELLED)
            now = self._store.now()
            updated = run.evolve(
                state=WorkflowState.CANCELLED,
                updated_at=now,
                completed_at=now,
                available_actions=(),
                stages=_finish_running(run.stages, "cancelled", now),
            )
            try:
                self._store.save(
                    updated,
                    expected_version=version,
                    history=(
                        HistoryDraft(
                            run.state,
                            WorkflowState.CANCELLED,
                            actor,
                            AgentRole.HUMAN,
                            "Cancelled on request",
                            request_id,
                        ),
                    ),
                    audit=(
                        AuditDraft(
                            AuditEvent.RUN_CANCELLED,
                            AgentRole.HUMAN,
                            actor,
                            {"previous_state": run.state.value},
                            request_id,
                        ),
                    ),
                )
            except ConcurrentUpdateError:
                continue
            return updated
        raise ConcurrentUpdateError("Workflow run was concurrently updated")

    def recover_interrupted(self) -> int:
        """Fail runs whose agents were interrupted by a previous server stop."""
        recovered = 0
        for run in self._store.active_runs():
            self._fail(
                run.id,
                "interrupted",
                "The server stopped while agents were working; start a new run",
            )
            recovered += 1
        return recovered

    # ------------------------------------------------------------------ execution

    def _execute(self, run_id: UUID) -> None:
        stage = AgentRole.PLANNER
        try:
            run = self.get_run(run_id)
            if run.state is not WorkflowState.PLANNING:
                return
            template = self._registry.get(run.template_id).template
            toolbox = TemplateToolbox(template, self._gateway)
            plan = self._planner.plan(
                run_id=run_id,
                template=template,
                inputs=run.input,
                toolbox=toolbox,
                audit=self._audit_sink(run_id),
            )
            self._advance(
                run_id,
                expected=WorkflowState.PLANNING,
                target=WorkflowState.WORKING,
                role=AgentRole.PLANNER,
                reason=f"Planner produced {len(plan.steps)} step(s); handed to Worker",
                changes={"plan": plan},
                start=AgentRole.WORKER,
                audit=(
                    AuditDraft(
                        AuditEvent.PLAN_CREATED,
                        AgentRole.PLANNER,
                        "planner",
                        {
                            "steps": [
                                {"id": step.id, "tool": step.tool, "arguments": step.arguments}
                                for step in plan.steps
                            ],
                            "evidence_needed": list(plan.evidence_needed),
                            **_attribution_detail(plan.produced_by),
                        },
                    ),
                    _handoff(AgentRole.PLANNER, AgentRole.WORKER, steps=len(plan.steps)),
                ),
            )
            stage = AgentRole.WORKER
            self._work_and_review(run_id, template, plan, None)
        except RunCancelledSignal:
            return
        except AgentStageError as exc:
            self._fail(run_id, exc.code, exc.message, stage)
        except Exception:
            LOGGER.exception("Workflow run failed", extra={"run_id": str(run_id)})
            self._fail(run_id, "internal_error", "The workflow failed unexpectedly", stage)

    def _rework(self, run_id: UUID) -> None:
        try:
            run = self.get_run(run_id)
            if run.state is not WorkflowState.WORKING or run.plan is None:
                return
            template = self._registry.get(run.template_id).template
            note = run.decisions[-1].note if run.decisions else None
            self._work_and_review(run_id, template, run.plan, note)
        except RunCancelledSignal:
            return
        except AgentStageError as exc:
            self._fail(run_id, exc.code, exc.message)
        except Exception:
            LOGGER.exception("Workflow correction failed", extra={"run_id": str(run_id)})
            self._fail(run_id, "internal_error", "The workflow failed unexpectedly")

    def _work_and_review(
        self, run_id: UUID, template: WorkflowTemplate, plan: WorkflowPlan, note: str | None
    ) -> None:
        run = self.get_run(run_id)
        toolbox = TemplateToolbox(template, self._gateway)
        audit = self._audit_sink(run_id)
        worker_output, invocations = self._worker.work(
            run_id=run_id,
            request_id=run.request_id,
            round_number=run.round,
            template=template,
            plan=plan,
            toolbox=toolbox,
            correction_note=note,
            audit=audit,
            ensure_active=lambda: self._ensure_state(run_id, WorkflowState.WORKING),
        )
        succeeded = sum(1 for step in worker_output.steps if step.status == "completed")
        self._advance(
            run_id,
            expected=WorkflowState.WORKING,
            target=WorkflowState.REVIEWING,
            role=AgentRole.WORKER,
            reason=f"Worker gathered evidence for {succeeded}/{len(plan.steps)} step(s)",
            changes={"worker_output": worker_output},
            start=AgentRole.REVIEWER,
            audit=(
                AuditDraft(
                    AuditEvent.WORKER_COMPLETED,
                    AgentRole.WORKER,
                    "worker",
                    {
                        "steps_completed": succeeded,
                        "steps_total": len(plan.steps),
                        "evidence_ids": [item.id for item in worker_output.evidence],
                        "correction_note": note,
                        **_attribution_detail(worker_output.produced_by),
                    },
                ),
                _handoff(AgentRole.WORKER, AgentRole.REVIEWER),
            ),
        )
        review = self._reviewer.review(
            run_id=run_id,
            round_number=run.round,
            template=template,
            inputs=run.input,
            plan=plan,
            worker_output=worker_output,
            invocations=invocations,
            correction_note=note,
            audit=audit,
        )
        self._advance(
            run_id,
            expected=WorkflowState.REVIEWING,
            target=WorkflowState.AWAITING_HUMAN,
            role=AgentRole.REVIEWER,
            reason=f"Reviewer recommends {review.recommendation.value}; awaiting human decision",
            changes={"review": review},
            start=AgentRole.HUMAN,
            audit=(
                AuditDraft(
                    AuditEvent.REVIEW_COMPLETED,
                    AgentRole.REVIEWER,
                    "reviewer",
                    {
                        "recommendation": review.recommendation.value,
                        "failed_findings": dict(review.failed_counts()),
                        "findings": len(review.findings),
                        **_attribution_detail(review.produced_by),
                    },
                ),
                _handoff(AgentRole.REVIEWER, AgentRole.HUMAN),
            ),
        )

    def _audit_sink(self, run_id: UUID) -> Callable[[AuditEvent, AgentRole, JsonObject], None]:
        def sink(event: AuditEvent, role: AgentRole, detail: JsonObject) -> None:
            run = self.get_run(run_id)
            self._store.append_audit(run, (AuditDraft(event, role, role.value, detail),))

        return sink

    def _ensure_state(self, run_id: UUID, expected: WorkflowState) -> None:
        run = self.get_run(run_id)
        if run.state is WorkflowState.CANCELLED:
            raise RunCancelledSignal
        if run.state is not expected:
            raise InvalidTransitionError(run.state.value, expected.value)

    def _advance(
        self,
        run_id: UUID,
        *,
        expected: WorkflowState,
        target: WorkflowState,
        role: AgentRole,
        reason: str,
        changes: Mapping[str, object],
        start: AgentRole,
        audit: Sequence[AuditDraft],
    ) -> WorkflowRun:
        for _ in range(MAX_SAVE_ATTEMPTS):
            run, version = self._store.get(run_id)
            if run.state is WorkflowState.CANCELLED:
                raise RunCancelledSignal
            if run.state is not expected:
                raise InvalidTransitionError(run.state.value, target.value)
            require_transition(run.state, target)
            now = self._store.now()
            stages = (
                *_finish_stage(run.stages, role, "completed", now),
                StageRecord(stage=start, round=run.round, status="running", started_at=now),
            )
            updated = run.evolve(
                **changes,
                state=target,
                updated_at=now,
                stages=stages,
                available_actions=available_actions(target),
            )
            try:
                self._store.save(
                    updated,
                    expected_version=version,
                    history=(HistoryDraft(run.state, target, role.value, role, reason),),
                    audit=audit,
                )
            except ConcurrentUpdateError:
                continue
            return updated
        raise ConcurrentUpdateError("Workflow run was concurrently updated")

    def _fail(self, run_id: UUID, code: str, message: str, stage: AgentRole | None = None) -> None:
        for _ in range(MAX_SAVE_ATTEMPTS):
            try:
                run, version = self._store.get(run_id)
            except MultiAgentError:
                LOGGER.exception("Could not load a failing workflow run")
                return
            if run.state in TERMINAL_WORKFLOW_STATES or run.state not in ACTIVE_WORKFLOW_STATES:
                return
            now = self._store.now()
            updated = run.evolve(
                state=WorkflowState.FAILED,
                updated_at=now,
                completed_at=now,
                available_actions=(),
                error=WorkflowError(code=code, message=message[:500], stage=stage),
                stages=_finish_running(run.stages, "failed", now),
            )
            try:
                self._store.save(
                    updated,
                    expected_version=version,
                    history=(
                        HistoryDraft(
                            run.state, WorkflowState.FAILED, SERVER_ACTOR, AgentRole.SYSTEM, message
                        ),
                    ),
                    audit=(
                        AuditDraft(
                            AuditEvent.RUN_FAILED,
                            AgentRole.SYSTEM,
                            SERVER_ACTOR,
                            {"code": code, "stage": stage.value if stage else None},
                        ),
                    ),
                )
            except ConcurrentUpdateError:
                continue
            except MultiAgentError:
                LOGGER.exception("Could not record a workflow failure")
            return


def _finish_stage(
    stages: Sequence[StageRecord],
    role: AgentRole,
    status: str,
    at: datetime,
    detail: str | None = None,
) -> tuple[StageRecord, ...]:
    result = list(stages)
    for index in range(len(result) - 1, -1, -1):
        if result[index].stage is role and result[index].status == "running":
            result[index] = result[index].evolve(status=status, completed_at=at, detail=detail)
            break
    return tuple(result)


def _finish_running(
    stages: Sequence[StageRecord], status: str, at: datetime
) -> tuple[StageRecord, ...]:
    return tuple(
        stage.evolve(status=status, completed_at=at) if stage.status == "running" else stage
        for stage in stages
    )


def summarize(run: WorkflowRun) -> WorkflowRunSummary:
    """Compact listing row for a run."""
    return WorkflowRunSummary(
        id=run.id,
        template_id=run.template_id,
        template_version=run.template_version,
        feature_id=run.feature_id,
        state=run.state,
        round=run.round,
        requested_by=run.requested_by,
        provider_mode=run.provider_mode,
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        recommendation=run.review.recommendation if run.review else None,
        failed_findings=run.review.failed_counts() if run.review else {},
        decision=run.decisions[-1].decision if run.decisions else None,
    )
