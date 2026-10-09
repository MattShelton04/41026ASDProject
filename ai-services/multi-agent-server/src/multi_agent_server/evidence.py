"""Export one run's workflow history, coordination audit and summary for the report."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from multi_agent_server.store import AUDIT_FILE, HISTORY_FILE, jsonl
from shared_contracts.multi_agent import FindingOutcome, WorkflowRun, WorkflowRunHistory

RUN_FILE = "run.json"
SUMMARY_FILE = "summary.md"


def export_run(run: WorkflowRun, history: WorkflowRunHistory, destination: Path) -> list[Path]:
    """Write ``run.json``, both JSONL logs and ``summary.md``; return the written paths."""
    destination.mkdir(parents=True, exist_ok=True)
    files = {
        RUN_FILE: json.dumps(run.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        HISTORY_FILE: jsonl(history.history),
        AUDIT_FILE: jsonl(history.audit),
        SUMMARY_FILE: render_summary(run, history),
    }
    written: list[Path] = []
    for name, content in files.items():
        path = destination / name
        path.write_text(content, encoding="utf-8", newline="\n")
        written.append(path)
    return written


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_summary(run: WorkflowRun, history: WorkflowRunHistory) -> str:
    """A Markdown report of the run suitable for ``docs/release-2/evidence``."""
    lines = [
        f"# Multi-agent workflow run `{run.id}`",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Template | `{run.template_id}` {run.template_version} |",
        f"| Feature | `{run.feature_id}` |",
        f"| Final state | **{run.state.value}** |",
        f"| Rounds | {run.round} |",
        f"| Requested by | {_cell(run.requested_by)} |",
        f"| Request ID | `{run.request_id}` |",
        f"| Agents | {run.provider_mode} provider |",
        f"| Created | {run.created_at.isoformat()} |",
        f"| Completed | {run.completed_at.isoformat() if run.completed_at else '-'} |",
        f"| Input | `{_cell(json.dumps(run.input, sort_keys=True))}` |",
        "",
        "## Workflow history",
        "",
        "| # | Time | From | To | Actor | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for entry in history.history:
        lines.append(
            f"| {entry.sequence} | {entry.at.isoformat()} | "
            f"{entry.from_state.value if entry.from_state else '-'} | {entry.to_state.value} | "
            f"{_cell(entry.actor)} ({entry.role.value}) | {_cell(entry.reason)} |"
        )
    if run.plan is not None:
        attribution = run.plan.produced_by
        lines += [
            "",
            "## Planner",
            "",
            f"{run.plan.summary}",
            "",
            f"Produced by `{attribution.provider}` / `{attribution.model}`, prompt "
            f"`{attribution.prompt_id}` {attribution.prompt_version}"
            + (" (deterministic fallback)" if attribution.fallback else "")
            + ".",
            "",
            "| # | Step | Tool | Arguments | Required |",
            "|---|---|---|---|---|",
        ]
        for step in run.plan.steps:
            lines.append(
                f"| {step.index} | {_cell(step.title)} (`{step.id}`) | `{step.tool}` | "
                f"`{_cell(json.dumps(step.arguments, sort_keys=True))}` | {step.required} |"
            )
        lines += ["", "Evidence needed:", ""]
        lines += [f"- {_cell(item)}" for item in run.plan.evidence_needed]
    attempts = [*((attempt.worker_output, attempt.review) for attempt in run.superseded)]
    if run.worker_output is not None and run.review is not None:
        attempts.append((run.worker_output, run.review))
    for worker_output, review in attempts:
        lines += [
            "",
            f"## Worker (round {worker_output.round})",
            "",
            worker_output.summary,
        ]
        if worker_output.correction_note:
            lines += ["", f"Correction note: {_cell(worker_output.correction_note)}"]
        lines += ["", "| Step | Status | Findings |", "|---|---|---|"]
        for result in worker_output.steps:
            lines.append(
                f"| `{result.step_id}` | {result.status} | {_cell(' / '.join(result.findings))} |"
            )
        lines += [
            "",
            "| Evidence | Tool | Outcome | Transport | Result SHA-256 |",
            "|---|---|---|---|---|",
        ]
        for evidence in worker_output.evidence:
            lines.append(
                f"| `{evidence.id}` | `{evidence.tool_name}` {evidence.tool_version} | "
                f"{evidence.outcome.value} | {evidence.transport} | `{evidence.result_digest}` |"
            )
        lines += [
            "",
            f"## Reviewer (round {review.round})",
            "",
            review.summary,
            "",
            f"Recommendation: **{review.recommendation.value}**",
            "",
            "| Finding | Check | Severity | Outcome | Message | Recommendation |",
            "|---|---|---|---|---|---|",
        ]
        for finding in review.findings:
            lines.append(
                f"| `{finding.id}` | {finding.check_id or finding.source} | "
                f"{finding.severity.value} | "
                f"{'**fail**' if finding.outcome is FindingOutcome.FAIL else finding.outcome.value}"
                f" | {_cell(finding.message)} | {_cell(finding.recommendation or '-')} |"
            )
    lines += ["", "## Human decisions", ""]
    if run.decisions:
        lines += [
            "| Round | Decision | Actor | Time | Note | Result |",
            "|---|---|---|---|---|---|",
        ]
        for decision in run.decisions:
            accepted = (
                f" (accepted: {', '.join(decision.accepted_step_ids)})"
                if decision.accepted_step_ids
                else ""
            )
            lines.append(
                f"| {decision.round} | {decision.decision.value}{accepted} | "
                f"{_cell(decision.actor)} | {decision.decided_at.isoformat()} | "
                f"{_cell(decision.note or '-')} | {decision.resulting_state.value} |"
            )
    else:
        lines.append("No human decision has been recorded yet.")
    if run.error is not None:
        lines += ["", f"Failure: `{run.error.code}` - {run.error.message}"]
    lines += [
        "",
        "## Coordination audit",
        "",
        f"{len(history.audit)} event(s) in `{AUDIT_FILE}`: "
        + ", ".join(
            f"{event} x{count}"
            for event, count in sorted(
                Counter(entry.event.value for entry in history.audit).items()
            )
        ),
        "",
    ]
    return "\n".join(lines)
