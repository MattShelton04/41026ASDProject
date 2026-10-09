"""Collect Multi-Agent Server workflow evidence for the Multi-Agent Workflow Review.

Expected layout, one directory per student, read up to three levels deep::

    multi-agent/student-N/**/workflow_history.jsonl    state transitions (required)
    multi-agent/student-N/**/coordination_audit.jsonl  handoffs, tool calls, decisions (required)
    multi-agent/student-N/**/*.json                    optional run or template exports

History and audit lines follow ``WorkflowHistoryEntry`` and ``CoordinationAuditEntry`` from the
Multi-Agent Server contract (``sequence``, ``run_id``, ``at``, ``from_state``/``to_state`` or
``event``/``role``/``actor``/``detail``). A run's tool allowlist is read from any audit
``detail.allowed_tools`` (or ``tool_allowlist``) or from an exported template's
``allowed_tools``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import JsonValue

from scripts.devtools.review.bounded import EvidenceReader
from scripts.devtools.review.checklist import Checklist, first_string, parse_timestamp, summarise
from shared_contracts.evidence_review import EvidenceReviewBundle

STUDENTS = tuple(f"student-{number}" for number in range(1, 6))
HISTORY_FILE = "workflow_history.jsonl"
AUDIT_FILE = "coordination_audit.jsonl"
STAGE_ORDER = ("planning", "working", "reviewing", "awaiting_human")
HUMAN_OUTCOMES = frozenset({"approved", "corrected", "partially_accepted", "rejected"})
TERMINAL = HUMAN_OUTCOMES | {"failed", "cancelled"}
# Mirrors the Multi-Agent Server state machine (ADR-047); a correction re-enters working.
TRANSITIONS: Mapping[str | None, frozenset[str]] = {
    None: frozenset({"planning"}),
    "planning": frozenset({"working", "failed", "cancelled"}),
    "working": frozenset({"reviewing", "failed", "cancelled"}),
    "reviewing": frozenset({"awaiting_human", "failed", "cancelled"}),
    "awaiting_human": frozenset({*HUMAN_OUTCOMES, "working", "cancelled"}),
    **{state: frozenset() for state in TERMINAL},
}
AGENT_ROLES = ("planner", "worker", "reviewer")
READ_ONLY = frozenset({"read_only", "read-only", "readonly"})
_RUN_KEYS = ("run_id", "workflow_run_id", "workflow_id")
_TIME_KEYS = ("at", "timestamp", "occurred_at", "recorded_at", "created_at")


@dataclass
class _Run:
    run_id: str
    history: list[dict[str, JsonValue]] = field(default_factory=list)
    audit: list[dict[str, JsonValue]] = field(default_factory=list)
    allowlist: set[str] = field(default_factory=set)


def collect(reader: EvidenceReader) -> EvidenceReviewBundle:
    """Build the multi-agent checklist for every student's exported workflow evidence."""
    checklist = Checklist(reader)
    students: dict[str, JsonValue] = {}
    for student in STUDENTS:
        students[student] = _collect_student(reader, checklist, student)
    reviewed = [facts for facts in students.values() if isinstance(facts, dict)]
    totals: dict[str, JsonValue] = {
        "students_with_evidence": sum(1 for facts in reviewed if facts.get("runs")),
        "runs": sum(_int(facts.get("runs")) for facts in reviewed),
        "runs_with_human_decision": sum(
            _int(facts.get("runs_with_human_decision")) for facts in reviewed
        ),
        "tool_calls": sum(_int(facts.get("tool_calls")) for facts in reviewed),
    }
    return checklist.bundle("multi-agent", {"totals": totals, "students": students})


