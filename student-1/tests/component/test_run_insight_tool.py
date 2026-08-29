from __future__ import annotations

import httpx

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient


def test_run_inspection_tool_returns_bounded_current_activity_evidence() -> None:
    run_id = "70000000-0000-4000-8000-000000000005"
    task_id = "71000000-0000-4000-8000-000000000005"

    def database(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"/internal/data-platform/v1/runs/{run_id}":
            return httpx.Response(
                200,
                json={
                    "run": {
                        "id": run_id,
                        "job_definition_id": "72000000-0000-4000-8000-000000000005",
                        "job_name": "Complete address update",
                        "source_definition_id": "73000000-0000-4000-8000-000000000005",
                        "source_name": "G-NAF Open NSW",
                        "status": "staging",
                        "run_mode": "full_refresh",
                        "profile_key": "gnaf-nsw-full",
                        "requested_scope_json": {"profile": "full-data", "all_records": True},
                        "attempt_number": 1,
                        "requested_at": "2026-08-29T03:00:00Z",
                        "started_at": "2026-08-29T03:01:00Z",
                        "heartbeat_at": "2026-08-29T03:07:00Z",
                        "rows_discovered": 5_190_134,
                        "rows_staged": 2_000_000,
                        "rows_accepted": 0,
                        "rows_rejected": 0,
                        "lease_token": "must-not-leave-feature-service",
                    }
                },
            )
        if request.url.path == f"/internal/data-platform/v1/runs/{run_id}/tasks":
            assert request.url.params["limit"] == "100"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": task_id,
                            "logical_key": "03-import",
                            "stage": "import",
                            "status": "running",
                            "attempt_number": 1,
                            "started_at": "2026-08-29T03:05:00Z",
                            "heartbeat_at": "2026-08-29T03:07:00Z",
                            "progress_phase": "copying",
                            "progress_rows": 2_000_000,
                            "progress_total_rows": 5_190_134,
                            "progress_bytes": 200_000_000,
                            "progress_total_bytes": 515_790_493,
                            "progress_updated_at": "2026-08-29T03:06:59Z",
                            "rows_in": 5_190_134,
                            "rows_out": 0,
                            "lease_owner": "must-not-leave-feature-service",
                        }
                    ]
                },
            )
        if request.url.path == f"/internal/data-platform/v1/runs/{run_id}/quality-results":
            assert request.url.params["limit"] == "100"
            return httpx.Response(200, json={"items": []})
        raise AssertionError(f"Unexpected request: {request.url}")

    transport = httpx.MockTransport(database)
    app = create_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=transport)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=transport)),
    )

    response = app.test_client().post(
        "/api/data-platform/v1/tools/runs.explain.v1", json={"run_id": run_id}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["insight"]["current_task_id"] == task_id
    assert body["insight"]["current_stage"] == "import"
    assert body["insight"]["progress"] == {
        "basis": "rows",
        "processed": 2_000_000,
        "total": 5_190_134,
        "percent_complete": 38.5,
        "updated_at": "2026-08-29T03:06:59Z",
    }
    assert body["run"]["counts"]["rows_discovered"] == 5_190_134
    assert body["tasks"][0]["progress"]["phase"] == "copying"
    assert "lease_token" not in str(body)
    assert "lease_owner" not in str(body)
