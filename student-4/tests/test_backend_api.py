"""Tests for the due-diligence backend HTTP API using injected fakes."""

from __future__ import annotations

from typing import Any

import httpx

from propertyscope_due_diligence.app import create_app

_API = "/api/due-diligence/v1"


class FakeStore:
    def __init__(self, *, ready: bool = True) -> None:
        self._ready = ready
        self._reviews: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def ready(self) -> bool:
        return self._ready

    def request(
        self, method: str, path: str, *, params: Any = None, json: Any = None
    ) -> httpx.Response:
        if path.endswith("/site-reviews"):
            if method == "GET":
                return httpx.Response(200, json={"items": list(self._reviews.values())})
            if not isinstance(json, dict) or not json.get("title"):
                return httpx.Response(422, json={"code": "invalid_site_review"})
            self._seq += 1
            review_id = f"r{self._seq}"
            row = {
                "id": review_id,
                "property_ref": json.get("property_ref", ""),
                "address_display": json.get("address_display", ""),
                "title": json["title"],
                "status": json.get("status", "draft"),
            }
            self._reviews[review_id] = row
            return httpx.Response(201, json=row)
        if path.endswith("/constraints"):
            return httpx.Response(200, json={"items": [{"id": "c", "evidence_state": "confirmed"}]})
        if path.endswith("/buildings"):
            return httpx.Response(200, json={"items": [{"id": "b", "evidence_state": "confirmed"}]})
        review_id = path.rstrip("/").split("/")[-1]
        row = self._reviews.get(review_id)
        if method == "GET":
            if row is None:
                return httpx.Response(404, json={"code": "site_review_not_found"})
            return httpx.Response(200, json=row)
        if method == "PUT":
            if row is None:
                return httpx.Response(404, json={"code": "site_review_not_found"})
            row = {**row, **(json or {})}
            self._reviews[review_id] = row
            return httpx.Response(200, json=row)
        if method == "DELETE":
            if self._reviews.pop(review_id, None) is None:
                return httpx.Response(404, json={"code": "site_review_not_found"})
            return httpx.Response(200, json={"deleted": review_id})
        return httpx.Response(404, json={})


class FakeFeature1:
    def __init__(self, state: str = "valid") -> None:
        self.state = state

    def validate(self, property_ref: str) -> str:
        return self.state


def _client(store: FakeStore | None = None, feature1: FakeFeature1 | None = None):
    app = create_app(store=store or FakeStore(), feature1=feature1 or FakeFeature1())
    return app.test_client()


def test_health_live_and_ready():
    client = _client()
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").status_code == 200


def test_ready_reports_unhealthy_database_api():
    client = _client(store=FakeStore(ready=False))
    assert client.get("/health/ready").status_code == 503


def test_list_reviews():
    assert _client().get(f"{_API}/site-reviews").status_code == 200


def test_create_with_valid_property():
    client = _client(feature1=FakeFeature1("valid"))
    response = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "a0", "address_display": "x", "title": "t"},
    )
    assert response.status_code == 201


def test_create_with_unknown_property_is_rejected():
    client = _client(feature1=FakeFeature1("not_found"))
    response = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "zzz", "address_display": "x", "title": "t"},
    )
    assert response.status_code == 422


def test_create_still_works_when_feature1_unavailable():
    client = _client(feature1=FakeFeature1("unavailable"))
    response = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "zzz", "address_display": "x", "title": "t"},
    )
    assert response.status_code == 201


def test_create_body_not_object_relays_store_validation():
    response = _client().post(f"{_API}/site-reviews", json="not-a-dict")
    assert response.status_code == 422


def test_get_put_delete_roundtrip():
    store = FakeStore()
    client = create_app(store=store, feature1=FakeFeature1()).test_client()
    review_id = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "a0", "address_display": "x", "title": "t"},
    ).get_json()["id"]
    assert client.get(f"{_API}/site-reviews/{review_id}").status_code == 200
    assert (
        client.put(f"{_API}/site-reviews/{review_id}", json={"status": "completed"}).get_json()[
            "status"
        ]
        == "completed"
    )
    assert client.delete(f"{_API}/site-reviews/{review_id}").status_code == 200
    assert client.get(f"{_API}/site-reviews/{review_id}").status_code == 404


def test_evidence_aggregates_constraints_and_buildings():
    store = FakeStore()
    client = create_app(store=store, feature1=FakeFeature1()).test_client()
    review_id = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "a0", "address_display": "x", "title": "t"},
    ).get_json()["id"]
    body = client.get(f"{_API}/site-reviews/{review_id}/evidence").get_json()
    assert body["site_review"]["id"] == review_id
    assert body["constraints"] and body["buildings"]


def test_evidence_missing_review_relays_not_found():
    assert _client().get(f"{_API}/site-reviews/nope/evidence").status_code == 404


def test_validate_endpoint_reports_state():
    client = _client(feature1=FakeFeature1("valid"))
    assert client.get(f"{_API}/properties/a0/validate").get_json()["state"] == "valid"


def test_unknown_route_returns_problem():
    response = _client().get(f"{_API}/missing")
    assert response.status_code == 404
    assert response.mimetype == "application/problem+json"
