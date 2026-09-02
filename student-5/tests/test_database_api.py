"""Internal HTTP contract tests for the Phase 1 database service."""

from __future__ import annotations

import logging

import pytest
from flask.testing import FlaskClient
from propertyscope_buyer_store.repository import BuyerStore

BASE = "/internal/buyer-workspaces/v1"
HEADERS = {"X-PropertyScope-Internal-Token": "phase-one-test-token"}
CASE_1 = "b5000000-0000-4000-8000-000000000001"
CASE_2 = "b5000000-0000-4000-8000-000000000002"
PROPERTY_1 = "c5000000-0000-4000-8000-000000000001"


def test_health_is_public_and_truthful(client: FlaskClient) -> None:
    live = client.get("/health/live")
    ready = client.get("/health/ready")
    assert live.status_code == 200
    assert ready.status_code == 200
    assert live.get_json()["service"] == "propertyscope-buyer-store"
    assert ready.get_json()["checks"]["database"]["status"] == "healthy"


def test_internal_routes_require_token_and_return_problem_details(client: FlaskClient) -> None:
    response = client.get(f"{BASE}/buyer-cases")
    problem = response.get_json()
    assert response.status_code == 401
    assert response.content_type == "application/problem+json"
    assert problem["code"] == "unauthorised"
    assert problem["request_id"] == response.headers["X-Request-ID"]


def test_request_id_is_safely_echoed_or_replaced(client: FlaskClient) -> None:
    echoed = client.get(
        f"{BASE}/seed-report", headers={**HEADERS, "X-Request-ID": "phase1-request-7"}
    )
    replaced = client.get(
        f"{BASE}/seed-report", headers={**HEADERS, "X-Request-ID": "unsafe request id"}
    )
    assert echoed.headers["X-Request-ID"] == "phase1-request-7"
    assert replaced.headers["X-Request-ID"] != "unsafe request id"


def test_seed_report_and_fingerprint_are_token_protected(client: FlaskClient) -> None:
    report = client.get(f"{BASE}/seed-report", headers=HEADERS)
    fingerprint = client.get(f"{BASE}/schema/fingerprint", headers=HEADERS)
    retired_route = client.get(f"{BASE}/schema-fingerprint", headers=HEADERS)
    assert report.get_json()["minimum_satisfied"] is True
    assert report.get_json()["tables"]["buyer_case"] == 10
    assert fingerprint.get_json()["schema_version"] == 2
    assert fingerprint.get_json()["algorithm"] == "sha256"
    assert retired_route.status_code == 404


def test_case_api_crud_defaults_owner_and_rejects_stale_updates(client: FlaskClient) -> None:
    payload = {
        "name": "API-created search",
        "budget_min_aud": 800000,
        "budget_max_aud": 1000000,
        "preferences": {"beds": 2},
        "target_suburbs": [{"state": "NSW", "locality": "Sydney"}],
    }
    created_response = client.post(f"{BASE}/buyer-cases", json=payload, headers=HEADERS)
    created = created_response.get_json()
    assert created_response.status_code == 201
    assert created["owner_ref"] == "release0-demo-owner"
    assert created["status"] == "active"

    listed = client.get(f"{BASE}/buyer-cases?page=1&page_size=5", headers=HEADERS).get_json()
    assert listed["page_size"] == 5
    assert listed["total"] == 11
    assert client.get(f"{BASE}/buyer-cases/{created['id']}", headers=HEADERS).status_code == 200

    updated = client.put(
        f"{BASE}/buyer-cases/{created['id']}",
        json={"version": 1, "status": "paused"},
        headers=HEADERS,
    )
    assert updated.get_json()["version"] == 2
    stale = client.put(
        f"{BASE}/buyer-cases/{created['id']}",
        json={"version": 1, "status": "closed"},
        headers=HEADERS,
    )
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "version_conflict"
    deleted = client.delete(f"{BASE}/buyer-cases/{created['id']}", headers=HEADERS)
    assert deleted.status_code == 200
    assert client.get(f"{BASE}/buyer-cases/{created['id']}", headers=HEADERS).status_code == 404


def test_browser_cannot_select_owner_and_bad_pagination_is_rejected(client: FlaskClient) -> None:
    owner = client.post(
        f"{BASE}/buyer-cases",
        json={"name": "No", "owner_ref": "chosen-in-browser"},
        headers=HEADERS,
    )
    page = client.get(f"{BASE}/buyer-cases?page=0", headers=HEADERS)
    misspelled = client.post(
        f"{BASE}/buyer-cases",
        json={"name": "Example", "statuz": "closed"},
        headers=HEADERS,
    )
    assert owner.status_code == 422
    assert "server configured" in owner.get_json()["detail"]
    assert page.status_code == 422
    assert misspelled.status_code == 422
    assert misspelled.content_type == "application/problem+json"
    assert misspelled.get_json()["code"] == "validation_failed"
    assert "statuz" in misspelled.get_json()["detail"]


