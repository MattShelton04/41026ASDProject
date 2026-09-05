"""In-process browser-to-backend-to-database Buyer Case integration test."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

from flask.testing import FlaskClient

from propertyscope_buyer_store.app import create_app as create_database_app
from propertyscope_buyer_store.configuration import StoreSettings
from propertyscope_buyer_store.repository import BuyerStore
from propertyscope_buyer_workspaces.app import create_app as create_backend_app
from propertyscope_buyer_workspaces.clients import BuyerStoreClient, ClientResponse
from propertyscope_buyer_workspaces.configuration import BackendSettings

API = "/api/buyer-workspaces/v1/buyer-cases"
TOKEN = "vertical-slice-token"
OWNER = "release0-demo-owner"


class FlaskTransport:
    """Adapt the real database Flask app to the injected HTTP transport protocol."""

    def __init__(self, client: FlaskClient) -> None:
        self.client = client
        self.request_ids: list[str] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, int] | None,
        json_body: Mapping[str, Any] | None,
        timeout_seconds: float,
    ) -> ClientResponse:
        parts = urlsplit(url)
        path = parts.path
        if params:
            path = f"{path}?{urlencode(params)}"
        if request_id := headers.get("X-Request-ID"):
            self.request_ids.append(request_id)
        response = self.client.open(
            path,
            method=method,
            headers=dict(headers),
            json=None if json_body is None else dict(json_body),
        )
        return ClientResponse(
            status_code=response.status_code,
            body=response.data,
            headers=dict(response.headers),
        )


class PendingPropertyEvidence:
    """Keep this database vertical slice isolated from cross-feature services."""

    def validate_property(self, property_ref: str, *, request_id: str) -> dict[str, str]:
        return {"state": "pending"}

    def collect(self, property_refs: Sequence[str], *, request_id: str) -> dict[str, Any]:
        return {"state": "partial", "sections": {}, "limitations": []}


def test_real_in_process_buyer_case_vertical_slice(tmp_path: Path) -> None:
    database_store = BuyerStore(
        tmp_path / "buyer-workspaces.sqlite3",
        clock=lambda: "2026-09-04T10:00:00Z",
        id_factory=lambda: "f5000000-0000-4000-8000-000000000201",
    )
    database_store.initialize()
    database_settings = StoreSettings(
        database_path=tmp_path / "buyer-workspaces.sqlite3",
        internal_token=TOKEN,
        demo_owner_ref=OWNER,
        auto_migrate=False,
    )
    database_app = create_database_app(database_settings, store=database_store)
    database_app.config.update(TESTING=True)
    transport = FlaskTransport(database_app.test_client())
    database_client = BuyerStoreClient("http://buyer-db", TOKEN, transport=transport)

    backend_settings = BackendSettings("http://buyer-db", TOKEN, OWNER)
    backend_app = create_backend_app(
        backend_settings, store=database_client, evidence=PendingPropertyEvidence()
    )
    backend_app.config.update(TESTING=True)
    browser = backend_app.test_client()
    headers = {"X-Request-ID": "vertical-slice-request"}

    listed = browser.get(API, headers=headers)
    assert listed.status_code == 200
    assert listed.get_json()["total"] == 10

    created_response = browser.post(
        API,
        headers=headers,
        json={
            "name": "Integrated buyer case",
            "budget_min_aud": 700000,
            "budget_max_aud": 950000,
            "target_suburbs": [{"state": "NSW", "locality": "MASCOT"}],
            "preferences": {
                "dwelling_types": ["apartment"],
                "priorities": ["transport"],
            },
        },
    )
    created = created_response.get_json()
    assert created_response.status_code == 201
    assert created["status"] == "active"
    case_id = created["id"]

    read = browser.get(f"{API}/{case_id}", headers=headers)
    assert read.status_code == 200
    assert read.get_json()["preferences"]["dwelling_types"] == ["apartment"]

    updated = browser.put(
        f"{API}/{case_id}",
        headers=headers,
        json={
            "version": created["version"],
            "status": "paused",
            "preferences": {
                "dwelling_types": ["apartment", "terrace"],
                "priorities": ["transport", "planning evidence"],
            },
        },
    )
    assert updated.status_code == 200
    assert updated.get_json()["version"] == 2
    assert updated.get_json()["status"] == "paused"

    property_response = browser.post(
        f"{API}/{case_id}/properties",
        headers=headers,
        json={
            "property_ref": "f1000000-0000-4000-8000-000000000001",
            "property_label": "Inspection candidate (unverified)",
            "journey_stage": "Inspecting",
            "rating": 4,
            "priority": "high",
        },
    )
    property_item = property_response.get_json()
    property_id = property_item["id"]
    assert property_response.status_code == 201
    assert property_item["property_validation_state"] == "pending"
    assert browser.get(f"{API}/{case_id}/properties", headers=headers).get_json()["total"] == 1
    closed_property = browser.put(
        f"{API}/{case_id}/properties/{property_id}",
        headers=headers,
        json={"version": 1, "journey_stage": "Closed", "rating": 5, "priority": "low"},
    ).get_json()
    reopened_property = browser.put(
        f"{API}/{case_id}/properties/{property_id}",
        headers=headers,
        json={"version": closed_property["version"], "journey_stage": "Shortlisted"},
    ).get_json()
    assert reopened_property["journey_stage"] == "Shortlisted"

    note_response = browser.post(
        f"{API}/{case_id}/notes",
        headers=headers,
        json={"case_property_id": property_id, "content": "  Check strata records.  "},
    )
    note = note_response.get_json()
    assert note_response.status_code == 201
    assert note["content"] == "Check strata records."
    updated_note = browser.put(
        f"{API}/{case_id}/notes/{note['id']}",
        headers=headers,
        json={"version": note["version"], "content": "Confirm strata meeting history."},
    ).get_json()
    assert updated_note["version"] == 2
    assert browser.get(f"{API}/{case_id}/notes", headers=headers).get_json()["total"] == 1

    task_response = browser.post(
        f"{API}/{case_id}/tasks",
        headers=headers,
        json={
            "case_property_id": property_id,
            "title": "Book inspection",
            "due_date": "2026-09-10",
        },
    )
    task = task_response.get_json()
    assert task_response.status_code == 201
    completed_task = browser.put(
        f"{API}/{case_id}/tasks/{task['id']}",
        headers=headers,
        json={"version": task["version"], "completed": True},
    ).get_json()
    assert completed_task["completed"] is True
    assert browser.get(f"{API}/{case_id}/tasks", headers=headers).get_json()["total"] == 1
    assert browser.delete(f"{API}/{case_id}/notes/{note['id']}", headers=headers).status_code == 200
    assert browser.delete(f"{API}/{case_id}/tasks/{task['id']}", headers=headers).status_code == 200
    assert (
        browser.delete(f"{API}/{case_id}/properties/{property_id}", headers=headers).status_code
        == 200
    )

    deleted = browser.delete(f"{API}/{case_id}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.get_json() == {"deleted": case_id}
    assert browser.get(f"{API}/{case_id}", headers=headers).status_code == 404

    for response in (listed, created_response, read, updated, deleted):
        assert "owner_ref" not in response.get_data(as_text=True)
        assert response.headers["X-Request-ID"] == "vertical-slice-request"
    assert transport.request_ids
    assert set(transport.request_ids) == {"vertical-slice-request"}
