"""Public Buyer Case API tests using an injected database gateway."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from flask.testing import FlaskClient
from propertyscope_buyer_workspaces.app import create_app
from propertyscope_buyer_workspaces.clients import ClientResponse, DatabaseUnavailableError
from propertyscope_buyer_workspaces.configuration import BackendSettings

API = "/api/buyer-workspaces/v1/buyer-cases"
OWNER = "release0-demo-owner"
CASE_ID = "b5000000-0000-4000-8000-000000000001"


def response(status: int, payload: object) -> ClientResponse:
    return ClientResponse(
        status, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )


class FakeStore:
    def __init__(self, *, ready: bool = True, owner: str = OWNER) -> None:
        self.is_ready = ready
        self.owner = owner
        self.request_ids: list[str] = []
        self.cases: dict[str, dict[str, Any]] = {
            CASE_ID: {
                "id": CASE_ID,
                "owner_ref": owner,
                "name": "Sydney search",
                "preferences": {},
                "budget_min_aud": 800000,
                "budget_max_aud": 1100000,
                "target_suburbs": [{"state": "NSW", "locality": "MASCOT"}],
                "status": "active",
                "created_at": "2026-09-01T10:00:00Z",
                "updated_at": "2026-09-02T10:00:00Z",
                "version": 1,
            }
        }

    def ready(self) -> bool:
        return self.is_ready

    def list_cases(self, *, page: int, page_size: int, request_id: str) -> ClientResponse:
        self.request_ids.append(request_id)
        values = list(self.cases.values())
        return response(
            200,
            {"items": values, "page": page, "page_size": page_size, "total": len(values)},
        )

    def create_case(self, values: Mapping[str, Any], *, request_id: str) -> ClientResponse:
        self.request_ids.append(request_id)
        case_id = "b5000000-0000-4000-8000-000000000099"
        item = {
            "id": case_id,
            "owner_ref": self.owner,
            **values,
            "created_at": "2026-09-03T10:00:00Z",
            "updated_at": "2026-09-03T10:00:00Z",
            "version": 1,
        }
        self.cases[case_id] = item
        return response(201, item)

    def get_case(self, case_id: str, *, request_id: str) -> ClientResponse:
        self.request_ids.append(request_id)
        item = self.cases.get(case_id)
        if item is None:
            return response(
                404,
                {
                    "type": "about:blank",
                    "title": "Resource Not Found",
                    "status": 404,
                    "detail": "buyer case does not exist",
                    "code": "resource_not_found",
                },
            )
        return response(200, item)

    def update_case(
        self, case_id: str, values: Mapping[str, Any], *, request_id: str
    ) -> ClientResponse:
        self.request_ids.append(request_id)
        item = self.cases.get(case_id)
        if item is None:
            return self.get_case(case_id, request_id=request_id)
        if values.get("version") != item["version"]:
            return response(
                409,
                {
                    "status": 409,
                    "code": "version_conflict",
                    "detail": "Refresh the resource before saving again",
                },
            )
        changes = {key: value for key, value in values.items() if key != "version"}
        item.update(changes)
        item["version"] += 1
        item["updated_at"] = "2026-09-03T11:00:00Z"
        return response(200, item)

    def delete_case(self, case_id: str, *, request_id: str) -> ClientResponse:
        self.request_ids.append(request_id)
        if self.cases.pop(case_id, None) is None:
            return response(404, {"status": 404, "code": "resource_not_found"})
        return response(200, {"deleted": case_id})


class UnavailableStore(FakeStore):
    def list_cases(self, *, page: int, page_size: int, request_id: str) -> ClientResponse:
        raise DatabaseUnavailableError("private transport detail")


class EnvelopeStore(FakeStore):
    def __init__(self, envelope: object) -> None:
        super().__init__()
        self.envelope = envelope

    def list_cases(self, *, page: int, page_size: int, request_id: str) -> ClientResponse:
        return response(200, self.envelope)


class DeleteConfirmationStore(FakeStore):
    def __init__(self, confirmation: object) -> None:
        super().__init__()
        self.confirmation = confirmation

    def delete_case(self, case_id: str, *, request_id: str) -> ClientResponse:
        return response(200, self.confirmation)


def backend_client(store: FakeStore | None = None) -> FlaskClient:
    settings = BackendSettings("http://buyer-db:5502", "server-secret")
    app = create_app(settings, store=store or FakeStore())
    app.config.update(TESTING=True)
    return app.test_client()


def test_application_factory_registers_injected_client_and_routes() -> None:
    store = FakeStore()
    settings = BackendSettings("http://buyer-db:5502", "secret", max_request_bytes=2048)
    app = create_app(settings, store=store)
    assert app.extensions["propertyscope_buyer_store_client"] is store
    assert app.config["MAX_CONTENT_LENGTH"] == 2048
    assert any(rule.rule == API for rule in app.url_map.iter_rules())


def test_health_readiness_depends_on_database_api() -> None:
    assert backend_client().get("/health/live").status_code == 200
    unavailable = backend_client(FakeStore(ready=False)).get("/health/ready")
    assert unavailable.status_code == 503
    assert unavailable.get_json()["checks"]["database_api"]["status"] == "unhealthy"


def test_create_list_read_update_delete_roundtrip_and_owner_is_private() -> None:
    store = FakeStore()
    client = backend_client(store)
    created_response = client.post(
        API,
        json={
            "name": "New case",
            "budget_min_aud": 700000,
            "budget_max_aud": 900000,
            "target_suburbs": [{"state": "NSW", "locality": "MASCOT"}],
            "preferences": {
                "dwelling_types": [" apartment ", "Apartment"],
                "priorities": ["transport"],
                "accessibility": {"step_free": True},
            },
        },
    )
    created = created_response.get_json()
    assert created_response.status_code == 201
    assert created["status"] == "active"
    assert created["preferences"] == {
        "dwelling_types": ["apartment"],
        "priorities": ["transport"],
        "accessibility": {"step_free": True},
    }
    assert "owner_ref" not in created

    listed = client.get(API).get_json()
    assert listed["total"] == 2
    assert all("owner_ref" not in item for item in listed["items"])
    assert client.get(f"{API}/{created['id']}").status_code == 200

    updated = client.put(
        f"{API}/{created['id']}", json={"version": 1, "status": "paused"}
    ).get_json()
    assert updated["status"] == "paused"
    assert updated["version"] == 2
    assert client.delete(f"{API}/{created['id']}").status_code == 200
    assert client.get(f"{API}/{created['id']}").status_code == 404


def test_browser_cannot_select_owner() -> None:
    response_value = backend_client().post(
        API, json={"name": "Unsafe", "owner_ref": "browser-selected"}
    )
    assert response_value.status_code == 422
    assert response_value.content_type == "application/problem+json"
    assert "server controlled" in response_value.get_json()["detail"]
    assert "owner_ref" not in response_value.get_data(as_text=True)


def test_invalid_input_budget_and_target_suburbs_return_problem_details() -> None:
    client = backend_client()
    invalid_name = client.post(API, json={"name": ""})
    invalid_budget = client.post(
        API, json={"name": "Case", "budget_min_aud": 900000, "budget_max_aud": 800000}
    )
    invalid_suburb = client.post(
        API,
        json={"name": "Case", "target_suburbs": [{"state": "NSW", "suburb": "MASCOT"}]},
    )
    for value in (invalid_name, invalid_budget, invalid_suburb):
        assert value.status_code == 422
        assert value.content_type == "application/problem+json"
        assert value.get_json()["code"] == "validation_failed"


def test_unknown_case_and_stale_version_preserve_safe_upstream_outcomes() -> None:
    client = backend_client()
    unknown = client.get(f"{API}/b5000000-0000-4000-8000-000000000404")
    conflict = client.put(f"{API}/{CASE_ID}", json={"version": 9, "status": "closed"})
    assert unknown.status_code == 404
    assert unknown.get_json()["code"] == "resource_not_found"
    assert conflict.status_code == 409
    assert conflict.content_type == "application/problem+json"
    assert conflict.get_json()["code"] == "version_conflict"


def test_request_id_is_echoed_and_forwarded_to_database() -> None:
    store = FakeStore()
    response_value = backend_client(store).get(API, headers={"X-Request-ID": "browser-request-5"})
    assert response_value.headers["X-Request-ID"] == "browser-request-5"
    assert store.request_ids == ["browser-request-5"]


def test_database_unavailable_is_generic_problem_detail() -> None:
    value = backend_client(UnavailableStore()).get(API)
    assert value.status_code == 503
    assert value.content_type == "application/problem+json"
    assert value.get_json()["code"] == "database_unavailable"
    assert "private transport detail" not in value.get_data(as_text=True)


def test_owner_scope_mismatch_is_rejected_without_leaking_identity() -> None:
    value = backend_client(FakeStore(owner="another-owner")).get(API)
    assert value.status_code == 502
    assert value.get_json()["code"] == "database_protocol_error"
    assert "another-owner" not in value.get_data(as_text=True)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("id", "not-a-uuid"),
        ("name", 42),
        ("preferences", []),
        ("preferences", None),
        ("budget_min_aud", True),
        ("budget_max_aud", -1),
        ("target_suburbs", [{"state": "VIC", "locality": "RICHMOND"}]),
        ("status", "draft"),
        ("created_at", None),
        ("updated_at", 42),
        ("version", 0),
    ],
)
def test_malformed_dependency_case_fields_return_safe_502(field: str, bad_value: object) -> None:
    store = FakeStore()
    store.cases[CASE_ID][field] = bad_value
    value = backend_client(store).get(f"{API}/{CASE_ID}")
    assert value.status_code == 502
    problem = value.get_json()
    assert problem["code"] == "database_protocol_error"
    assert problem["detail"] == ("The buyer case service received an invalid dependency response")
    assert "upstream" not in problem
    assert "owner_ref" not in problem


def test_incomplete_dependency_case_returns_safe_502() -> None:
    store = FakeStore()
    del store.cases[CASE_ID]["name"]
    value = backend_client(store).get(f"{API}/{CASE_ID}")
    assert value.status_code == 502
    assert value.content_type == "application/problem+json"


@pytest.mark.parametrize(
    "envelope",
    [
        [],
        {"items": "not-a-list", "page": 1, "page_size": 50, "total": 0},
        {"items": [], "page": 0, "page_size": 50, "total": 0},
        {"items": [], "page": 1, "page_size": True, "total": 0},
        {"items": [], "page": 1, "page_size": 101, "total": 0},
        {"items": [], "page": 1, "page_size": 50, "total": -1},
        {"items": [{}], "page": 1, "page_size": 50, "total": 0},
    ],
)
def test_malformed_list_envelopes_return_safe_502(envelope: object) -> None:
    value = backend_client(EnvelopeStore(envelope)).get(API)
    assert value.status_code == 502
    assert value.get_json()["code"] == "database_protocol_error"
    assert "not-a-list" not in value.get_data(as_text=True)


@pytest.mark.parametrize(
    "confirmation",
    [
        {},
        {"deleted": "b5000000-0000-4000-8000-000000000099"},
        {"deleted": CASE_ID, "extra": True},
        [CASE_ID],
    ],
)
def test_invalid_delete_confirmation_returns_safe_502(confirmation: object) -> None:
    value = backend_client(DeleteConfirmationStore(confirmation)).delete(f"{API}/{CASE_ID}")
    assert value.status_code == 502
    assert value.get_json()["code"] == "database_protocol_error"
