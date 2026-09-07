"""Deterministic Student 5 Compose smoke without third-party dependencies."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

API = "/api/buyer-workspaces/v1/buyer-cases"
EXPECTED_TOOLS = [
    "buyer.cases.inspect.v1",
    "buyer.notes.list.v1",
    "buyer.tasks.list.v1",
    "buyer.evidence.collect.v1",
]


def request(
    base_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    data = None if body is None else json.dumps(body).encode()
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    outbound = urllib.request.Request(
        f"{base_url}{path}", data=data, headers=request_headers, method=method
    )
    try:
        with urllib.request.urlopen(outbound, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.load(error)
        finally:
            error.close()


def initial(frontend: str, shared: str, ai_mode: str, state_path: Path) -> None:
    with urllib.request.urlopen(f"{frontend}/health/ready", timeout=10) as response:
        assert response.status == 200
    with urllib.request.urlopen(f"{shared}/fragments/research-areas.html", timeout=10) as response:
        assert b"/features/buyer-workspaces/#buyer-cases" in response.read()

    status, page = request(frontend, "GET", API)
    assert status == 200 and page["total"] >= 10, page
    deleted_seed_id = page["items"][0]["id"]
    status, _ = request(frontend, "DELETE", f"{API}/{deleted_seed_id}")
    assert status == 200

    status, persisted = request(
        frontend,
        "POST",
        API,
        {
            "name": "Compose persistence probe",
            "preferences": {
                "dwelling_types": ["apartment"],
                "priorities": ["transport"],
            },
            "budget_min_aud": 700000,
            "budget_max_aud": 900000,
            "target_suburbs": [{"state": "NSW", "locality": "MASCOT"}],
        },
    )
    assert status == 201, persisted
    case_id = persisted["id"]
    status, updated = request(
        frontend,
        "PUT",
        f"{API}/{case_id}",
        {"version": persisted["version"], "status": "paused"},
    )
    assert status == 200 and updated["status"] == "paused", updated
    status, opened = request(frontend, "GET", f"{API}/{case_id}")
    assert status == 200 and opened["id"] == case_id

    status, disposable = request(frontend, "POST", API, {"name": "Disposable smoke case"})
    assert status == 201
    status, _ = request(frontend, "DELETE", f"{API}/{disposable['id']}")
    assert status == 200

    status, property_item = request(
        frontend,
        "POST",
        f"{API}/{case_id}/properties",
        {
            "property_ref": "a0000000-0000-0000-0000-000000009999",
            "property_label": "Unverified smoke candidate",
        },
    )
    assert status == 201 and property_item["property_validation_state"] == "unavailable"
    property_id = property_item["id"]
    status, property_item = request(
        frontend,
        "PUT",
        f"{API}/{case_id}/properties/{property_id}",
        {
            "version": property_item["version"],
            "journey_stage": "Inspecting",
            "rating": 4,
            "priority": "high",
        },
    )
    assert status == 200 and property_item["journey_stage"] == "Inspecting"

    status, note = request(
        frontend,
        "POST",
        f"{API}/{case_id}/notes",
        {"case_property_id": property_id, "content": "Smoke note"},
    )
    assert status == 201
    status, note = request(
        frontend,
        "PUT",
        f"{API}/{case_id}/notes/{note['id']}",
        {"version": note["version"], "content": "Updated smoke note"},
    )
    assert status == 200
    status, _ = request(frontend, "DELETE", f"{API}/{case_id}/notes/{note['id']}")
    assert status == 200

    status, task = request(
        frontend,
        "POST",
        f"{API}/{case_id}/tasks",
        {"case_property_id": property_id, "title": "Complete smoke task"},
    )
    assert status == 201
    status, task = request(
        frontend,
        "PUT",
        f"{API}/{case_id}/tasks/{task['id']}",
        {"version": task["version"], "completed": True},
    )
    assert status == 200 and task["completed"] is True
    status, _ = request(frontend, "DELETE", f"{API}/{case_id}/tasks/{task['id']}")
    assert status == 200

    status, evidence = request(frontend, "GET", f"{API}/{case_id}/evidence")
    assert status == 200
    assert evidence["sections"]["feature_3"]["state"] == "unavailable"
    assert all(
        section["state"]
        in {"complete", "partial", "unavailable", "needs_verification", "conflicting"}
        for section in evidence["sections"].values()
    )

    status, run = request(
        frontend,
        "POST",
        f"{API}/{case_id}/case-summary-runs",
        {},
        headers={"Idempotency-Key": "student5-compose-smoke-summary"},
    )
    assert status == 202, run
    run_id = run["id"]
    status, detail = request(ai_mode, "GET", f"/api/v1/agent-runs/{run_id}")
    assert status == 200
    assert detail["run"]["feature_key"] == "student-5-buyer-journey"
    assert detail["run"]["tool_allowlist"] == EXPECTED_TOOLS
    for _ in range(30):
        status, detail = request(ai_mode, "GET", f"/api/v1/agent-runs/{run_id}")
        assert status == 200
        if detail["run"]["status"] in {"succeeded", "failed", "cancelled"}:
            break
        time.sleep(1)
    assert detail["run"]["status"] in {"succeeded", "failed", "cancelled"}, detail
    status, public_run = request(frontend, "GET", f"{API}/{case_id}/case-summary-runs/{run_id}")
    assert status == 200
    assert [phase["name"] for phase in public_run["phases"]] == [
        "plan",
        "act",
        "observe",
        "adapt",
    ]
    if public_run["status"] == "failed":
        assert public_run["error"] == "The AI summary could not be generated."
    status, _ = request(frontend, "GET", API)
    assert status == 200

    state_path.write_text(
        json.dumps({"case_id": case_id, "deleted_seed_id": deleted_seed_id, "run_id": run_id}),
        encoding="utf-8",
    )


def verify_restart(frontend: str, state_path: Path) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    status, persisted = request(frontend, "GET", f"{API}/{state['case_id']}")
    assert status == 200 and persisted["name"] == "Compose persistence probe"
    status, _ = request(frontend, "GET", f"{API}/{state['deleted_seed_id']}")
    assert status == 404


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("initial", "verify-restart"))
    parser.add_argument("--frontend", default="http://127.0.0.1:5500")
    parser.add_argument("--shared", default="http://127.0.0.1:5100")
    parser.add_argument(
        "--ai-mode", help="AI API origin; defaults to the authenticated shared edge"
    )
    parser.add_argument("--state", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.phase == "initial":
        initial(
            arguments.frontend,
            arguments.shared,
            arguments.ai_mode or arguments.shared,
            arguments.state,
        )
    else:
        time.sleep(1)
        verify_restart(arguments.frontend, arguments.state)
    print(f"Student 5 Compose smoke {arguments.phase} passed")


if __name__ == "__main__":
    main()
