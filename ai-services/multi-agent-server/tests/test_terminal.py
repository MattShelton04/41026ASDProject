"""Terminal human review: the live coordination trail and the interactive decision prompt."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from multi_agent_server import cli
from multi_agent_server.cli import LocalBackend, render_run
from multi_agent_server.service import WorkflowService
from multi_agent_server.terminal import (
    Cursors,
    describe_audit,
    follow,
    interactive_review,
    prompt_decision,
    trail_lines,
)
from multi_agent_server.tools import FixtureToolGateway
from shared_contracts import ToolDefinition
from shared_contracts.multi_agent import (
    AgentRole,
    AuditEvent,
    CoordinationAuditEntry,
    HumanDecisionKind,
    WorkflowRunRequest,
    WorkflowState,
)

FIXTURES = Path(__file__).parent / "fixtures"
RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"
Factory = Callable[..., WorkflowService]


class Script:
    """Answers prompts in order; ends input (EOF) when it runs out."""

    def __init__(self, answers: Iterable[str]) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.answers:
            raise EOFError
        return self.answers.pop(0)


def start(service: WorkflowService) -> Any:
    return service.create_run(
        WorkflowRunRequest(
            template_id="example-readiness-review",
            input={"record_id": RECORD_ID},
            requested_by="tester",
        ),
        request_id="req-start",
    )


def review(
    service: WorkflowService, run_id: Any, answers: Iterable[str], **options: Any
) -> tuple[int, str, Script]:
    lines: list[str] = []
    script = Script(answers)
    code = interactive_review(
        LocalBackend(service),
        run_id,
        actor="analyst",
        ask=script,
        say=lines.append,
        render=render_run,
        **options,
    )
    return code, "\n".join(lines), script


def failing_gateway() -> FixtureToolGateway:
    payload = json.loads((FIXTURES / "tools.json").read_text(encoding="utf-8"))
    definitions = [ToolDefinition.model_validate(entry["definition"]) for entry in payload["tools"]]
    return FixtureToolGateway(
        definitions,
        {
            "example.record.v1": {"id": RECORD_ID, "item_count": 0},
            "example.quality.v1": {"checks": [{"name": "schema"}], "failed": 1},
        },
    )


def test_correction_then_partial_acceptance_in_the_terminal(service: WorkflowService) -> None:
    run = start(service)

    code, out, script = review(
        service,
        run.id,
        [
            "2",  # correct (round 1)
            "Recheck the quality results",
            "",  # keep the default name
            "",  # confirm
            "partial",  # round 2
            "ghost",  # not a step
            "1",
            "Only the record is ready",
            "lead",
            "y",
        ],
        follow_from=Cursors(),
    )

    assert code == 0
    # The live trail shows every hand-off and the human decisions in order.
    assert "plan.created" in out and "agent.handoff" in out and "tool.call" in out
    assert "handoff human -> worker with correction: Recheck the quality results" in out
    assert "== Human review: round 1 of 2 ==" in out
    assert "== Human review: round 2 of 2 ==" in out
    assert "Round 1 was corrected: Recheck the quality results" in out
    assert "Guidance: Approve the recommendation only when" in out
    assert "<- Reviewer suggests" in out
    assert "Recorded correct by analyst for round 1." in out
    assert "The Worker and Reviewer re-run round 2 with your note." in out
    assert "Not a step in this plan: ghost" in out
    assert "lead decided partial in round 2 -> partially_accepted" in out
    assert "not accepted quality" in out
    assert "Accepted steps: record; not accepted: quality" in out
    assert "Decision [1]: " in script.prompts  # the Reviewer's approve is the default
    final = service.get_run(run.id)
    assert final.state is WorkflowState.PARTIALLY_ACCEPTED
    assert [d.decision for d in final.decisions] == [
        HumanDecisionKind.CORRECT,
        HumanDecisionKind.PARTIAL,
    ]
    assert final.decisions[0].actor == "analyst"
    assert final.decisions[1].actor == "lead"


def test_final_round_correction_is_labelled_as_closing_the_run(service: WorkflowService) -> None:
    run = start(service)
    code, out, _ = review(
        service, run.id, ["correct", "first", "", "y", "correct", "second", "", "y"]
    )
    assert code == 0
    assert "Record your correction and close the run" in out
    assert service.get_run(run.id).state is WorkflowState.CORRECTED


def test_approving_over_failed_blocking_checks_needs_confirmation(
    service_factory: Factory,
) -> None:
    service = service_factory(gateway=failing_gateway())
    run = start(service)
    assert run.review.recommendation is HumanDecisionKind.CORRECT

    code, out, script = review(
        service,
        run.id,
        [
            "9",  # out of range
            "approve",
            "n",  # do not approve over the failed checks
            "4",  # reject
            "",  # a reject needs a note
            "x" * 2_001,
            "Item count is zero",
            "",
            "n",  # do not record yet
            "reject",
            "Item count is zero",
            "",
            "",
        ],
    )

    assert code == 0
    assert "Enter 1-4, a decision name, or q." in out
    assert any(
        "critical or high check(s) failed. Approve anyway? [y/N]" in p for p in script.prompts
    )
    assert "A reject decision needs a note." in out
    assert "Keep the note within 2000 characters." in out
    assert "Not recorded. Choose again." in out
    assert "Decision [2]: " in script.prompts  # the Reviewer suggested correct
    assert service.get_run(run.id).state is WorkflowState.REJECTED


def test_deferring_or_ending_input_records_nothing(service: WorkflowService) -> None:
    run = start(service)

    code, out, _ = review(service, run.id, ["q"])
    assert code == 0 and "Nothing recorded. Resume with: multi-agent-server review" in out

    code, out, _ = review(service, run.id, ["partial", ""])
    assert code == 2 and "Input ended; nothing recorded." in out
    assert service.get_run(run.id).state is WorkflowState.AWAITING_HUMAN
    assert service.get_run(run.id).decisions == ()


def test_partial_acceptance_needs_at_least_one_step(service: WorkflowService) -> None:
    run = start(service)
    lines: list[str] = []
    request = prompt_decision(
        run, actor="me", ask=Script(["3", ",", "record, record", "why", "", "y"]), say=lines.append
    )
    assert "Select at least one step." in lines
    assert request is not None and request.accepted_step_ids == ("record",)


def test_finished_and_failed_runs_are_shown_without_a_prompt(
    service: WorkflowService, service_factory: Factory, deferred: Any
) -> None:
    run = start(service)
    service.decide(
        run.id,
        cli.HumanDecisionRequest(decision=HumanDecisionKind.APPROVE, actor="me"),
        request_id="r",
    )
    code, out, script = review(service, run.id, [])
    assert code == 0 and "approved" in out and not script.prompts

    waiting = service_factory("other", executor=deferred)
    stale = start(waiting)
    waiting.recover_interrupted()
    code, out, _ = review(waiting, stale.id, [])
    assert code == 1
    assert "Failed (during planner): interrupted" in out


def test_follow_prints_the_trail_while_agents_work(service_factory: Factory, deferred: Any) -> None:
    service = service_factory(executor=deferred)
    run = start(service)
    lines: list[str] = []
    naps: list[float] = []

    def nap(seconds: float) -> None:
        naps.append(seconds)
        deferred.run_all()

    final, cursors = follow(
        LocalBackend(service), run.id, say=lines.append, interval=0.25, sleep=nap
    )

    assert final.state is WorkflowState.AWAITING_HUMAN
    assert naps == [0.25]
    assert lines[0].split()[1:5] == ["==", "r1", "system", "-"]
    assert any("planning -> working" in line for line in lines)
    assert any("review.completed" in line and "recommends APPROVE" in line for line in lines)
    page = service.history(run.id)
    assert (cursors.history, cursors.audit) == (page.history[-1].sequence, page.audit[-1].sequence)


def test_follow_gives_up_after_the_timeout(service_factory: Factory, deferred: Any) -> None:
    service = service_factory(executor=deferred)
    run = start(service)
    ticks = iter([0.0, 5.0])
    lines: list[str] = []

    final, _ = follow(
        LocalBackend(service), run.id, say=lines.append, timeout=1, clock=lambda: next(ticks)
    )

    assert final.state is WorkflowState.PLANNING
    assert lines[-1] == "Still planning after 1 s; stopped following."


def entry(event: AuditEvent, detail: dict[str, Any], actor: str = "worker") -> Any:
    return CoordinationAuditEntry(
        sequence=1,
        run_id=uuid4(),
        request_id="req",
        at=datetime(2026, 10, 15, tzinfo=UTC),
        event=event,
        role=AgentRole.WORKER,
        actor=actor,
        round=1,
        detail=detail,
    )


@pytest.mark.parametrize(
    ("event", "detail", "expected"),
    [
        (
            AuditEvent.MODEL_STARTED,
            {"attempt": 1, "model_profile": "p", "prompt_id": "planner", "prompt_version": "v1"},
            "model call 1 started: p, prompt planner v1",
        ),
        (
            AuditEvent.MODEL_INVOCATION,
            {
                "attempt": 2,
                "outcome": "succeeded",
                "provider": "openai",
                "model": "gpt",
                "prompt_tokens": 10,
                "output_tokens": 5,
                "duration_ms": 7,
            },
            "model call 2 succeeded: openai/gpt, 10+5 tokens, 7 ms",
        ),
        (
            AuditEvent.MODEL_INVOCATION,
            {"attempt": 1, "outcome": "provider_error", "error": "provider_down"},
            "model call 1 provider_error (provider_down)",
        ),
        (
            AuditEvent.MODEL_FALLBACK,
            {"reason": "invalid_output", "fallback_provider": "deterministic"},
            "fell back to deterministic after invalid_output",
        ),
        (
            AuditEvent.TOOL_REJECTED,
            {
                "step_id": "s",
                "tool_name": "t.v1",
                "outcome": "rejected",
                "transport": "mcp",
                "duration_ms": 0,
                "evidence_id": "ev",
            },
            "step s: t.v1 rejected via mcp in 0 ms -> ev",
        ),
        (
            AuditEvent.RUN_FAILED,
            {"code": "worker_output_unavailable", "stage": "worker"},
            "run failed: worker_output_unavailable during worker",
        ),
        (AuditEvent.RUN_FAILED, {"code": "x"}, "run failed: x during unknown stage"),
        (
            AuditEvent.RUN_CANCELLED,
            {"previous_state": "awaiting_human"},
            "cancelled by worker while awaiting_human",
        ),
    ],
)
def test_describe_audit_sentences(event: AuditEvent, detail: dict[str, Any], expected: str) -> None:
    assert describe_audit(entry(event, detail)) == expected


def test_long_notes_are_shortened_in_the_trail() -> None:
    text = describe_audit(
        entry(
            AuditEvent.HANDOFF,
            {"from": "human", "to": "worker", "correction_note": "word " * 40},
        )
    )
    assert text.endswith("...") and len(text) < 140


def test_history_command_prints_a_readable_trail(service: WorkflowService) -> None:
    run = start(service)
    lines = trail_lines(service.history(run.id))
    assert lines[0].split()[1] == "=="
    assert any("run.created" in line and "run accepted for tester" in line for line in lines)
    assert any("worker.completed" in line and "2/2 step(s)" in line for line in lines)
