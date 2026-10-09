"""Declarative reviewer checks evaluated against complete tool results."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from multi_agent_server.checks import evaluate_checks, recommend, resolve_path
from multi_agent_server.tools import ToolInvocation, digest
from shared_contracts.multi_agent import (
    EvidenceOutcome,
    EvidenceReference,
    FindingOutcome,
    FindingSeverity,
    HumanDecisionKind,
    PlanStep,
    ReviewerCheck,
    ReviewFinding,
)

STEPS = (
    PlanStep(id="a", index=1, title="A", purpose="p", tool="t.a.v1"),
    PlanStep(id="b", index=2, title="B", purpose="p", tool="t.b.v1"),
)


def invocation(step: str, content: dict[str, Any], *, ok: bool = True) -> ToolInvocation:
    return ToolInvocation(
        evidence=EvidenceReference(
            id=f"ev-{step}-r1",
            step_id=step,
            tool_name=f"t.{step}.v1",
            tool_version="v1",
            outcome=EvidenceOutcome.SUCCEEDED if ok else EvidenceOutcome.FAILED,
            transport="fake",
            result_digest=digest(content),
            duration_ms=1,
            error_code=None if ok else "boom",
            tool_call_id=uuid4(),
        ),
        content=content if ok else {},
    )


def check(rule: dict[str, Any], severity: str = "high") -> ReviewerCheck:
    return ReviewerCheck.model_validate(
        {
            "id": "c1",
            "description": "described",
            "severity": severity,
            "recommendation": "fix it",
            "rule": rule,
        }
    )


CONTENT = {
    "id": "abc",
    "count": 3,
    "ratio": 0.5,
    "flag": True,
    "items": [{"name": "x"}, {"name": "y"}],
    "tags": ["red", "blue"],
    "nested": {"status": "candidate", "empty": None},
}
INVOCATIONS = {"a": invocation("a", CONTENT), "b": invocation("b", {}, ok=False)}


def evaluate(rule: dict[str, Any], inputs: dict[str, Any] | None = None) -> ReviewFinding:
    return evaluate_checks([check(rule)], STEPS, INVOCATIONS, inputs or {})[0]


@pytest.mark.parametrize(
    ("rule", "passed"),
    [
        ({"kind": "step_succeeded", "step": "a"}, True),
        ({"kind": "step_succeeded", "step": "b"}, False),
        ({"kind": "field_present", "step": "a", "path": "nested.status"}, True),
        ({"kind": "field_present", "step": "a", "path": "nested.empty"}, False),
        ({"kind": "field_present", "step": "a", "path": "items.1.name"}, True),
        ({"kind": "field_present", "step": "a", "path": "items.9.name"}, False),
        ({"kind": "min_items", "step": "a", "path": "items", "value": 2}, True),
        ({"kind": "min_items", "step": "a", "path": "items", "value": 3}, False),
        ({"kind": "min_items", "step": "a", "path": "count", "value": 1}, False),
        ({"kind": "min_items", "step": "a", "path": "missing", "value": 1}, False),
        (
            {"kind": "field_compare", "step": "a", "path": "id", "operator": "eq", "value": "abc"},
            True,
        ),
        (
            {"kind": "field_compare", "step": "a", "path": "id", "operator": "ne", "value": "abc"},
            False,
        ),
        (
            {"kind": "field_compare", "step": "a", "path": "count", "operator": "gt", "value": 2},
            True,
        ),
        (
            {"kind": "field_compare", "step": "a", "path": "count", "operator": "ge", "value": 4},
            False,
        ),
        (
            {"kind": "field_compare", "step": "a", "path": "ratio", "operator": "lt", "value": 1},
            True,
        ),
        (
            {"kind": "field_compare", "step": "a", "path": "ratio", "operator": "le", "value": 0.5},
            True,
        ),
        (
            {"kind": "field_compare", "step": "a", "path": "flag", "operator": "gt", "value": 0},
            False,
        ),
        ({"kind": "field_compare", "step": "a", "path": "id", "operator": "gt", "value": 1}, False),
        (
            {
                "kind": "field_compare",
                "step": "a",
                "path": "nested.status",
                "operator": "in",
                "value": ["candidate"],
            },
            True,
        ),
        (
            {
                "kind": "field_compare",
                "step": "a",
                "path": "nested.status",
                "operator": "not_in",
                "value": ["candidate"],
            },
            False,
        ),
        (
            {
                "kind": "field_compare",
                "step": "a",
                "path": "tags",
                "operator": "contains",
                "value": "red",
            },
            True,
        ),
        (
            {
                "kind": "field_compare",
                "step": "a",
                "path": "items",
                "operator": "contains",
                "value": {},
            },
            False,
        ),
        (
            {
                "kind": "field_compare",
                "step": "a",
                "path": "count",
                "operator": "contains",
                "value": 3,
            },
            False,
        ),
        (
            {
                "kind": "field_compare",
                "step": "a",
                "path": "nested",
                "operator": "contains",
                "value": ["x"],
            },
            False,
        ),
        (
            {"kind": "field_compare", "step": "a", "path": "gone", "operator": "eq", "value": 1},
            False,
        ),
        ({"kind": "field_compare", "step": "b", "path": "id", "operator": "eq", "value": 1}, False),
        ({"kind": "step_succeeded", "step": "zzz"}, False),
    ],
)
def test_rules(rule: dict[str, Any], passed: bool) -> None:
    finding = evaluate(rule)

    assert finding.outcome is (FindingOutcome.PASS if passed else FindingOutcome.FAIL)
    assert finding.severity is (FindingSeverity.INFO if passed else FindingSeverity.HIGH)
    assert (finding.recommendation is None) is passed
    assert finding.check_id == "c1"
    assert finding.id == "f-c1"


def test_compare_values_can_reference_inputs() -> None:
    rule = {
        "kind": "field_compare",
        "step": "a",
        "path": "id",
        "operator": "eq",
        "value": "{{input.x}}",
    }
    assert evaluate(rule, {"x": "abc"}).outcome is FindingOutcome.PASS
    assert evaluate(rule, {"x": "zzz"}).outcome is FindingOutcome.FAIL


def test_all_steps_succeeded_names_the_failed_steps() -> None:
    finding = evaluate({"kind": "all_steps_succeeded"})
    assert finding.outcome is FindingOutcome.FAIL
    assert "b" in finding.message
    assert finding.evidence_ids == ("ev-a-r1", "ev-b-r1")
    passing = evaluate_checks([check({"kind": "all_steps_succeeded"})], STEPS[:1], INVOCATIONS, {})[
        0
    ]
    assert passing.outcome is FindingOutcome.PASS


def test_unexecuted_step_has_no_evidence_reference() -> None:
    finding = evaluate({"kind": "step_succeeded", "step": "zzz"})
    assert finding.evidence_ids == ()
    assert "not executed" in finding.message


def finding(severity: str, outcome: FindingOutcome = FindingOutcome.FAIL) -> ReviewFinding:
    return ReviewFinding(id=f"f-{severity}", severity=severity, outcome=outcome, message="m")


@pytest.mark.parametrize(
    ("severities", "expected"),
    [
        ([], HumanDecisionKind.APPROVE),
        (["info", "low"], HumanDecisionKind.APPROVE),
        (["medium"], HumanDecisionKind.PARTIAL),
        (["medium", "high"], HumanDecisionKind.CORRECT),
        (["low", "critical", "high"], HumanDecisionKind.REJECT),
    ],
)
def test_recommendation_follows_the_worst_failure(
    severities: list[str], expected: HumanDecisionKind
) -> None:
    findings = [finding(severity) for severity in severities]
    findings.append(finding("critical", FindingOutcome.PASS))
    assert recommend(findings) is expected


def test_resolve_path_handles_lists_and_missing_segments() -> None:
    assert resolve_path(CONTENT, "items.0.name") == "x"
    assert resolve_path(CONTENT, "items.x") is not None
    assert resolve_path(CONTENT, "count.deeper") is resolve_path(CONTENT, "nope")
