"""Deterministic evaluation of a template's declarative reviewer checks.

The Reviewer always runs these rules against the complete tool results the Worker gathered, so
every check produces a finding regardless of which model provider is configured. A model may add
findings, but cannot remove or soften these.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pydantic import JsonValue

from multi_agent_server.tools import ToolInvocation
from shared_contracts.multi_agent import (
    SEVERITY_RANK,
    EvidenceOutcome,
    FindingOutcome,
    FindingSeverity,
    HumanDecisionKind,
    JsonObject,
    PlanStep,
    ReviewerCheck,
    ReviewFinding,
    resolve_placeholders,
)

_ABSENT = object()


def evaluate_checks(
    checks: Sequence[ReviewerCheck],
    steps: Sequence[PlanStep],
    invocations: Mapping[str, ToolInvocation],
    inputs: JsonObject,
) -> tuple[ReviewFinding, ...]:
    """Evaluate every check in template order and return one finding per check."""
    return tuple(_evaluate(check, steps, invocations, inputs) for check in checks)


def recommend(findings: Sequence[ReviewFinding]) -> HumanDecisionKind:
    """Deterministic recommendation from the most severe failed finding.

    critical → reject; high → correct; medium → partial (accept the evidence that passed);
    low/info or no failures → approve.
    """
    worst = max(
        (SEVERITY_RANK[f.severity] for f in findings if f.outcome is FindingOutcome.FAIL),
        default=-1,
    )
    if worst >= SEVERITY_RANK[FindingSeverity.CRITICAL]:
        return HumanDecisionKind.REJECT
    if worst >= SEVERITY_RANK[FindingSeverity.HIGH]:
        return HumanDecisionKind.CORRECT
    if worst >= SEVERITY_RANK[FindingSeverity.MEDIUM]:
        return HumanDecisionKind.PARTIAL
    return HumanDecisionKind.APPROVE


def resolve_path(content: JsonValue, path: str) -> object:
    """Follow a dotted path through objects and (by numeric segment) arrays."""
    current: object = content
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        elif isinstance(current, list) and segment.isdecimal() and int(segment) < len(current):
            current = current[int(segment)]
        else:
            return _ABSENT
    return current


def _finding(
    check: ReviewerCheck,
    passed: bool,
    observation: str,
    step_ids: tuple[str, ...],
    invocations: Mapping[str, ToolInvocation],
) -> ReviewFinding:
    return ReviewFinding(
        id=f"f-{check.id}",
        check_id=check.id,
        severity=FindingSeverity.INFO if passed else check.severity,
        outcome=FindingOutcome.PASS if passed else FindingOutcome.FAIL,
        message=f"{'Passed' if passed else 'Failed'}: {check.description} ({observation})"[:4000],
        recommendation=None if passed else check.recommendation,
        evidence_ids=tuple(
            invocations[step_id].evidence.id for step_id in step_ids if step_id in invocations
        ),
        step_ids=step_ids,
        source="check",
    )


def _evaluate(
    check: ReviewerCheck,
    steps: Sequence[PlanStep],
    invocations: Mapping[str, ToolInvocation],
    inputs: JsonObject,
) -> ReviewFinding:
    rule = check.rule
    if rule.kind == "all_steps_succeeded":
        step_ids = tuple(step.id for step in steps)
        failed = [
            step_id
            for step_id in step_ids
            if step_id not in invocations
            or invocations[step_id].evidence.outcome is not EvidenceOutcome.SUCCEEDED
        ]
        observation = (
            f"all {len(step_ids)} steps succeeded"
            if not failed
            else f"steps without evidence: {', '.join(failed)}"
        )
        return _finding(check, not failed, observation, step_ids, invocations)
    assert rule.step is not None  # guaranteed by ReviewerCheckRule validation
    step_ids = (rule.step,)
    invocation = invocations.get(rule.step)
    if invocation is None:
        return _finding(check, False, f"step {rule.step} was not executed", (), invocations)
    evidence = invocation.evidence
    if evidence.outcome is not EvidenceOutcome.SUCCEEDED:
        observation = f"step {rule.step} {evidence.outcome.value}: {evidence.error_code}"
        return _finding(check, False, observation, step_ids, invocations)
    if rule.kind == "step_succeeded":
        return _finding(check, True, f"{evidence.tool_name} succeeded", step_ids, invocations)
    assert rule.path is not None
    observed = resolve_path(dict(invocation.content), rule.path)
    if rule.kind == "field_present":
        present = observed is not _ABSENT and observed is not None
        observation = f"{rule.path} {'is present' if present else 'is missing'}"
        return _finding(check, present, observation, step_ids, invocations)
    if observed is _ABSENT:
        return _finding(check, False, f"{rule.path} is missing", step_ids, invocations)
    if rule.kind == "min_items":
        assert isinstance(rule.value, int)
        size = len(observed) if isinstance(observed, (list, dict)) else None
        passed = size is not None and size >= rule.value
        observation = (
            f"{rule.path} has {size} item(s); at least {rule.value} required"
            if size is not None
            else f"{rule.path} is not a collection"
        )
        return _finding(check, passed, observation, step_ids, invocations)
    expected = resolve_placeholders(rule.value, inputs)
    assert rule.operator is not None
    passed = _compare(observed, rule.operator, expected)
    observation = f"{rule.path} = {_short(observed)}; expected {rule.operator} {_short(expected)}"
    return _finding(check, passed, observation, step_ids, invocations)


def _compare(observed: object, operator: str, expected: object) -> bool:
    try:
        if operator == "eq":
            return observed == expected
        if operator == "ne":
            return observed != expected
        if operator == "in":
            return isinstance(expected, list) and observed in expected
        if operator == "not_in":
            return isinstance(expected, list) and observed not in expected
        if operator == "contains":
            return isinstance(observed, (list, str, dict)) and expected in observed
        if isinstance(observed, bool) or isinstance(expected, bool):
            return False
        if not isinstance(observed, (int, float)) or not isinstance(expected, (int, float)):
            return False
        return {
            "gt": observed > expected,
            "ge": observed >= expected,
            "lt": observed < expected,
            "le": observed <= expected,
        }[operator]
    except TypeError:
        return False


def _short(value: object) -> str:
    text = repr(value) if not isinstance(value, str) else f"'{value}'"
    return text if len(text) <= 120 else text[:117] + "..."
