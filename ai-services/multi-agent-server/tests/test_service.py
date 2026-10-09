"""Planner → Worker → Reviewer → Human Review coordination, history and audit."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from multi_agent_server.errors import (
    CapacityExceededError,
    ConcurrentUpdateError,
    InvalidDecisionError,
    InvalidTransitionError,
    InvalidWorkflowInputError,
    RunNotFoundError,
    TemplateNotFoundError,
)
from multi_agent_server.execution import BoundedExecutor
from multi_agent_server.service import WorkflowService
from multi_agent_server.store import AUDIT_FILE, HISTORY_FILE
from multi_agent_server.tools import FixtureToolGateway
from shared_contracts import ToolCall, ToolDefinition, ToolResult
from shared_contracts.multi_agent import (
    AgentRole,
    AuditEvent,
    EvidenceOutcome,
    FindingOutcome,
    HumanDecisionKind,
    HumanDecisionRequest,
    WorkflowRunRequest,
    WorkflowState,
)

FIXTURES = Path(__file__).parent / "fixtures"
RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"
TEMPLATE_ID = "example-readiness-review"
Factory = Callable[..., WorkflowService]


def start(service: WorkflowService, **input_values: Any) -> Any:
    return service.create_run(
        WorkflowRunRequest(
            template_id=TEMPLATE_ID,
            input={"record_id": RECORD_ID, **input_values},
            requested_by="tester",
        ),
        request_id="req-start",
    )


def decide(service: WorkflowService, run_id: Any, decision: str, **options: Any) -> Any:
    request = HumanDecisionRequest(
        decision=HumanDecisionKind(decision),
        note=options.pop("note", "" if decision == "approve" else "reason"),
        actor=options.pop("actor", "reviewer@example.org"),
        **options,
    )
    return service.decide(run_id, request, request_id="req-decide")


def gateway_with(**results: dict[str, Any]) -> FixtureToolGateway:
    payload = json.loads((FIXTURES / "tools.json").read_text(encoding="utf-8"))
    definitions = [ToolDefinition.model_validate(entry["definition"]) for entry in payload["tools"]]
    defaults = {entry["definition"]["name"]: entry["result"] for entry in payload["tools"]}
    defaults.update(results)
    return FixtureToolGateway(definitions, defaults)


def test_run_reaches_awaiting_human_with_plan_evidence_and_findings(
    service: WorkflowService,
) -> None:
    run = start(service)

    assert run.state is WorkflowState.AWAITING_HUMAN
    assert run.provider_mode == "deterministic"
    assert [step.id for step in run.plan.steps] == ["record", "quality"]
    assert run.plan.steps[0].arguments == {"record_id": RECORD_ID}
    assert len(run.plan.evidence_needed) == 2
    assert [step.status for step in run.worker_output.steps] == ["completed", "completed"]
    assert {item.outcome for item in run.worker_output.evidence} == {EvidenceOutcome.SUCCEEDED}
    assert run.review.recommendation is HumanDecisionKind.APPROVE
    assert all(item.outcome is FindingOutcome.PASS for item in run.review.findings)
    assert [stage.stage for stage in run.stages] == [
        AgentRole.PLANNER,
        AgentRole.WORKER,
        AgentRole.REVIEWER,
        AgentRole.HUMAN,
    ]
    assert run.stages[-1].status == "running"
    assert run.available_actions == ("approve", "correct", "partial", "reject", "cancel")
    for attribution in (run.plan.produced_by, run.worker_output.produced_by):
        assert attribution.provider == "deterministic"
        assert attribution.prompt_version == "v1"


def test_history_and_audit_are_persisted_and_mirrored_to_jsonl(service: WorkflowService) -> None:
    run = start(service)
    final = decide(service, run.id, "approve")

    history = service.history(run.id)

    assert final.state is WorkflowState.APPROVED
    assert final.completed_at is not None
    assert [(entry.from_state, entry.to_state) for entry in history.history] == [
        (None, WorkflowState.PLANNING),
        (WorkflowState.PLANNING, WorkflowState.WORKING),
        (WorkflowState.WORKING, WorkflowState.REVIEWING),
        (WorkflowState.REVIEWING, WorkflowState.AWAITING_HUMAN),
        (WorkflowState.AWAITING_HUMAN, WorkflowState.APPROVED),
    ]
    assert history.history[-1].actor == "reviewer@example.org"
    assert history.history[-1].request_id == "req-decide"
    events = [entry.event for entry in history.audit]
    assert events[0] is AuditEvent.RUN_CREATED
    assert events.count(AuditEvent.HANDOFF) == 4
    assert events.count(AuditEvent.TOOL_CALL) == 2
    assert events.count(AuditEvent.MODEL_INVOCATION) == 3
    assert events[-1] is AuditEvent.DECISION_RECORDED
    tool_call = next(entry for entry in history.audit if entry.event is AuditEvent.TOOL_CALL)
    assert tool_call.detail["tool_name"] == "example.record.v1"
    assert len(str(tool_call.detail["result_digest"])) == 64
    decision = history.audit[-1]
    assert decision.actor == "reviewer@example.org"
    assert decision.detail["decision"] == "approve"
    assert [entry.sequence for entry in history.audit] == list(range(1, len(history.audit) + 1))
    state = service.store.directory
    history_lines = (state / HISTORY_FILE).read_text(encoding="utf-8").splitlines()
    audit_lines = (state / AUDIT_FILE).read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == len(history.history)
    assert len(audit_lines) == len(history.audit)
    assert json.loads(history_lines[-1])["to_state"] == "approved"


@pytest.mark.parametrize(
    ("decision", "options", "state"),
    [
        ("reject", {}, WorkflowState.REJECTED),
        ("partial", {"accepted_step_ids": ("record",)}, WorkflowState.PARTIALLY_ACCEPTED),
    ],
)
def test_terminal_decisions(
    service: WorkflowService, decision: str, options: dict[str, Any], state: WorkflowState
) -> None:
    run = start(service)
    final = decide(service, run.id, decision, **options)
    assert final.state is state
    assert final.decisions[0].resulting_state is state
    assert final.available_actions == ()
    assert final.stages[-1].status == "completed"


def test_first_correction_reruns_worker_and_reviewer_with_the_note(
    service: WorkflowService,
) -> None:
    run = start(service)

    corrected = decide(service, run.id, "correct", note="Check the status field too")

    assert corrected.state is WorkflowState.AWAITING_HUMAN
    assert corrected.round == 2
    assert corrected.worker_output.correction_note == "Check the status field too"
    assert "Check the status field too" in corrected.worker_output.summary
    assert corrected.review.round == 2
    assert corrected.superseded[0].round == 1
    assert {item.id for item in corrected.worker_output.evidence} == {
        "ev-record-r2",
        "ev-quality-r2",
    }
    assert corrected.decisions[0].resulting_state is WorkflowState.WORKING
    history = service.history(run.id)
    handoffs = [entry for entry in history.audit if entry.event is AuditEvent.HANDOFF]
    assert handoffs[4].detail == {
        "from": "human",
        "to": "worker",
        "correction_note": "Check the status field too",
    }
    approved = decide(service, run.id, "approve")
    assert approved.state is WorkflowState.APPROVED
    assert [decision.round for decision in approved.decisions] == [1, 2]


def test_second_correction_finishes_as_corrected(service: WorkflowService) -> None:
    run = start(service)
    decide(service, run.id, "correct", note="first")

    final = decide(service, run.id, "correct", note="final correction")

    assert final.state is WorkflowState.CORRECTED
    assert final.decisions[-1].note == "final correction"
    assert final.completed_at is not None


def test_decisions_are_rejected_outside_awaiting_human(
    service_factory: Factory, deferred: Any
) -> None:
    service = service_factory(executor=deferred)
    run = start(service)
    assert run.state is WorkflowState.PLANNING
    with pytest.raises(InvalidTransitionError, match="awaiting_human"):
        decide(service, run.id, "approve")
    deferred.run_all()
    decide(service, run.id, "approve")
    with pytest.raises(InvalidTransitionError):
        decide(service, run.id, "approve")


def test_partial_acceptance_names_known_steps(service: WorkflowService) -> None:
    run = start(service)
    with pytest.raises(InvalidDecisionError, match="ghost"):
        decide(service, run.id, "partial", accepted_step_ids=("ghost",))


def test_cancel_stops_queued_and_running_work(service_factory: Factory, deferred: Any) -> None:
    service = service_factory(executor=deferred)
    run = start(service)

    cancelled = service.cancel(run.id, actor="operator", request_id="req-cancel")
    deferred.run_all()

    assert cancelled.state is WorkflowState.CANCELLED
    assert service.get_run(run.id).state is WorkflowState.CANCELLED
    assert service.get_run(run.id).stages[0].status == "cancelled"
    with pytest.raises(InvalidTransitionError):
        service.cancel(run.id, actor="operator", request_id="again")
    events = [entry.event for entry in service.history(run.id).audit]
    assert events[-1] is AuditEvent.RUN_CANCELLED


def test_cancel_during_tool_calls_stops_the_worker(service_factory: Factory) -> None:
    holder: dict[str, WorkflowService] = {}

    class Cancelling(FixtureToolGateway):
        def execute(self, call: ToolCall, definition: ToolDefinition) -> ToolResult:
            holder["service"].cancel(call.run_id, actor="operator", request_id="mid-run")
            return super().execute(call, definition)

    gateway = gateway_with()
    cancelling = Cancelling(
        [gateway.definition(name) for name in ("example.record.v1", "example.quality.v1")],  # type: ignore[misc]
        {"example.record.v1": {}, "example.quality.v1": {}},
    )
    service = service_factory(gateway=cancelling)
    holder["service"] = service

    run = start(service)

    assert run.state is WorkflowState.CANCELLED
    assert len(cancelling.calls) == 1


def test_tool_failures_become_reviewer_findings(service_factory: Factory) -> None:
    service = service_factory(
        gateway=gateway_with(**{"example.quality.v1": {"checks": [], "failed": 2}})
    )

    run = start(service)

    failed = {f.check_id: f for f in run.review.findings if f.outcome is FindingOutcome.FAIL}
    assert set(failed) == {"quality-recorded", "quality-clean"}
    assert run.review.recommendation is HumanDecisionKind.CORRECT
    assert failed["quality-clean"].recommendation.startswith("Resolve")


def test_unknown_template_and_invalid_input_are_structured(service: WorkflowService) -> None:
    with pytest.raises(TemplateNotFoundError):
        service.create_run(WorkflowRunRequest(template_id="nope"), request_id="r")
    with pytest.raises(InvalidWorkflowInputError) as error:
        service.create_run(
            WorkflowRunRequest(template_id=TEMPLATE_ID, input={"record_id": "x", "extra": 1}),
            request_id="r",
        )
    fields = {issue.field for issue in error.value.errors}
    assert "record_id" in fields
    assert service.list_runs().count == 0


def test_capacity_is_checked_before_a_run_is_persisted(
    service_factory: Factory, deferred: Any
) -> None:
    service = service_factory(executor=deferred)
    deferred.capacity = False
    with pytest.raises(CapacityExceededError):
        start(service)
    assert service.list_runs().count == 0


def test_capacity_lost_after_persisting_fails_the_run(service_factory: Factory) -> None:
    class Full:
        def has_capacity(self) -> bool:
            return True

        def submit(self, task: object) -> None:
            raise CapacityExceededError("full")

        def shutdown(self) -> None:
            pass

    service = service_factory(executor=Full())
    with pytest.raises(CapacityExceededError):
        start(service)
    failed = service.list_runs().items[0]
    assert failed.state is WorkflowState.FAILED


def test_correction_requires_capacity(service_factory: Factory, deferred: Any) -> None:
    service = service_factory(executor=deferred)
    run = start(service)
    deferred.run_all()
    deferred.capacity = False
    with pytest.raises(CapacityExceededError):
        decide(service, run.id, "correct")
    assert service.get_run(run.id).state is WorkflowState.AWAITING_HUMAN


def test_recover_interrupted_runs(service_factory: Factory, deferred: Any) -> None:
    service = service_factory(executor=deferred)
    run = start(service)

    assert service.recover_interrupted() == 1

    failed = service.get_run(run.id)
    assert failed.state is WorkflowState.FAILED
    assert failed.error.code == "interrupted"
    deferred.run_all()  # the stale task must not resurrect the run
    assert service.get_run(run.id).state is WorkflowState.FAILED


def test_list_runs_filters_and_summaries(service: WorkflowService) -> None:
    first = start(service)
    decide(service, first.id, "reject")
    start(service)

    page = service.list_runs(template_id=TEMPLATE_ID, limit=10)
    assert page.count == 2
    assert {item.state for item in page.items} == {
        WorkflowState.REJECTED,
        WorkflowState.AWAITING_HUMAN,
    }
    rejected = next(item for item in page.items if item.state is WorkflowState.REJECTED)
    assert rejected.decision is HumanDecisionKind.REJECT
    assert rejected.recommendation is HumanDecisionKind.APPROVE
    assert service.list_runs(feature_id="other").count == 0
    assert service.list_runs(state="rejected").count == 1


def test_missing_runs_raise_not_found(service: WorkflowService) -> None:
    with pytest.raises(RunNotFoundError):
        service.get_run(uuid4())


def test_background_executor_runs_to_awaiting_human(service_factory: Factory) -> None:
    executor = BoundedExecutor(workers=1, capacity=2)
    service = service_factory(executor=executor)

    run = start(service)
    settled = service.wait(run.id, timeout=10)

    assert settled.state is WorkflowState.AWAITING_HUMAN
    corrected = decide(service, run.id, "correct", note="again")
    assert service.wait(corrected.id, timeout=10).round == 2


def test_bounded_executor_rejects_work_beyond_capacity() -> None:
    import threading

    gate = threading.Event()
    executor = BoundedExecutor(workers=1, capacity=1)
    executor.submit(gate.wait)
    assert executor.has_capacity() is False
    with pytest.raises(CapacityExceededError):
        executor.submit(lambda: None)
    gate.set()
    executor.shutdown()
    with pytest.raises(ValueError):
        BoundedExecutor(workers=0, capacity=1)


def test_bounded_executor_survives_task_errors() -> None:
    import threading

    done = threading.Event()
    executor = BoundedExecutor(workers=1, capacity=2)

    def explode() -> None:
        raise RuntimeError("boom")

    executor.submit(explode)
    executor.submit(done.set)
    assert done.wait(5)
    executor.shutdown()


def test_store_rejects_stale_versions(service: WorkflowService) -> None:
    run = start(service)
    snapshot, version = service.store.get(run.id)
    service.store.save(snapshot, expected_version=version)
    with pytest.raises(ConcurrentUpdateError):
        service.store.save(snapshot, expected_version=version)
    assert service.store.health()[0] is True
