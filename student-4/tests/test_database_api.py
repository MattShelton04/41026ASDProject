"""Tests for the due-diligence database service HTTP API (no PostgreSQL required)."""

from __future__ import annotations

from typing import Any

import pytest

from propertyscope_due_diligence_store.app import create_app
from propertyscope_due_diligence_store.configuration import StoreSettings

TOKEN = {"X-PropertyScope-Internal-Token": "tok"}


class FakeStore:
    def __init__(self, *, ready: bool = True) -> None:
        self._ready = ready
        self._reviews: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def ready(self) -> bool:
        return self._ready

    def list_site_reviews(self, *, limit: int = 50) -> list[dict[str, Any]]:
        return list(self._reviews.values())[:limit]

    def get_site_review(self, review_id: str) -> dict[str, Any] | None:
        return self._reviews.get(review_id)

    def create_site_review(self, payload: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        review_id = f"d4000000-0000-0000-0000-{self._seq:012d}"
        row = {"id": review_id, "version": 1, **payload}
        self._reviews[review_id] = row
        return row

    def update_site_review(self, review_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        row = self._reviews.get(review_id)
        if row is None:
            return None
        row = {**row, **changes, "version": row["version"] + 1}
        self._reviews[review_id] = row
        return row

    def delete_site_review(self, review_id: str) -> bool:
        return self._reviews.pop(review_id, None) is not None

    def list_constraint_observations(
        self, property_ref: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return [{"id": "c", "property_ref": property_ref, "evidence_state": "confirmed"}]

    def list_building_observations(
        self, property_ref: str, *, limit: int = 100
    ) -> list[dict[str, Any]]:
        return [{"id": "b", "property_ref": property_ref, "evidence_state": "confirmed"}]


def _app(store: FakeStore | None = None):
    settings = StoreSettings(
        database_url="postgresql://x", internal_token="tok", auto_migrate=False
    )
    return create_app(settings, store=store or FakeStore())


@pytest.fixture
def client():
    return _app().test_client()


def test_health_live_and_ready(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_ready_reports_unhealthy_store():
    client = _app(FakeStore(ready=False)).test_client()
    assert client.get("/health/ready").status_code == 503


def test_internal_routes_require_token(client):
    assert client.get("/internal/due-diligence/v1/site-reviews").status_code == 401


def test_crud_roundtrip(client):
    created = client.post(
        "/internal/due-diligence/v1/site-reviews",
        headers=TOKEN,
        json={"property_ref": "a0", "address_display": "11 Example St", "title": "Review"},
    )
    assert created.status_code == 201
    review_id = created.get_json()["id"]
    assert client.get("/internal/due-diligence/v1/site-reviews", headers=TOKEN).get_json()["items"]
    assert (
        client.get(
            f"/internal/due-diligence/v1/site-reviews/{review_id}", headers=TOKEN
        ).status_code
        == 200
    )
    updated = client.put(
        f"/internal/due-diligence/v1/site-reviews/{review_id}",
        headers=TOKEN,
        json={"status": "completed", "checklist": [{"item": "x", "done": True}]},
    )
    assert updated.get_json()["status"] == "completed"
    assert (
        client.delete(
            f"/internal/due-diligence/v1/site-reviews/{review_id}", headers=TOKEN
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/internal/due-diligence/v1/site-reviews/{review_id}", headers=TOKEN
        ).status_code
        == 404
    )


def test_create_rejects_invalid_bodies(client):
    assert (
        client.post(
            "/internal/due-diligence/v1/site-reviews", headers=TOKEN, json={"title": "x"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/internal/due-diligence/v1/site-reviews",
            headers=TOKEN,
            json={"property_ref": "a", "address_display": "b", "title": "t", "status": "bogus"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/internal/due-diligence/v1/site-reviews", headers=TOKEN, json="not-an-object"
        ).status_code
        == 422
    )


def test_update_and_delete_missing_return_404(client):
    assert (
        client.put(
            "/internal/due-diligence/v1/site-reviews/nope", headers=TOKEN, json={"title": "z"}
        ).status_code
        == 404
    )
    assert (
        client.delete("/internal/due-diligence/v1/site-reviews/nope", headers=TOKEN).status_code
        == 404
    )


def test_update_rejects_invalid_disposition(client):
    created = client.post(
        "/internal/due-diligence/v1/site-reviews",
        headers=TOKEN,
        json={"property_ref": "a0", "address_display": "x", "title": "T"},
    )
    review_id = created.get_json()["id"]
    assert (
        client.put(
            f"/internal/due-diligence/v1/site-reviews/{review_id}",
            headers=TOKEN,
            json={"disposition": "bogus"},
        ).status_code
        == 422
    )


def test_evidence_lists(client):
    assert client.get(
        "/internal/due-diligence/v1/properties/a0/constraints", headers=TOKEN
    ).get_json()["items"]
    assert client.get(
        "/internal/due-diligence/v1/properties/a0/buildings", headers=TOKEN
    ).get_json()["items"]


def test_unknown_route_returns_problem(client):
    response = client.get("/internal/due-diligence/v1/missing", headers=TOKEN)
    assert response.status_code == 404
    assert response.mimetype == "application/problem+json"
