"""Multi-Agent Server contracts: templates, runs, decisions and evidence logs (ADR-047)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from shared_contracts.multi_agent import (
    MISSING_INPUT,
    SEVERITY_RANK,
    AgentRole,
    EvidenceOutcome,
    EvidenceReference,
    FindingOutcome,
    FindingSeverity,
    HumanDecision,
    HumanDecisionKind,
    HumanDecisionRequest,
    ModelAttribution,
    PlanStep,
    ReviewerCheckRule,
    ReviewFinding,
    ReviewReport,
    WorkerOutput,
    WorkerStepResult,
    WorkflowError,
    WorkflowInputField,
    WorkflowPlan,
    WorkflowRun,
    WorkflowState,
    WorkflowTemplate,
    resolve_placeholders,
)

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
DIGEST = "0" * 64


def template_payload() -> dict[str, Any]:
    return {
        "id": "demo-review",
        "version": "v1",
        "feature_id": "demo-feature",
        "title": "Demo review",
        "objective": "Review one record using read-only evidence.",
        "inputs": [{"name": "record_id", "title": "Record", "format": "uuid"}],
        "planner_guidance": "Read the record.",
        "allowed_tools": ["demo.record.v1"],
        "steps": [
            {
                "id": "record",
                "title": "Read record",
                "purpose": "Confirm it exists.",
                "tool": "demo.record.v1",
                "arguments": {"record_id": "{{input.record_id}}"},
            }
        ],
        "reviewer_checks": [
            {
                "id": "found",
                "description": "Record found",
                "severity": "critical",
                "recommendation": "Check the ID",
                "rule": {"kind": "step_succeeded", "step": "record"},
            }
        ],
    }


def attribution(role: AgentRole = AgentRole.PLANNER) -> ModelAttribution:
    return ModelAttribution(
        role=role,
        provider="deterministic",
        model="rules",
        prompt_id="planner",
        prompt_version="v1",
        prompt_hash=DIGEST,
    )


def plan() -> WorkflowPlan:
    return WorkflowPlan(
        summary="Plan",
        steps=(PlanStep(id="record", index=1, title="t", purpose="p", tool="demo.record.v1"),),
        evidence_needed=("record",),
        produced_by=attribution(),
    )


def evidence(**changes: Any) -> EvidenceReference:
    values: dict[str, Any] = {
        "id": "ev-record-r1",
        "step_id": "record",
        "tool_name": "demo.record.v1",
        "tool_version": "v1",
        "outcome": EvidenceOutcome.SUCCEEDED,
        "transport": "fake",
        "result_digest": DIGEST,
        "duration_ms": 1,
        "tool_call_id": uuid4(),
    }
    values.update(changes)
    return EvidenceReference(**values)


def worker_output() -> WorkerOutput:
    return WorkerOutput(
        round=1,
        summary="Done",
        steps=(
            WorkerStepResult(
                step_id="record",
                status="completed",
                findings=("ok",),
                evidence_ids=("ev-record-r1",),
            ),
        ),
        evidence=(evidence(),),
        produced_by=attribution(AgentRole.WORKER),
    )


def review() -> ReviewReport:
    return ReviewReport(
        round=1,
        summary="Fine",
        recommendation=HumanDecisionKind.APPROVE,
        findings=(
            ReviewFinding(
                id="f-found",
                check_id="found",
                severity=FindingSeverity.INFO,
                outcome=FindingOutcome.PASS,
                message="Passed",
            ),
            ReviewFinding(
                id="f-model-1",
                severity=FindingSeverity.HIGH,
                outcome=FindingOutcome.FAIL,
                message="Risk",
                source="model",
            ),
        ),
        produced_by=attribution(AgentRole.REVIEWER),
    )


def run(**changes: Any) -> WorkflowRun:
    values: dict[str, Any] = {
        "id": uuid4(),
        "template_id": "demo-review",
        "template_version": "v1",
        "feature_id": "demo-feature",
        "state": WorkflowState.PLANNING,
        "round": 1,
        "requested_by": "tester",
        "request_id": "req-1",
        "provider_mode": "deterministic",
        "created_at": NOW,
        "updated_at": NOW,
        "available_actions": ("cancel",),
    }
    values.update(changes)
    return WorkflowRun(**values)


def test_template_derives_a_closed_input_schema() -> None:
    template = WorkflowTemplate.model_validate(template_payload())

    schema = template.input_schema()

    assert schema["additionalProperties"] is False
    assert schema["required"] == ["record_id"]
    assert schema["properties"] == {
        "record_id": {"type": "string", "title": "Record", "format": "uuid", "maxLength": 1000}
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: p["steps"][0].update(tool="demo.other.v1"), "outside allowed_tools"),
        (
            lambda p: p["steps"][0].update(arguments={"x": "{{input.missing}}"}),
            "undeclared input",
        ),
        (lambda p: p["reviewer_checks"][0]["rule"].update(step="nope"), "unknown step"),
        (lambda p: p["steps"].append(copy.deepcopy(p["steps"][0])), "duplicate step"),
        (lambda p: p["allowed_tools"].append("demo.record.v1"), "duplicate allowed tool"),
        (
            lambda p: p["reviewer_checks"][0]["rule"].update(
                kind="field_compare", path="a", operator="eq", value="{{input.ghost}}"
            ),
            "undeclared input",
        ),
    ],
)
def test_template_rejects_inconsistent_references(mutate: Any, message: str) -> None:
    payload = template_payload()
    mutate(payload)

    with pytest.raises(ValidationError, match=message):
        WorkflowTemplate.model_validate(payload)


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "all_steps_succeeded", "step": "x"},
        {"kind": "step_succeeded"},
        {"kind": "field_present", "step": "x"},
        {"kind": "field_compare", "step": "x", "path": "a"},
        {"kind": "min_items", "step": "x", "path": "a", "value": -1},
        {"kind": "min_items", "step": "x", "path": "a", "value": True},
        {"kind": "step_succeeded", "step": "x", "value": 1},
        {"kind": "field_compare", "step": "x", "path": "a", "operator": "in", "value": 1},
        {"kind": "step_succeeded", "step": "x", "path": "a"},
        {"kind": "field_present", "step": "x", "path": "a", "operator": "eq"},
    ],
)
def test_reviewer_rules_accept_only_their_own_parameters(rule: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        ReviewerCheckRule.model_validate(rule)


@pytest.mark.parametrize(
    "field",
    [
        {"name": "n", "title": "t", "type": "integer", "pattern": "x"},
        {"name": "n", "title": "t", "type": "string", "minimum": 1},
        {"name": "n", "title": "t", "pattern": "("},
        {"name": "n", "title": "t", "min_length": 5, "max_length": 2},
        {"name": "n", "title": "t", "type": "number", "minimum": 5, "maximum": 2},
    ],
)
def test_input_fields_reject_meaningless_constraints(field: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        WorkflowInputField.model_validate(field)


def test_input_field_schema_projection() -> None:
    field = WorkflowInputField(
        name="count",
        type="integer",
        title="Count",
        description="How many",
        minimum=1,
        maximum=5,
    )
    assert field.json_schema() == {
        "type": "integer",
        "title": "Count",
        "description": "How many",
        "minimum": 1,
        "maximum": 5,
    }
    choice = WorkflowInputField(name="mode", title="Mode", enum=("a", "b"), max_length=5)
    assert choice.json_schema()["enum"] == ["a", "b"]


def test_placeholders_keep_types_and_drop_absent_optional_inputs() -> None:
    inputs = {"id": "abc", "limit": 5}
    resolved = resolve_placeholders(
        {
            "id": "{{input.id}}",
            "limit": "{{ input.limit }}",
            "label": "record {{input.id}}",
            "absent": "{{input.missing}}",
            "list": ["{{input.limit}}", "{{input.missing}}", 3],
            "fixed": True,
        },
        inputs,
    )
    assert resolved == {
        "id": "abc",
        "limit": 5,
        "label": "record abc",
        "list": [5, 3],
        "fixed": True,
    }
    assert resolve_placeholders("{{input.missing}}", inputs) is MISSING_INPUT
    assert repr(MISSING_INPUT) == "<missing input>"


def test_decisions_require_reasons_and_partial_step_lists() -> None:
    assert HumanDecisionRequest(decision=HumanDecisionKind.APPROVE, actor="a").note == ""
    assert HumanDecisionRequest(decision="reject", note="  why  ", actor="a").note == "why"
    with pytest.raises(ValidationError, match="requires a note"):
        HumanDecisionRequest(decision="correct", note="   ", actor="a")
    with pytest.raises(ValidationError, match="accepted_step_ids"):
        HumanDecisionRequest(decision="partial", note="some", actor="a")
    with pytest.raises(ValidationError, match="accepted_step_ids"):
        HumanDecisionRequest(decision="approve", actor="a", accepted_step_ids=("x",))
    with pytest.raises(ValidationError, match="duplicate"):
        HumanDecisionRequest(decision="partial", note="n", actor="a", accepted_step_ids=("x", "x"))
    with pytest.raises(ValidationError):
        HumanDecisionRequest(decision="approve", actor="bad\nactor")


def test_plan_steps_are_ordered_and_unique() -> None:
    step = PlanStep(id="a", index=1, title="t", purpose="p", tool="x.v1")
    with pytest.raises(ValidationError, match="indexes"):
        WorkflowPlan(
            summary="s",
            steps=(step.evolve(index=2),),
            evidence_needed=("e",),
            produced_by=attribution(),
        )
    with pytest.raises(ValidationError, match="duplicate"):
        WorkflowPlan(
            summary="s",
            steps=(step, step.evolve(index=2)),
            evidence_needed=("e",),
            produced_by=attribution(),
        )


def test_evidence_errors_match_outcomes_and_worker_links_exist() -> None:
    with pytest.raises(ValidationError, match="error_code"):
        evidence(error_code="boom")
    with pytest.raises(ValidationError, match="error_code"):
        evidence(outcome=EvidenceOutcome.FAILED)
    assert evidence(outcome=EvidenceOutcome.REJECTED, error_code="tool_not_allowlisted")
    output = worker_output()
    with pytest.raises(ValidationError, match="unknown evidence"):
        output.evolve(
            steps=(
                {
                    "step_id": "record",
                    "status": "completed",
                    "findings": ["x"],
                    "evidence_ids": ["ev-ghost"],
                },
            )
        )


def test_review_counts_failed_findings_by_severity() -> None:
    report = review()
    assert report.failed_counts() == {
        "info": 0,
        "low": 0,
        "medium": 0,
        "high": 1,
        "critical": 0,
    }
    with pytest.raises(ValidationError, match="duplicate finding"):
        report.evolve(findings=(report.findings[0], report.findings[0]))
    assert SEVERITY_RANK[FindingSeverity.CRITICAL] > SEVERITY_RANK[FindingSeverity.INFO]


def test_run_snapshots_reject_contradictory_lifecycle_content() -> None:
    assert run().state is WorkflowState.PLANNING
    with pytest.raises(ValidationError, match="completed_at"):
        run(state=WorkflowState.CANCELLED, available_actions=())
    with pytest.raises(ValidationError, match="completed_at"):
        run(completed_at=NOW)
    with pytest.raises(ValidationError, match="updated_at"):
        run(updated_at=NOW - timedelta(seconds=1))
    with pytest.raises(ValidationError, match="error"):
        run(state=WorkflowState.FAILED, completed_at=NOW, available_actions=())
    with pytest.raises(ValidationError, match="error"):
        run(error=WorkflowError(code="x", message="y"))
    with pytest.raises(ValidationError, match="awaiting_human requires"):
        run(state=WorkflowState.AWAITING_HUMAN)
    with pytest.raises(ValidationError, match="no available actions"):
        run(state=WorkflowState.CANCELLED, completed_at=NOW)
    with pytest.raises(ValidationError, match="recorded decision"):
        run(state=WorkflowState.APPROVED, completed_at=NOW, available_actions=())
    waiting = run(
        state=WorkflowState.AWAITING_HUMAN,
        plan=plan(),
        worker_output=worker_output(),
        review=review(),
        available_actions=("approve", "correct", "partial", "reject", "cancel"),
    )
    decision = HumanDecision(
        decision=HumanDecisionKind.APPROVE,
        actor="person",
        round=1,
        decided_at=NOW,
        resulting_state=WorkflowState.APPROVED,
    )
    approved = waiting.evolve(
        state=WorkflowState.APPROVED,
        completed_at=NOW,
        available_actions=(),
        decisions=(decision,),
    )
    assert approved.decisions[0].resulting_state is WorkflowState.APPROVED
