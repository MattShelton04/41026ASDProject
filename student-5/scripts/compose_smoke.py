"""Deterministic Student 5 Compose smoke without third-party dependencies."""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from propertyscope_buyer_workspaces.clients import urlopen as dependency_urlopen
from propertyscope_buyer_workspaces.clients import validate_http_url

API = "/api/buyer-workspaces/v1/buyer-cases"


def require(condition: object, detail: object = "Compose smoke check failed") -> None:
    """Smoke checks must still execute when Python optimisation is enabled."""
    if not condition:
        raise RuntimeError(str(detail))


def request(
    base_url: str,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any]]:
    validate_http_url(base_url)
    data = None if body is None else json.dumps(body).encode()
    request_headers = {"Accept": "application/json", **(headers or {})}
    if data is not None:
        request_headers["Content-Type"] = "application/json"
    outbound = urllib.request.Request(  # noqa: S310 - base URL validated; wrapper rejects redirects
        f"{base_url}{path}", data=data, headers=request_headers, method=method
    )
    try:
        with dependency_urlopen(outbound, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        try:
            return error.code, json.load(error)
        finally:
            error.close()


def initial(frontend: str, shared: str, state_path: Path) -> None:
    with dependency_urlopen(
        urllib.request.Request(f"{frontend}/health/ready"),  # noqa: S310 - wrapper validates HTTP(S) before opening
        timeout=10,
    ) as response:
        require(response.status == 200)
    with dependency_urlopen(
        urllib.request.Request(f"{shared}/fragments/research-areas.html"),  # noqa: S310 - wrapper validates HTTP(S) before opening
        timeout=10,
    ) as response:
        require(b"/features/buyer-workspaces/#buyer-cases" in response.read())

    status, page = request(frontend, "GET", API)
    require(status == 200 and page["total"] >= 10, page)
    deleted_seed_id = page["items"][0]["id"]
    status, _ = request(frontend, "DELETE", f"{API}/{deleted_seed_id}")
    require(status == 200)

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
    require(status == 201, persisted)
    case_id = persisted["id"]
    status, updated = request(
        frontend,
        "PUT",
        f"{API}/{case_id}",
        {"version": persisted["version"], "status": "paused"},
    )
    require(status == 200 and updated["status"] == "paused", updated)
    status, opened = request(frontend, "GET", f"{API}/{case_id}")
    require(status == 200 and opened["id"] == case_id)

    status, disposable = request(frontend, "POST", API, {"name": "Disposable smoke case"})
    require(status == 201)
    status, _ = request(frontend, "DELETE", f"{API}/{disposable['id']}")
    require(status == 200)

    status, property_item = request(
        frontend,
        "POST",
        f"{API}/{case_id}/properties",
        {
            "property_ref": "a0000000-0000-0000-0000-000000009999",
            "property_label": "Unverified smoke candidate",
        },
    )
    require(status == 201 and property_item["property_validation_state"] == "unavailable")
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
    require(status == 200 and property_item["journey_stage"] == "Inspecting")

    status, note = request(
        frontend,
        "POST",
        f"{API}/{case_id}/notes",
        {"case_property_id": property_id, "content": "Smoke note"},
    )
    require(status == 201)
    status, note = request(
        frontend,
        "PUT",
        f"{API}/{case_id}/notes/{note['id']}",
        {"version": note["version"], "content": "Updated smoke note"},
    )
    require(status == 200)
    status, _ = request(frontend, "DELETE", f"{API}/{case_id}/notes/{note['id']}")
    require(status == 200)

    status, task = request(
        frontend,
        "POST",
        f"{API}/{case_id}/tasks",
        {"case_property_id": property_id, "title": "Complete smoke task"},
    )
    require(status == 201)
    status, task = request(
        frontend,
        "PUT",
        f"{API}/{case_id}/tasks/{task['id']}",
        {"version": task["version"], "completed": True},
    )
    require(status == 200 and task["completed"] is True)
    status, _ = request(frontend, "DELETE", f"{API}/{case_id}/tasks/{task['id']}")
    require(status == 200)

    status, evidence = request(frontend, "GET", f"{API}/{case_id}/evidence")
    require(status == 200)
    require(evidence["sections"]["feature_3"]["state"] == "unavailable")
    require(
        all(
            section["state"]
            in {"complete", "partial", "unavailable", "needs_verification", "conflicting"}
            for section in evidence["sections"].values()
        )
    )

    check_ai_disabled(frontend, case_id)
    status, _ = request(frontend, "GET", API)
    require(status == 200)

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"case_id": case_id, "deleted_seed_id": deleted_seed_id}),
        encoding="utf-8",
    )


def check_ai_disabled(frontend: str, case_id: str) -> None:
    """CI must exercise truthful degradation without starting host AI services."""
    status, problem = request(
        frontend,
        "POST",
        f"{API}/{case_id}/case-summary-runs",
        {},
        headers={"Idempotency-Key": "student5-compose-smoke-summary"},
    )
    require(status == 503 and problem["code"] == "integration_unavailable", problem)
    status, problem = request(
        frontend,
        "POST",
        "/api/buyer-workspaces/v1/assistant/turns",
        {"message": "How do I manage a shortlist?", "scope": "guidance"},
    )
    require(status == 503 and problem["code"] == "integration_unavailable", problem)
    status, problem = request(frontend, "GET", f"{API}/{case_id}/evidence-reviews/template")
    require(status == 503 and problem["code"] == "multi_agent_unavailable", problem)


def verify_restart(frontend: str, state_path: Path) -> None:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    status, persisted = request(frontend, "GET", f"{API}/{state['case_id']}")
    require(status == 200 and persisted["name"] == "Compose persistence probe")
    status, _ = request(frontend, "GET", f"{API}/{state['deleted_seed_id']}")
    require(status == 404)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("initial", "verify-restart"))
    parser.add_argument("--frontend", default="http://127.0.0.1:5500")
    parser.add_argument("--shared", default="http://127.0.0.1:5100")
    parser.add_argument("--state", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.phase == "initial":
        initial(arguments.frontend, arguments.shared, arguments.state)
    else:
        time.sleep(1)
        verify_restart(arguments.frontend, arguments.state)
    print(f"Student 5 Compose smoke {arguments.phase} passed")


if __name__ == "__main__":
    main()
