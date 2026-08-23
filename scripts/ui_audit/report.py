"""Atomic artifact persistence and compact report generation."""

from __future__ import annotations

import html
import json
import os
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator

if TYPE_CHECKING:
    from scripts.ui_audit.config import AuditConfig
    from scripts.ui_audit.models import AuditBatch

REPORT_SCHEMA = Path(__file__).with_name("audit-report.schema.json")


def atomic_json(path: Path, value: object) -> None:
    """Write JSON through a sibling temporary file and atomic replacement."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def load_completed_batch(path: Path, fingerprint: str) -> dict[str, Any] | None:
    """Load a completed matching batch, ignoring partial/corrupt state."""
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("fingerprint") != fingerprint or value.get("status") not in {
        "passed",
        "failed",
    }:
        return None
    return value


def summary_for(
    batches: list[dict[str, Any]],
    *,
    planned_batches: tuple[AuditBatch, ...],
    config: AuditConfig,
    deferred_states: int,
) -> dict[str, Any]:
    """Build coverage and finding counts from durable batch results."""
    statuses = Counter(str(batch.get("status", "unknown")) for batch in batches)
    findings = [
        finding
        for batch in batches
        for finding in batch.get("findings", [])
        if isinstance(finding, dict)
    ]
    severities = Counter(str(finding.get("severity", "unknown")) for finding in findings)
    codes = Counter(str(finding.get("code", "unknown")) for finding in findings)
    inventory = sum(int(batch.get("inventory", {}).get("count", 0)) for batch in batches)
    interactions = Counter(
        str(item.get("status", "unknown"))
        for batch in batches
        for item in batch.get("interactions", [])
        if isinstance(item, dict)
    )
    selected_states = {
        (batch.route_id, state) for batch in planned_batches for state in batch.case.states
    }
    captured_states = {
        (str(batch.get("routeId")), str(state))
        for batch in batches
        if batch.get("baseline", {}).get("screenshot")
        for state in batch.get("case", {}).get("states", [])
    }
    configured_states = sum(
        len({state for case in route.cases for state in case.states}) + len(route.deferred_states)
        for route in config.routes
    )
    executable_states = configured_states - deferred_states
    total_planned = len(planned_batches)
    selected_route_ids = {batch.route_id for batch in planned_batches}
    selected_interaction_intents = sum(
        len(route.configured_interactions)
        for route in config.routes
        if route.id in selected_route_ids
    )
    return {
        "batches": {
            "planned": total_planned,
            "completed": len(batches),
            "passed": statuses["passed"],
            "failed": statuses["failed"],
            "resumed": sum(1 for batch in batches if batch.get("resumed") is True),
        },
        "baselines": {
            "required": total_planned,
            "captured": sum(1 for batch in batches if batch.get("baseline", {}).get("screenshot")),
        },
        "controls": {
            "configuredIntents": selected_interaction_intents,
            "inventoried": inventory,
            "exercised": interactions["exercised"],
            "notReplayed": max(0, inventory - sum(interactions.values())),
            "skippedDestructive": interactions["skipped-destructive"],
            "unreachable": interactions["unreachable"],
            "errors": interactions["error"],
        },
        "states": {
            "configured": configured_states,
            "executable": executable_states,
            "deferred": deferred_states,
            "selected": len(selected_states),
            "captured": len(captured_states),
        },
        "routes": {
            "configured": len(config.routes),
            "selected": len(selected_route_ids),
            "captured": len(
                {
                    str(batch.get("routeId"))
                    for batch in batches
                    if batch.get("baseline", {}).get("screenshot")
                }
            ),
        },
        "findings": {"bySeverity": dict(severities), "byCode": dict(codes)},
        "durationMs": sum(int(batch.get("durationMs", 0)) for batch in batches),
    }


def write_reports(output: Path, report: dict[str, Any]) -> None:
    """Persist the machine report and regenerate compact human summaries."""
    schema = json.loads(REPORT_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(report)
    atomic_json(output / "audit.json", report)
    (output / "index.html").write_text(_html(report), encoding="utf-8")
    (output / "TRIAGE.md").write_text(_markdown(report), encoding="utf-8")


def _html(report: dict[str, Any]) -> str:
    rows: list[str] = []
    for batch in report.get("batches", []):
        findings = batch.get("findings", [])
        errors = sum(1 for item in findings if item.get("severity") == "error")
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(batch.get('workspace', '')))}</td>"
            f"<td><code>{html.escape(str(batch.get('routeId', '')))}</code></td>"
            f"<td>{html.escape(str(batch.get('case', {}).get('id', '')))}</td>"
            f"<td>{html.escape(str(batch.get('viewport', {}).get('id', '')))}</td>"
            f"<td>{html.escape(str(batch.get('status', '')))}</td><td>{errors}</td>"
            "</tr>"
        )
    summary = report.get("summary", {})
    return (
        "<!doctype html><meta charset='utf-8'><title>PropertyScope UI audit</title>"
        "<style>body{font:15px/1.5 system-ui;margin:32px;color:#17202a}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #d7dde3;"
        "padding:8px;text-align:left}th{background:#f3f6f8}code{font-size:13px}</style>"
        "<h1>PropertyScope UI audit</h1>"
        f"<p><strong>{summary.get('batches', {}).get('completed', 0)}</strong> batches completed; "
        f"<strong>{summary.get('findings', {}).get('bySeverity', {}).get('error', 0)}</strong> "
        "gating findings.</p><table><thead><tr><th>Workspace</th><th>Route</th>"
        "<th>Case</th><th>Viewport</th><th>Status</th><th>Errors</th></tr></thead><tbody>"
        + "".join(rows)
        + "</tbody></table><p>See <code>audit.json</code> and <code>TRIAGE.md</code>.</p>"
    )


def _markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    batch = summary.get("batches", {})
    controls = summary.get("controls", {})
    findings = summary.get("findings", {})
    run = report.get("run", {})
    return "\n".join(
        (
            "# UI audit triage",
            "",
            f"- Profile: `{run.get('profile', 'unknown')}`",
            f"- Batches: {batch.get('completed', 0)}/{batch.get('planned', 0)} completed; "
            f"{batch.get('failed', 0)} failed; {batch.get('resumed', 0)} resumed",
            f"- Baselines: {summary.get('baselines', {}).get('captured', 0)}/"
            f"{summary.get('baselines', {}).get('required', 0)} captured",
            f"- Controls: {controls.get('inventoried', 0)} inventoried; "
            f"{controls.get('exercised', 0)} exercised; "
            f"{controls.get('notReplayed', 0)} not replayed in this profile; "
            f"{controls.get('skippedDestructive', 0)} destructive confirmations skipped; "
            f"{controls.get('unreachable', 0)} unreachable",
            f"- Findings: {json.dumps(findings.get('bySeverity', {}), sort_keys=True)}",
            f"- Deferred configured states: {summary.get('states', {}).get('deferred', 0)}",
            f"- Selected state coverage: {summary.get('states', {}).get('captured', 0)}/"
            f"{summary.get('states', {}).get('selected', 0)}",
            f"- Accumulated batch time: {summary.get('durationMs', 0)} ms",
            f"- Artifacts: `{run.get('artifactRoot', '')}`",
            "",
        )
    )