def _collect_student(
    reader: EvidenceReader, checklist: Checklist, student: str
) -> dict[str, JsonValue]:
    directory = f"multi-agent/{student}"
    histories = reader.glob(directory, (HISTORY_FILE,)) or [f"{directory}/{HISTORY_FILE}"]
    audits = reader.glob(directory, (AUDIT_FILE,)) or [f"{directory}/{AUDIT_FILE}"]
    exports = [
        path
        for path in reader.glob(directory, ("*.json",))
        if not path.endswith((HISTORY_FILE, AUDIT_FILE))
    ][:10]
    screenshots = len(reader.glob(directory, ("*.png", "*.jpg", "*.jpeg", "*.webp")))
    runs: dict[str, _Run] = {}
    problems: list[str] = []
    refs = [*histories, *audits]
    for path in histories:
        _, records = reader.read_jsonl(path)
        if records is None:
            problems.append(f"{path} unreadable")
            continue
        for record in records:
            run_id = first_string(record, *_RUN_KEYS)
            if run_id is None:
                problems.append(f"{path} has a line without run_id")
                continue
            runs.setdefault(run_id, _Run(run_id)).history.append(record)
    for path in audits:
        _, records = reader.read_jsonl(path)
        if records is None:
            problems.append(f"{path} unreadable")
            continue
        for record in records:
            run_id = first_string(record, *_RUN_KEYS)
            if run_id is None:
                problems.append(f"{path} has a line without run_id")
                continue
            run = runs.setdefault(run_id, _Run(run_id))
            run.audit.append(record)
            run.allowlist.update(_allowlist(record))
    template_allowlist: set[str] = set()
    templates: set[str] = set()
    for path in exports:
        _, value = reader.read_json(path)
        if isinstance(value, dict):
            template_allowlist.update(_allowlist(value))
            template = value.get("template")
            if isinstance(template, dict):
                template_allowlist.update(_allowlist(template))
            template_id = value.get("template_id") or (
                value.get("id") if "allowed_tools" in value else None
            )
            if isinstance(template_id, str):
                templates.add(template_id)
    for run in runs.values():
        run.allowlist.update(template_allowlist)
        run.history.sort(key=_sequence)
        run.audit.sort(key=_sequence)

    present = bool(runs) and not problems
    checklist.add(
        f"{student}.evidence",
        f"{student} exported workflow history and coordination audit",
        passed=present,
        detail=(
            f"{len(runs)} run(s) across {len(histories)} history and {len(audits)} audit file(s)."
            if present
            else "Evidence gap: "
            + (summarise(problems) if problems else "no workflow runs were exported")
            + f". Export with the Multi-Agent Server CLI into {directory}/."
        ),
        refs=refs,
    )
    ordered = sorted(runs.values(), key=lambda run: run.run_id)
    decided = [run for run in ordered if _human_decision(run) is not None]
    _stage_check(checklist, student, ordered, refs)
    _decision_check(checklist, student, ordered, decided, refs)
    _transition_check(checklist, student, ordered, refs)
    _tool_check(checklist, student, ordered, refs)
    _handoff_check(checklist, student, ordered, refs)
    missing_history = sorted(_short(run.run_id) for run in ordered if not run.history)
    missing_audit = sorted(_short(run.run_id) for run in ordered if not run.audit)
    checklist.add(
        f"{student}.correlation",
        f"{student} history and audit describe the same runs",
        passed=bool(ordered) and not missing_history and not missing_audit,
        detail=(
            "Every run appears in both files."
            if ordered and not missing_history and not missing_audit
            else "No runs to correlate."
            if not ordered
            else "Runs without history: "
            + (summarise(missing_history) or "none")
            + "; runs without audit: "
            + (summarise(missing_audit) or "none")
            + "."
        ),
        refs=refs,
    )
    tool_calls = [
        record for run in ordered for record in run.audit if _event(record) == "tool.call"
    ]
    return {
        "runs": len(ordered),
        "runs_with_human_decision": len(decided),
        "decisions": _strings(
            decision for run in decided if (decision := _human_decision(run)) is not None
        ),
        "final_states": _strings(
            state for run in ordered if (state := _final_state(run)) is not None
        ),
        "tool_calls": len(tool_calls),
        "tools": _strings({name for record in tool_calls if (name := _tool_name(record))}),
        "tool_rejections": sum(
            1 for run in ordered for record in run.audit if _event(record) == "tool.rejected"
        ),
        "templates": _strings(templates),
        "screenshots": screenshots,
    }


def _stage_check(
    checklist: Checklist, student: str, runs: Sequence[_Run], refs: Sequence[str]
) -> None:
    incomplete: list[str] = []
    complete = 0
    for run in runs:
        states = [_to_state(record) for record in run.history]
        roles = {_role(record) for record in run.audit}
        reached_human = "awaiting_human" in states
        if not reached_human:
            continue
        ordered_ok = _in_order(states, STAGE_ORDER)
        missing_roles = [role for role in AGENT_ROLES if role not in roles]
        if ordered_ok and not missing_roles:
            complete += 1
        else:
            incomplete.append(_short(run.run_id))
    checklist.add(
        f"{student}.stages",
        f"{student} runs pass through Planner, Worker and Reviewer before human review",
        passed=complete > 0 and not incomplete,
        detail=(
            f"{complete} run(s) recorded planning, working, reviewing and awaiting_human with "
            "planner, worker and reviewer audit events."
            if complete and not incomplete
            else "No run reached awaiting_human through all agent stages."
            if not incomplete
            else f"Stage order or agent audit events missing for run(s) {summarise(incomplete)}."
        ),
        refs=refs,
    )


