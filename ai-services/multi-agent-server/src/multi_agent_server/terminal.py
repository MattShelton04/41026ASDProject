"""Terminal human review: a live coordination trail and an interactive decision prompt.

``multi-agent-server review RUN_ID`` (and ``run --review``) follows a run while the Planner,
Worker and Reviewer work, printing each state change and coordination event as it is recorded.
When the run reaches ``awaiting_human`` it shows the evidence and asks the person for a decision
with exactly the choices the server offers. A first correction re-runs the Worker and Reviewer,
so the prompt follows round 2 and asks again. Nothing is recorded until the person confirms.

The module talks only to a :class:`ReviewBackend` (in-process service or HTTP client), reads
answers through an injectable ``ask`` function and writes through ``say``, so tests drive it
without a terminal.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from shared_contracts.multi_agent import (
    ACTIVE_WORKFLOW_STATES,
    MAX_WORKFLOW_ROUNDS,
    AuditEvent,
    CoordinationAuditEntry,
    FindingOutcome,
    FindingSeverity,
    HumanDecisionKind,
    HumanDecisionRequest,
    WorkflowHistoryEntry,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowState,
    WorkflowTemplateList,
)

Ask = Callable[[str], str]
Say = Callable[[str], None]
NOTE_LIMIT = 2_000
BLOCKING_SEVERITIES = frozenset({FindingSeverity.CRITICAL, FindingSeverity.HIGH})
CHOICES: dict[str, str] = {
    "approve": "Accept the result as it stands",
    "correct": "Send the Worker and Reviewer back once with your note",
    "partial": "Accept only some plan steps",
    "reject": "Reject the result",
}
FINAL_CORRECTION = "Record your correction and close the run (no further re-run)"


class ReviewBackend(Protocol):
    """The operations the review loop needs (the CLI's in-process and HTTP backends)."""

    def templates(self) -> WorkflowTemplateList: ...
    def run(self, run_id: UUID) -> WorkflowRun: ...
    def decide(self, run_id: UUID, request: HumanDecisionRequest) -> WorkflowRun: ...
    def history(
        self, run_id: UUID, after_history: int = 0, after_audit: int = 0
    ) -> WorkflowRunHistory: ...


class ReviewAborted(Exception):  # noqa: N818 - control flow: the person left the prompt
    """The person ended input (EOF or Ctrl+C) before a decision was confirmed."""


@dataclass
class Cursors:
    """The last history and audit sequence already printed."""

    history: int = 0
    audit: int = 0

    def advance(self, page: WorkflowRunHistory) -> None:
        if page.history:
            self.history = max(self.history, page.history[-1].sequence)
        if page.audit:
            self.audit = max(self.audit, page.audit[-1].sequence)


# --------------------------------------------------------------------------- trail


def _text(value: Any, limit: int = 120) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _ids(value: Any) -> str:
    return ", ".join(str(item) for item in value) if isinstance(value, list) and value else "-"


def describe_audit(entry: CoordinationAuditEntry) -> str:
    """One plain-language sentence for a coordination event."""
    # Audit detail is free-form JSON; read it defensively so an older entry still prints.
    detail: dict[str, Any] = dict(entry.detail)
    get = detail.get
    event = entry.event
    if event is AuditEvent.RUN_CREATED:
        return (
            f"run accepted for {get('requested_by', entry.actor)}: {get('template_id')} "
            f"{get('template_version')}, {get('provider_mode')} agents, tools via "
            f"{get('tool_transport')}"
        )
    if event is AuditEvent.HANDOFF:
        text = f"handoff {get('from')} -> {get('to')}"
        if get("steps") is not None:
            text += f" ({get('steps')} step(s))"
        if get("correction_note"):
            text += f" with correction: {_text(get('correction_note'), 80)}"
        return text
    if event is AuditEvent.PLAN_CREATED:
        steps = _list(get("steps"))
        names = ", ".join(
            f"{step.get('id')} [{step.get('tool')}]" for step in steps if isinstance(step, dict)
        )
        return f"plan of {len(steps)} step(s): {names or '-'} ({get('provider')})"
    if event is AuditEvent.MODEL_STARTED:
        return (
            f"model call {get('attempt')} started: {get('model_profile')}, prompt "
            f"{get('prompt_id')} {get('prompt_version')}"
        )
    if event is AuditEvent.MODEL_INVOCATION:
        text = f"model call {get('attempt')} {get('outcome')}"
        if get("model"):
            text += f": {get('provider')}/{get('model')}"
        if get("prompt_tokens") is not None:
            text += f", {get('prompt_tokens')}+{get('output_tokens')} tokens"
        if get("duration_ms") is not None:
            text += f", {get('duration_ms')} ms"
        if get("error"):
            text += f" ({_text(get('error'), 60)})"
        return text
    if event is AuditEvent.MODEL_FALLBACK:
        return f"fell back to {get('fallback_provider')} after {get('reason')}"
    if event in {AuditEvent.TOOL_CALL, AuditEvent.TOOL_REJECTED}:
        return (
            f"step {get('step_id')}: {get('tool_name')} {get('outcome')} via "
            f"{get('transport')} in {get('duration_ms')} ms -> {get('evidence_id')}"
        )
    if event is AuditEvent.WORKER_COMPLETED:
        evidence = _list(get("evidence_ids"))
        return (
            f"evidence gathered for {get('steps_completed')}/{get('steps_total')} step(s), "
            f"{len(evidence)} evidence item(s) ({get('provider')})"
        )
    if event is AuditEvent.REVIEW_COMPLETED:
        failed = _dict(get("failed_findings"))
        failures = ", ".join(f"{count} {severity}" for severity, count in failed.items() if count)
        return (
            f"recommends {str(get('recommendation', '?')).upper()}; "
            f"{get('findings')} finding(s), failed: {failures or 'none'} ({get('provider')})"
        )
    if event is AuditEvent.DECISION_RECORDED:
        text = (
            f"{entry.actor} decided {get('decision')} in round {get('decision_round')} "
            f"-> {get('resulting_state')} (Reviewer suggested {get('reviewer_recommendation')})"
        )
        if get("accepted_step_ids"):
            text += f"; accepted {_ids(get('accepted_step_ids'))}"
        if get("not_accepted_step_ids"):
            text += f"; not accepted {_ids(get('not_accepted_step_ids'))}"
        if get("note"):
            text += f"; note: {_text(get('note'), 80)}"
        return text
    if event is AuditEvent.RUN_FAILED:
        return f"run failed: {get('code')} during {get('stage') or 'unknown stage'}"
    if event is AuditEvent.RUN_CANCELLED:
        return f"cancelled by {entry.actor} while {get('previous_state')}"
    return _text(detail, 160)


def describe_history(entry: WorkflowHistoryEntry) -> str:
    """One line for a state transition."""
    origin = entry.from_state.value if entry.from_state else "-"
    return f"{origin} -> {entry.to_state.value}: {entry.reason}"


def trail_lines(page: WorkflowRunHistory) -> list[str]:
    """History and audit merged in time order, one readable line each.

    Transitions are prefixed ``==`` and coordination events ``  .``, so the hand-offs between
    the Planner, Worker, Reviewer and human read top to bottom. Event names are kept, so the
    lines can be matched against ``coordination_audit.jsonl``.
    """
    rows: list[tuple[str, int, int, str]] = []
    for entry in page.history:
        rows.append(
            (
                entry.at.isoformat(),
                0,
                entry.sequence,
                f"{entry.at.strftime('%H:%M:%S')} == r{entry.round} {entry.role.value:<9} "
                f"{describe_history(entry)}",
            )
        )
    for audit in page.audit:
        rows.append(
            (
                audit.at.isoformat(),
                1,
                audit.sequence,
                f"{audit.at.strftime('%H:%M:%S')}  . r{audit.round} {audit.role.value:<9} "
                f"{audit.event.value:<18} {describe_audit(audit)}",
            )
        )
    return [row[3] for row in sorted(rows)]


def follow(
    backend: ReviewBackend,
    run_id: UUID,
    *,
    say: Say,
    cursors: Cursors | None = None,
    timeout: float = 300.0,
    interval: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[WorkflowRun, Cursors]:
    """Print new trail lines until no agent is working on the run (or ``timeout`` passes)."""
    position = cursors or Cursors()
    deadline = clock() + timeout
    while True:
        page = backend.history(run_id, position.history, position.audit)
        for line in trail_lines(page):
            say(line)
        position.advance(page)
        if page.state not in ACTIVE_WORKFLOW_STATES:
            return backend.run(run_id), position
        if clock() >= deadline:
            say(f"Still {page.state.value} after {timeout:g} s; stopped following.")
            return backend.run(run_id), position
        sleep(interval)


# --------------------------------------------------------------------------- decision prompt


def _ask(ask: Ask, prompt: str) -> str:
    try:
        return ask(prompt).strip()
    except (EOFError, KeyboardInterrupt) as exc:
        raise ReviewAborted from exc


def _blocking_failures(run: WorkflowRun) -> int:
    if run.review is None:
        return 0
    return sum(
        1
        for finding in run.review.findings
        if finding.outcome is FindingOutcome.FAIL and finding.severity in BLOCKING_SEVERITIES
    )


def _choose(run: WorkflowRun, ask: Ask, say: Say) -> str | None:
    offered: list[str] = [action for action in CHOICES if action in run.available_actions]
    recommended = run.review.recommendation.value if run.review else None
    final_round = run.round >= MAX_WORKFLOW_ROUNDS
    say("Choose a decision:")
    for number, action in enumerate(offered, start=1):
        detail = FINAL_CORRECTION if action == "correct" and final_round else CHOICES[action]
        tag = "  <- Reviewer suggests" if action == recommended else ""
        say(f"  {number}. {action:<8} {detail}{tag}")
    say("  q. later    Leave the run waiting; nothing is recorded")
    default = offered.index(recommended) + 1 if recommended in offered else None
    suffix = f" [{default}]" if default else ""
    while True:
        answer = _ask(ask, f"Decision{suffix}: ").lower()
        if not answer and default:
            return offered[default - 1]
        if answer in {"q", "quit", "later"}:
            return None
        if answer.isdecimal() and 1 <= int(answer) <= len(offered):
            return offered[int(answer) - 1]
        if answer in offered:
            return answer
        say(f"Enter 1-{len(offered)}, a decision name, or q.")


def _accepted_steps(run: WorkflowRun, ask: Ask, say: Say) -> tuple[str, ...]:
    steps = run.plan.steps if run.plan else ()
    results = {
        result.step_id: result.status
        for result in (run.worker_output.steps if run.worker_output else ())
    }
    say("Plan steps:")
    for number, step in enumerate(steps, start=1):
        say(f"  {number}. {step.id:<16} {step.title} [{results.get(step.id, 'not run')}]")
    by_number = {str(number): step.id for number, step in enumerate(steps, start=1)}
    known = {step.id for step in steps}
    while True:
        answer = _ask(ask, "Accept which steps? (numbers or IDs, comma-separated): ")
        picked: list[str] = []
        unknown: list[str] = []
        for token in (part.strip() for part in answer.replace(" ", ",").split(",")):
            if not token:
                continue
            step_id = by_number.get(token, token)
            if step_id not in known:
                unknown.append(token)
            elif step_id not in picked:
                picked.append(step_id)
        if unknown:
            say(f"Not a step in this plan: {', '.join(unknown)}")
        elif not picked:
            say("Select at least one step.")
        else:
            return tuple(picked)


def _note(decision: str, ask: Ask, say: Say) -> str:
    required = decision != "approve"
    prompt = "Note (required; why this decision): " if required else "Note (optional): "
    while True:
        note = _ask(ask, prompt)
        if len(note) > NOTE_LIMIT:
            say(f"Keep the note within {NOTE_LIMIT} characters.")
        elif required and not note:
            say(f"A {decision} decision needs a note.")
        else:
            return note


def _confirm(ask: Ask, prompt: str, *, default: bool) -> bool:
    answer = _ask(ask, prompt + (" [Y/n] " if default else " [y/N] ")).lower()
    return default if not answer else answer in {"y", "yes"}


def prompt_decision(
    run: WorkflowRun, *, actor: str, ask: Ask, say: Say
) -> HumanDecisionRequest | None:
    """Ask for one decision the run allows; ``None`` when the person defers it."""
    while True:
        decision = _choose(run, ask, say)
        if decision is None:
            return None
        blocking = _blocking_failures(run)
        if (
            decision == "approve"
            and blocking
            and not _confirm(
                ask,
                f"{blocking} critical or high check(s) failed. Approve anyway?",
                default=False,
            )
        ):
            continue
        accepted = _accepted_steps(run, ask, say) if decision == "partial" else ()
        note = _note(decision, ask, say)
        name = _ask(ask, f"Recorded as [{actor}]: ") or actor
        summary = decision.upper() + (f" (accept {', '.join(accepted)})" if accepted else "")
        if _confirm(ask, f"Record {summary} for round {run.round} as {name}?", default=True):
            return HumanDecisionRequest(
                decision=HumanDecisionKind(decision),
                note=note,
                actor=name,
                accepted_step_ids=accepted,
            )
        say("Not recorded. Choose again.")


def review_header(run: WorkflowRun, guidance: str | None) -> list[str]:
    """What the person needs before choosing: the round, the suggestion and the guidance."""
    lines = ["", f"== Human review: round {run.round} of {MAX_WORKFLOW_ROUNDS} =="]
    if run.review is not None:
        failed = ", ".join(
            f"{count} {kind}" for kind, count in run.review.failed_counts().items() if count
        )
        lines.append(
            f"The Reviewer suggests {run.review.recommendation.value.upper()} "
            f"(failed checks: {failed or 'none'}). Agents never decide; you do."
        )
    if run.superseded:
        lines.append(f"Round {run.round - 1} was corrected: {run.decisions[-1].note}")
    if guidance:
        lines.append(f"Guidance: {' '.join(guidance.split())}")
    return lines


def interactive_review(
    backend: ReviewBackend,
    run_id: UUID,
    *,
    actor: str,
    ask: Ask,
    say: Say,
    render: Callable[[WorkflowRun], str],
    follow_from: Cursors | None = None,
    timeout: float = 300.0,
    interval: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    """Follow the run, ask for decisions until it ends or the person defers; return an exit code.

    ``follow_from`` is where the live trail starts. ``None`` prints the whole trail of a run the
    agents are still working on, and only what happens from now on for any other run.
    Exit codes: 0 once a decision ends the run or the person defers, 1 when the run failed or
    was cancelled, 2 when input ended before a decision was confirmed.
    """
    run = backend.run(run_id)
    cursors = follow_from
    if cursors is None:
        cursors = Cursors()
        if run.state not in ACTIVE_WORKFLOW_STATES:
            cursors.advance(backend.history(run_id))
    guidance = next(
        (
            item.template.human_review_guidance
            for item in backend.templates().items
            if item.template.id == run.template_id
        ),
        None,
    )
    while True:
        if run.state in ACTIVE_WORKFLOW_STATES:
            say(f"Following run {run.id} while the agents work ({run.state.value})...")
        # Prints whatever was recorded since the last look (including a decision just made) and
        # returns at once when no agent is working.
        run, cursors = follow(
            backend,
            run.id,
            say=say,
            cursors=cursors,
            timeout=timeout,
            interval=interval,
            sleep=sleep,
        )
        if run.state is not WorkflowState.AWAITING_HUMAN:
            say("")
            say(render(run))
            return 1 if run.state in {WorkflowState.FAILED, WorkflowState.CANCELLED} else 0
        say("")
        say(render(run))
        for line in review_header(run, guidance):
            say(line)
        try:
            request = prompt_decision(run, actor=actor, ask=ask, say=say)
        except ReviewAborted:
            say("")
            say(f"Input ended; nothing recorded. Resume with: multi-agent-server review {run.id}")
            return 2
        if request is None:
            say(f"Nothing recorded. Resume with: multi-agent-server review {run.id}")
            return 0
        request_round = run.round
        run = backend.decide(run.id, request)
        say(f"Recorded {request.decision.value} by {request.actor} for round {request_round}.")
        if run.round > request_round:
            say(f"The Worker and Reviewer re-run round {run.round} with your note.")