def test_unexpected_exceptions_are_logged_but_response_remains_safe(
    client: FlaskClient,
    store: BuyerStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail() -> dict[str, object]:
        raise RuntimeError("diagnostic marker")

    monkeypatch.setattr(store, "seed_report", fail)
    with caplog.at_level(logging.ERROR):
        response = client.get(f"{BASE}/seed-report", headers=HEADERS)
    assert response.status_code == 500
    assert response.content_type == "application/problem+json"
    assert response.get_json()["detail"] == "The service could not complete the request"
    assert "diagnostic marker" not in response.get_data(as_text=True)
    assert "Unexpected buyer store request failure" in caplog.text


def test_property_note_and_task_crud(client: FlaskClient) -> None:
    property_response = client.post(
        f"{BASE}/buyer-cases/{CASE_1}/properties",
        json={
            "property_ref": "95000000-0000-4000-8000-000000000099",
            "journey_stage": "Shortlisted",
            "rating": None,
            "priority": "high",
        },
        headers=HEADERS,
    )
    case_property = property_response.get_json()
    assert property_response.status_code == 201
    assert case_property["property_validation_state"] == "pending"
    assert (
        client.get(
            f"{BASE}/buyer-cases/{CASE_1}/properties/{case_property['id']}", headers=HEADERS
        ).status_code
        == 200
    )
    closed = client.put(
        f"{BASE}/buyer-cases/{CASE_1}/properties/{case_property['id']}",
        json={"version": 1, "journey_stage": "Closed"},
        headers=HEADERS,
    ).get_json()
    reopened = client.put(
        f"{BASE}/buyer-cases/{CASE_1}/properties/{case_property['id']}",
        json={"version": closed["version"], "journey_stage": "Shortlisted"},
        headers=HEADERS,
    ).get_json()
    assert reopened["journey_stage"] == "Shortlisted"

    note_response = client.post(
        f"{BASE}/buyer-cases/{CASE_1}/notes",
        json={"case_property_id": case_property["id"], "content": "Review evidence"},
        headers=HEADERS,
    )
    note = note_response.get_json()
    task_response = client.post(
        f"{BASE}/buyer-cases/{CASE_1}/tasks",
        json={
            "case_property_id": case_property["id"],
            "title": "Verify source",
            "due_date": "2026-09-20",
        },
        headers=HEADERS,
    )
    task = task_response.get_json()
    assert note_response.status_code == task_response.status_code == 201
    assert (
        client.get(f"{BASE}/buyer-cases/{CASE_1}/notes", headers=HEADERS).get_json()["total"] == 3
    )
    assert (
        client.get(f"{BASE}/buyer-cases/{CASE_1}/tasks", headers=HEADERS).get_json()["total"] == 4
    )

    note_updated = client.put(
        f"{BASE}/buyer-cases/{CASE_1}/notes/{note['id']}",
        json={"version": 1, "content": "Evidence reviewed"},
        headers=HEADERS,
    ).get_json()
    task_updated = client.put(
        f"{BASE}/buyer-cases/{CASE_1}/tasks/{task['id']}",
        json={"version": 1, "completed": True},
        headers=HEADERS,
    ).get_json()
    assert note_updated["content"] == "Evidence reviewed"
    assert task_updated["completed"] is True
    assert (
        client.get(f"{BASE}/buyer-cases/{CASE_1}/notes/{note['id']}", headers=HEADERS).status_code
        == 200
    )
    assert (
        client.get(f"{BASE}/buyer-cases/{CASE_1}/tasks/{task['id']}", headers=HEADERS).status_code
        == 200
    )
    assert (
        client.delete(
            f"{BASE}/buyer-cases/{CASE_1}/notes/{note['id']}", headers=HEADERS
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"{BASE}/buyer-cases/{CASE_1}/tasks/{task['id']}", headers=HEADERS
        ).status_code
        == 200
    )
    assert (
        client.delete(
            f"{BASE}/buyer-cases/{CASE_1}/properties/{case_property['id']}", headers=HEADERS
        ).status_code
        == 200
    )


def test_duplicate_and_cross_case_relationships_return_safe_problems(client: FlaskClient) -> None:
    duplicate = client.post(
        f"{BASE}/buyer-cases/{CASE_1}/properties",
        json={"property_ref": "a0000000-0000-0000-0000-000000000001"},
        headers=HEADERS,
    )
    mismatch = client.post(
        f"{BASE}/buyer-cases/{CASE_2}/notes",
        json={"case_property_id": PROPERTY_1, "content": "Wrong relationship"},
        headers=HEADERS,
    )
    assert duplicate.status_code == 409
    assert duplicate.get_json()["code"] == "duplicate_case_property"
    assert mismatch.status_code == 422
    assert mismatch.get_json()["code"] == "property_case_mismatch"
    assert "case_property_case_mismatch" not in mismatch.get_data(as_text=True)


def test_invalid_uuid_and_unknown_resources_use_problem_details(client: FlaskClient) -> None:
    invalid = client.get(f"{BASE}/buyer-cases/not-a-uuid", headers=HEADERS)
    unknown = client.get(
        f"{BASE}/buyer-cases/95000000-0000-4000-8000-000000000404", headers=HEADERS
    )
    assert invalid.status_code == unknown.status_code == 404
    assert invalid.content_type == unknown.content_type == "application/problem+json"