def _decision_check(
    checklist: Checklist,
    student: str,
    runs: Sequence[_Run],
    decided: Sequence[_Run],
    refs: Sequence[str],
) -> None:
    unattributed: list[str] = []
    for run in decided:
        decisions = [record for record in run.audit if _event(record) == "decision.recorded"]
        if not any(
            first_string(record, "actor", "decided_by", "decider")
            and parse_timestamp(first_string(record, *_TIME_KEYS))
            and _role(record) == "human"
            for record in decisions
        ):
            unattributed.append(_short(run.run_id))
    passed = bool(decided) and not unattributed
    checklist.add(
        f"{student}.human-decision",
        f"{student} records a human decision with actor and time",
        passed=passed,
        detail=(
            f"{len(decided)} of {len(runs)} run(s) reached a human decision with an attributed "
            "decision.recorded audit event."
            if passed
            else "No run reached a human decision (approve, correct, partial or reject)."
            if not decided
            else f"Decision without a human actor or timestamp in run(s) {summarise(unattributed)}."
        ),
        refs=refs,
    )


def _transition_check(
    checklist: Checklist, student: str, runs: Sequence[_Run], refs: Sequence[str]
) -> None:
    problems: list[str] = []
    for run in runs:
        problems.extend(f"{_short(run.run_id)}: {issue}" for issue in _transition_issues(run))
    checklist.add(
        f"{student}.transitions",
        f"{student} state transitions are legal with consistent timestamps",
        passed=bool(runs) and not problems,
        detail=(
            f"All transitions in {len(runs)} run(s) follow the workflow state machine in "
            "sequence and time order."
            if runs and not problems
            else "No transitions to check."
            if not runs
            else summarise(problems, limit=3)
        ),
        refs=refs,
    )


def _transition_issues(run: _Run) -> list[str]:
    issues: list[str] = []
    previous_state: str | None = None
    previous_time: datetime | None = None
    for index, record in enumerate(run.history, start=1):
        sequence = record.get("sequence")
        if isinstance(sequence, int) and sequence != index:
            issues.append(f"history sequence {sequence} at position {index}")
            break
        source = record.get("from_state", record.get("from"))
        target = _to_state(record)
        if target is None:
            issues.append(f"history entry {index} has no target state")
            break
        if source != previous_state:
            issues.append(f"entry {index} starts from {source}, previous state {previous_state}")
            break
        allowed = TRANSITIONS.get(previous_state)
        if allowed is None or target not in allowed:
            issues.append(f"illegal transition {previous_state} -> {target}")
            break
        moment = parse_timestamp(first_string(record, *_TIME_KEYS))
        if moment is None:
            issues.append(f"entry {index} has no timezone-aware timestamp")
            break
        if previous_time is not None and moment < previous_time:
            issues.append(f"entry {index} is earlier than entry {index - 1}")
            break
        previous_state, previous_time = target, moment
    audit_time: datetime | None = None
    for index, record in enumerate(run.audit, start=1):
        moment = parse_timestamp(first_string(record, *_TIME_KEYS))
        if moment is None:
            issues.append(f"audit entry {index} has no timezone-aware timestamp")
            break
        if audit_time is not None and moment < audit_time:
            issues.append(f"audit entry {index} is earlier than audit entry {index - 1}")
            break
        audit_time = moment
    return issues


