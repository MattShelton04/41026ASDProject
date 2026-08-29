"""Bounded, evidence-only projections for explaining one ingestion run."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

JsonObject = dict[str, Any]

_ACTIVE_TASK_STATUSES = ("running", "claimed", "retry_wait", "pending")


def _text(value: object, *, limit: int = 500) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered[:limit] if rendered else None


def _integer(value: object) -> int:
    try:
        if not isinstance(value, (bool, int, float, str)):
            return 0
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    return _integer(value)


def _timestamp(record: Mapping[str, Any], name: str) -> str | None:
    return _text(record.get(name), limit=80)


def _latest_timestamp(record: Mapping[str, Any], names: Sequence[str]) -> str | None:
    timestamps = [value for name in names if (value := _timestamp(record, name)) is not None]
    return max(timestamps) if timestamps else None


def _error(value: object) -> JsonObject | None:
    if not isinstance(value, Mapping):
        return None
    message = _text(value.get("message") or value.get("detail") or value.get("reason"))
    if message is None:
        message = "A structured error was recorded without a public message."
    retryable = value.get("retryable")
    return {
        "code": _text(value.get("code") or value.get("type"), limit=120),
        "category": _text(value.get("category"), limit=120),
        "message": message,
        "retryable": retryable if isinstance(retryable, bool) else None,
    }


def _scope(run: Mapping[str, Any]) -> JsonObject:
    raw = run.get("requested_scope_json")
    scope = raw if isinstance(raw, Mapping) else {}
    all_records = scope.get("all_records")
    profile = _text(scope.get("profile"), limit=100)
    return {
        "profile": profile,
        "all_records": all_records if isinstance(all_records, bool) else None,
        "explicit_complete_source": bool(
            all_records is True or profile in {"full-data", "all-records"}
        ),
    }


def _task_projection(task: Mapping[str, Any]) -> JsonObject:
    return {
        "id": _text(task.get("id"), limit=80),
        "logical_key": _text(task.get("logical_key"), limit=160) or "unknown",
        "stage": _text(task.get("stage"), limit=100) or "unknown",
        "status": _text(task.get("status"), limit=80) or "unknown",
        "attempt_number": max(1, _integer(task.get("attempt_number"))),
        "rows_in": _integer(task.get("rows_in")),
        "rows_out": _integer(task.get("rows_out")),
        "progress": {
            "phase": _text(task.get("progress_phase"), limit=160),
            "processed_rows": _integer(task.get("progress_rows")),
            "total_rows": _optional_integer(task.get("progress_total_rows")),
            "processed_bytes": _integer(task.get("progress_bytes")),
            "total_bytes": _optional_integer(task.get("progress_total_bytes")),
            "updated_at": _timestamp(task, "progress_updated_at"),
        },
        "timestamps": {
            "started_at": _timestamp(task, "started_at"),
            "last_activity_at": _latest_timestamp(
                task,
                (
                    "finished_at",
                    "progress_updated_at",
                    "heartbeat_at",
                    "updated_at",
                    "started_at",
                    "created_at",
                ),
            ),
            "finished_at": _timestamp(task, "finished_at"),
        },
        "error": _error(task.get("error_json")),
    }


def _quality_projection(result: Mapping[str, Any]) -> JsonObject:
    return {
        "rule_key": _text(result.get("rule_key"), limit=160) or "unknown",
        "dimension": _text(result.get("dimension"), limit=80) or "unknown",
        "severity": _text(result.get("severity"), limit=80) or "unknown",
        "status": _text(result.get("status"), limit=80) or "unknown",
        "message": _text(result.get("message")) or "No public quality message was recorded.",
    }


def _current_task(tasks: Sequence[JsonObject]) -> JsonObject | None:
    for status in _ACTIVE_TASK_STATUSES:
        for task in tasks:
            if task["status"] == status:
                return task
    return None


def _progress(task: JsonObject | None) -> JsonObject:
    if task is None:
        return {
            "basis": None,
            "processed": 0,
            "total": None,
            "percent_complete": None,
            "updated_at": None,
        }
    raw = task["progress"]
    assert isinstance(raw, dict)
    total_rows = raw["total_rows"]
    total_bytes = raw["total_bytes"]
    if isinstance(total_rows, int) and total_rows > 0:
        basis, processed, total = "rows", int(raw["processed_rows"]), total_rows
    elif isinstance(total_bytes, int) and total_bytes > 0:
        basis, processed, total = "bytes", int(raw["processed_bytes"]), total_bytes
    elif int(raw["processed_rows"]) > 0:
        basis, processed, total = "rows", int(raw["processed_rows"]), None
    elif int(raw["processed_bytes"]) > 0:
        basis, processed, total = "bytes", int(raw["processed_bytes"]), None
    else:
        basis, processed, total = None, 0, None
    percent = None if total is None else round(min(processed / total, 1.0) * 100, 1)
    return {
        "basis": basis,
        "processed": processed,
        "total": total,
        "percent_complete": percent,
        "updated_at": raw["updated_at"],
    }


def _insight(
    run: JsonObject, tasks: Sequence[JsonObject], quality_results: Sequence[JsonObject]
) -> JsonObject:
    terminal = run["status"] in {"succeeded", "failed", "cancelled", "interrupted"}
    current = None if terminal else _current_task(tasks)
    progress = _progress(current)
    succeeded = sum(task["status"] in {"succeeded", "skipped"} for task in tasks)
    failed = sum(task["status"] in {"failed", "cancelled"} for task in tasks)
    quality_failures = sum(result["status"] == "fail" for result in quality_results)
    observations = [f"The run is recorded as {run['status']}."]
    limitations = [
        "Progress values are durable checkpoints reported by the worker, not a forecast.",
        "No remaining-time estimate is produced because throughput can change between stages.",
    ]
    if current is not None:
        phase = current["progress"]["phase"]
        phase_suffix = f" ({phase})" if phase else ""
        observations.append(
            f"The current recorded task is {current['stage']}{phase_suffix} with status "
            f"{current['status']}."
        )
        if progress["basis"] is not None:
            if progress["total"] is None:
                observations.append(
                    f"The latest checkpoint reports {progress['processed']:,} "
                    f"{progress['basis']} processed; no total is recorded."
                )
            else:
                observations.append(
                    f"The latest checkpoint reports {progress['processed']:,} of "
                    f"{progress['total']:,} {progress['basis']} processed."
                )
    elif tasks:
        observations.append("No active task is recorded for this run state.")
    if run["error"] is not None:
        observations.append(f"The run error says: {run['error']['message']}")
    if quality_results:
        observations.append(
            f"{len(quality_results)} quality results are recorded, including "
            f"{quality_failures} failed checks."
        )
    headline = (
        f"{current['stage']} is {current['status']}"
        if current is not None
        else f"Run is {run['status']}"
    )
    return {
        "headline": headline,
        "current_task_id": current["id"] if current is not None else None,
        "current_stage": current["stage"] if current is not None else None,
        "current_task_status": current["status"] if current is not None else None,
        "completed_tasks": succeeded,
        "failed_tasks": failed,
        "total_tasks": len(tasks),
        "progress": progress,
        "observations": observations[:8],
        "limitations": limitations,
    }


def build_run_inspection(
    raw_run: Mapping[str, Any],
    raw_tasks: Sequence[Mapping[str, Any]],
    raw_quality_results: Sequence[Mapping[str, Any]],
) -> JsonObject:
    """Project one run into bounded evidence suitable for an AI observation."""
    tasks = [_task_projection(task) for task in raw_tasks[:100]]
    quality_results = [_quality_projection(result) for result in raw_quality_results[:100]]
    run: JsonObject = {
        "id": _text(raw_run.get("id"), limit=80),
        "job_definition_id": _text(raw_run.get("job_definition_id"), limit=80),
        "job_name": _text(raw_run.get("job_name"), limit=200),
        "source_definition_id": _text(raw_run.get("source_definition_id"), limit=80),
        "source_name": _text(raw_run.get("source_name"), limit=200),
        "status": _text(raw_run.get("status"), limit=80) or "unknown",
        "run_mode": _text(raw_run.get("run_mode"), limit=80) or "unknown",
        "profile_key": _text(raw_run.get("profile_key"), limit=120),
        "scope": _scope(raw_run),
        "attempt_number": max(1, _integer(raw_run.get("attempt_number"))),
        "parent_run_id": _text(raw_run.get("parent_run_id"), limit=80),
        "counts": {
            "rows_discovered": _integer(raw_run.get("rows_discovered")),
            "rows_staged": _integer(raw_run.get("rows_staged")),
            "rows_accepted": _integer(raw_run.get("rows_accepted")),
            "rows_rejected": _integer(raw_run.get("rows_rejected")),
        },
        "timestamps": {
            "requested_at": _timestamp(raw_run, "requested_at"),
            "started_at": _timestamp(raw_run, "started_at"),
            "last_activity_at": _latest_timestamp(
                raw_run,
                ("finished_at", "last_activity_at", "heartbeat_at", "started_at", "requested_at"),
            ),
            "finished_at": _timestamp(raw_run, "finished_at"),
        },
        "error": _error(raw_run.get("error_json")),
    }
    return {
        "run": run,
        "tasks": tasks,
        "quality_results": quality_results,
        "insight": _insight(run, tasks, quality_results),
    }
