from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core.tools import ToolRegistry
from ai_mode.tool_catalog import load_tool_catalog
from propertyscope_data_platform.run_insight import build_run_inspection

ROOT = Path(__file__).resolve().parents[2]


def _definition() -> Any:
    catalog = load_tool_catalog(ROOT / "tool-catalog.yaml")
    return next(
        registration.definition
        for registration in catalog.tools
        if registration.definition.name == "data.run_explain.v1"
    )


def test_running_inspection_selects_active_task_and_reports_saved_progress() -> None:
    run_id = "70000000-0000-4000-8000-000000000001"
    active_task_id = "71000000-0000-4000-8000-000000000002"
    result = build_run_inspection(
        {
            "id": run_id,
            "job_definition_id": "72000000-0000-4000-8000-000000000001",
            "job_name": "G-NAF NSW complete update",
            "source_definition_id": "73000000-0000-4000-8000-000000000001",
            "source_name": "G-NAF Open NSW",
            "status": "acquiring",
            "run_mode": "full_refresh",
            "profile_key": "gnaf-nsw-full",
            "requested_scope_json": {"profile": "full-data", "all_records": True},
            "attempt_number": 1,
            "requested_at": "2026-08-29T01:00:00Z",
            "started_at": "2026-08-29T01:01:00Z",
            "heartbeat_at": "2026-08-29T01:06:00Z",
            "rows_discovered": 125_000,
            "rows_staged": 0,
            "rows_accepted": 0,
            "rows_rejected": 0,
            "source_snapshot_json": {"private": "not model context"},
            "lease_token": "not model context",
        },
        [
            {
                "id": "71000000-0000-4000-8000-000000000001",
                "logical_key": "01-plan",
                "stage": "plan",
                "status": "succeeded",
                "attempt_number": 1,
                "started_at": "2026-08-29T01:01:00Z",
                "finished_at": "2026-08-29T01:01:01Z",
                "rows_in": 0,
                "rows_out": 0,
            },
            {
                "id": "71000000-0000-4000-8000-000000000003",
                "logical_key": "03-import",
                "stage": "import",
                "status": "pending",
                "attempt_number": 1,
            },
            {
                "id": active_task_id,
                "logical_key": "02-acquire",
                "stage": "acquire",
                "status": "running",
                "attempt_number": 1,
                "started_at": "2026-08-29T01:01:01Z",
                "heartbeat_at": "2026-08-29T01:06:00Z",
                "progress_phase": "canonicalising",
                "progress_rows": 125_000,
                "progress_total_rows": 5_190_134,
                "progress_bytes": 0,
                "progress_total_bytes": None,
                "progress_updated_at": "2026-08-29T01:05:59Z",
                "rows_in": 0,
                "rows_out": 0,
                "lease_token": "not model context",
            },
        ],
        [],
    )

    assert result["insight"]["current_task_id"] == active_task_id
    assert result["insight"]["headline"] == "acquire is running"
    assert result["insight"]["progress"] == {
        "basis": "rows",
        "processed": 125_000,
        "total": 5_190_134,
        "percent_complete": 2.4,
        "updated_at": "2026-08-29T01:05:59Z",
    }
    assert result["run"]["scope"]["explicit_complete_source"] is True
    assert "remaining-time estimate" in result["insight"]["limitations"][1]
    assert "lease_token" not in str(result)
    assert "source_snapshot_json" not in str(result)
    ToolRegistry((_definition(),)).validate_output(_definition(), result)


def test_failed_inspection_bounds_errors_and_quality_without_inventing_an_eta() -> None:
    result = build_run_inspection(
        {
            "id": "70000000-0000-4000-8000-000000000002",
            "job_definition_id": "72000000-0000-4000-8000-000000000002",
            "source_definition_id": "73000000-0000-4000-8000-000000000002",
            "status": "failed",
            "run_mode": "full_refresh",
            "attempt_number": 2,
            "requested_scope_json": {},
            "requested_at": "2026-08-29T02:00:00Z",
            "started_at": "2026-08-29T02:01:00Z",
            "finished_at": "2026-08-29T02:02:00Z",
            "error_json": {
                "code": "source_unavailable",
                "message": "Publisher connection closed",
                "retryable": True,
                "private_trace": "not projected",
            },
        },
        [
            {
                "id": "71000000-0000-4000-8000-000000000004",
                "logical_key": "02-acquire",
                "stage": "acquire",
                "status": "failed",
                "attempt_number": 2,
                "rows_in": 0,
                "rows_out": 0,
                "error_json": {"detail": "Publisher connection closed", "stack": "private"},
                "started_at": "2026-08-29T02:01:00Z",
                "finished_at": "2026-08-29T02:02:00Z",
            }
        ],
        [
            {
                "rule_key": "artifact.checksum",
                "dimension": "reproducibility",
                "severity": "blocking",
                "status": "fail",
                "message": "Artifact checksum did not match.",
                "sample_json": {"private": "not projected"},
            }
        ],
    )

    assert result["insight"]["current_task_id"] is None
    assert result["insight"]["failed_tasks"] == 1
    assert result["insight"]["progress"]["percent_complete"] is None
    assert result["run"]["error"] == {
        "code": "source_unavailable",
        "category": None,
        "message": "Publisher connection closed",
        "retryable": True,
    }
    assert "private_trace" not in str(result)
    assert "sample_json" not in str(result)
    assert all("ETA" not in item for item in result["insight"]["observations"])
    ToolRegistry((_definition(),)).validate_output(_definition(), result)


def test_failed_import_reason_is_available_to_the_ai_explanation_tool() -> None:
    message = "Import stopped because record 1978 postcode must contain four digits."
    result = build_run_inspection(
        {
            "id": "70000000-0000-4000-8000-000000000003",
            "status": "failed",
            "run_mode": "reprocess_cached",
            "error_json": {
                "code": "canonical_record_invalid",
                "category": "data_validation",
                "message": message,
                "retryable": False,
            },
        },
        [
            {
                "id": "71000000-0000-4000-8000-000000000005",
                "logical_key": "02/import",
                "stage": "import",
                "status": "failed",
                "error_json": {
                    "code": "canonical_record_invalid",
                    "category": "data_validation",
                    "message": message,
                    "retryable": False,
                },
            }
        ],
        [],
    )

    assert result["run"]["error"]["message"] == message
    assert result["tasks"][0]["error"]["category"] == "data_validation"
    assert any(message in item for item in result["insight"]["observations"])
    ToolRegistry((_definition(),)).validate_output(_definition(), result)