def _tool_check(
    checklist: Checklist, student: str, runs: Sequence[_Run], refs: Sequence[str]
) -> None:
    outside: list[str] = []
    unrecorded: list[str] = []
    writes: list[str] = []
    calls = 0
    for run in runs:
        for record in run.audit:
            if _event(record) != "tool.call":
                continue
            calls += 1
            name = _tool_name(record)
            if not run.allowlist:
                unrecorded.append(_short(run.run_id))
            elif name is None or name not in run.allowlist:
                outside.append(f"{name} in {_short(run.run_id)}")
            effect = _detail_string(record, "side_effect")
            if effect is not None and effect.lower() not in READ_ONLY:
                writes.append(f"{name} ({effect})")
    passed = bool(runs) and not outside and not unrecorded and not writes
    if passed:
        detail = f"{calls} tool call(s) all used allowlisted read-only tools."
    elif not runs:
        detail = "No runs exported."
    elif outside:
        detail = f"Tool calls outside the template allowlist: {summarise(sorted(set(outside)))}."
    elif writes:
        detail = f"Non-read-only tool calls: {summarise(sorted(set(writes)))}."
    else:
        detail = (
            "The export does not record the template's allowed_tools for run(s) "
            f"{summarise(sorted(set(unrecorded)))}; tool calls cannot be checked."
        )
    checklist.add(
        f"{student}.tool-allowlist",
        f"{student} Worker tool calls stay inside the read-only allowlist",
        passed=passed,
        detail=detail,
        refs=refs,
    )


def _handoff_check(
    checklist: Checklist, student: str, runs: Sequence[_Run], refs: Sequence[str]
) -> None:
    handoffs = 0
    seen: set[str] = set()
    for run in runs:
        for record in run.audit:
            if _event(record) != "agent.handoff":
                continue
            handoffs += 1
            source = _detail_string(record, "from", "from_role", "source") or _role(record)
            target = _detail_string(record, "to", "to_role", "target")
            if source and target:
                seen.add(f"{source}->{target}")
    expected = ("planner->worker", "worker->reviewer", "reviewer->human")
    missing = [pair for pair in expected if pair not in seen]
    checklist.add(
        f"{student}.handoffs",
        f"{student} audit records agent handoffs",
        passed=handoffs > 0 and not missing,
        required=False,
        detail=(
            f"{handoffs} handoff event(s) cover planner, worker, reviewer and human."
            if handoffs and not missing
            else f"Handoffs not recorded: {', '.join(missing)}."
        ),
        refs=refs,
    )


def _human_decision(run: _Run) -> str | None:
    for record in run.audit:
        if _event(record) == "decision.recorded":
            decision = _detail_string(record, "decision") or first_string(record, "decision")
            return decision or "recorded"
    for record in run.history:
        if _to_state(record) in HUMAN_OUTCOMES and _role(record) == "human":
            return str(_to_state(record))
    return None


def _final_state(run: _Run) -> str | None:
    return _to_state(run.history[-1]) if run.history else None


def _in_order(states: Sequence[str | None], expected: Sequence[str]) -> bool:
    position = 0
    for state in states:
        if position < len(expected) and state == expected[position]:
            position += 1
    return position == len(expected)


def _allowlist(record: Mapping[str, JsonValue]) -> set[str]:
    names: set[str] = set()
    sources: list[Mapping[str, JsonValue]] = [record]
    detail = record.get("detail")
    if isinstance(detail, dict):
        sources.append(detail)
    for source in sources:
        for key in ("allowed_tools", "tool_allowlist"):
            value = source.get(key)
            if isinstance(value, list):
                names.update(item for item in value if isinstance(item, str))
    return names


def _event(record: Mapping[str, JsonValue]) -> str | None:
    value = first_string(record, "event", "type", "kind")
    return value.lower() if value else None


def _role(record: Mapping[str, JsonValue]) -> str | None:
    value = first_string(record, "role", "agent")
    return value.lower() if value else None


def _to_state(record: Mapping[str, JsonValue]) -> str | None:
    value = first_string(record, "to_state", "state", "to", "status")
    return value.lower() if value else None


def _tool_name(record: Mapping[str, JsonValue]) -> str | None:
    return _detail_string(record, "tool_name", "tool") or first_string(record, "tool_name")


def _detail_string(record: Mapping[str, JsonValue], *keys: str) -> str | None:
    detail = record.get("detail")
    if isinstance(detail, dict):
        return first_string(detail, *keys)
    return None


def _sequence(record: Mapping[str, JsonValue]) -> int:
    value = record.get("sequence")
    return value if isinstance(value, int) else 0


def _short(run_id: str) -> str:
    return run_id[:8]


def _strings(values: Iterable[str]) -> list[JsonValue]:
    return [*sorted(values)]


def _int(value: JsonValue | None) -> int:
    return value if isinstance(value, int) else 0
