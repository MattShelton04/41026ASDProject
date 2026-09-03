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
    def __init__(
        self,
        state: str = "valid",
        *,
        search_result: dict[str, Any] | None = None,
        coordinates: tuple[float, float] | None = (151.0, -33.9),
    ) -> None:
        self.state = state
        self._coordinates = coordinates
        self.search_result = (
            search_result
            if search_result is not None
            else {
                "available": True,
                "items": [
                    {
                        "property_ref": "a0",
                        "address_display": "11 Example Street, Sydney NSW 2000",
                        "resolution_status": "verified",
                    }
                ],
            }
        )

    def validate(self, property_ref: str) -> str:
        return self.state

    def search(self, query: str, limit: int = 8) -> dict[str, Any]:
        return self.search_result

    def coordinates(self, property_ref: str) -> tuple[float, float] | None:
        return self._coordinates


class FakeAiMode:
    def __init__(self, *, run_feature_key: str = "student-4-due-diligence") -> None:
        self._run_feature_key = run_feature_key
        self.created: list[dict[str, Any]] = []

    def create_run(self, payload: dict[str, Any]) -> httpx.Response:
        self.created.append(payload)
        return httpx.Response(202, json={"id": "run-1", "status": "queued"})

    def get(self, path: str, *, params: Any = None) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "run": {
                    "id": "run-1",
                    "status": "succeeded",
                    "feature_key": self._run_feature_key,
                    "tool_allowlist": [
                        "duediligence.review.inspect.v1",
                        "duediligence.evidence.summary.v1",
                    ],
                    "final_result": {"questions": ["Confirm the zoning permits your use."]},
                }
            },
        )

    def cancel(self, run_id: str) -> httpx.Response:
        return httpx.Response(200, json={"id": run_id, "status": "cancelled"})


def _client(
    store: FakeStore | None = None,
    feature1: FakeFeature1 | None = None,
    ai_mode: FakeAiMode | None = None,
):
    app = create_app(
        store=store or FakeStore(),
        feature1=feature1 or FakeFeature1(),
        ai_mode=ai_mode or FakeAiMode(),
    )
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


def test_property_search_returns_matches():
    response = _client().get(f"{_API}/properties/search?q=Example")
    assert response.status_code == 200
    body = response.get_json()
    assert body["available"] is True
    assert body["items"][0]["property_ref"] == "a0"


def test_property_search_rejects_short_query():
    response = _client().get(f"{_API}/properties/search?q=ab")
    assert response.status_code == 422
    assert response.mimetype == "application/problem+json"


def test_property_search_reports_unavailable():
    client = _client(feature1=FakeFeature1(search_result={"available": False, "items": []}))
    body = client.get(f"{_API}/properties/search?q=Example").get_json()
    assert body["available"] is False
    assert body["items"] == []


def test_map_returns_bounded_geojson():
    store = FakeStore()
    client = create_app(
        store=store, feature1=FakeFeature1(coordinates=(151.0, -33.9))
    ).test_client()
    review_id = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "a0", "address_display": "11 Example Street", "title": "t"},
    ).get_json()["id"]
    body = client.get(f"{_API}/site-reviews/{review_id}/map").get_json()
    assert body["available"] is True
    assert body["center"] == [151.0, -33.9]
    assert body["property"]["features"][0]["geometry"]["type"] == "Point"


def test_map_unavailable_when_no_coordinates():
    store = FakeStore()
    client = create_app(store=store, feature1=FakeFeature1(coordinates=None)).test_client()
    review_id = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "a0", "address_display": "x", "title": "t"},
    ).get_json()["id"]
    body = client.get(f"{_API}/site-reviews/{review_id}/map").get_json()
    assert body["available"] is False


def test_map_missing_review_relays_not_found():
    assert _client().get(f"{_API}/site-reviews/nope/map").status_code == 404


def test_assistant_capabilities_lists_tools():
    body = _client().get(f"{_API}/assistant/capabilities").get_json()
    assert body["feature_key"] == "student-4-due-diligence"
    assert "duediligence.review.inspect.v1" in body["tools"]
    assert body["suggested_questions"]


def test_assistant_turn_creates_a_bounded_run():
    store = FakeStore()
    ai = FakeAiMode()
    client = create_app(store=store, feature1=FakeFeature1(), ai_mode=ai).test_client()
    review_id = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "a0", "address_display": "x", "title": "t"},
    ).get_json()["id"]
    response = client.post(f"{_API}/assistant/turns", json={"review_id": review_id})
    assert response.status_code == 202
    assert response.get_json()["id"] == "run-1"
    payload = ai.created[0]
    assert payload["feature_key"] == "student-4-due-diligence"
    assert payload["trusted_identifiers"] == [{"kind": "site_review_id", "value": review_id}]
    assert payload["tool_allowlist"] == [
        "duediligence.review.inspect.v1",
        "duediligence.evidence.summary.v1",
    ]


def test_assistant_turn_requires_review_id():
    assert _client().post(f"{_API}/assistant/turns", json={}).status_code == 422
    assert _client().post(f"{_API}/assistant/turns", json="x").status_code == 422


def test_assistant_turn_relays_missing_review():
    assert _client().post(f"{_API}/assistant/turns", json={"review_id": "nope"}).status_code == 404


def test_assistant_detail_rejects_unowned_run():
    client = _client(ai_mode=FakeAiMode(run_feature_key="student-2-market-intelligence"))
    assert client.get(f"{_API}/assistant/turns/run-1").status_code == 404


def test_assistant_detail_returns_owned_run():
    body = _client().get(f"{_API}/assistant/turns/run-1").get_json()
    assert body["run"]["status"] == "succeeded"


def test_assistant_cancel_owned_run():
    assert _client().post(f"{_API}/assistant/turns/run-1/cancel").status_code == 200


def test_assistant_turn_degrades_when_ai_unavailable():
    class DownAi(FakeAiMode):
        def create_run(self, payload):
            from propertyscope_due_diligence.clients import DependencyUnavailableError

            raise DependencyUnavailableError("down")

    store = FakeStore()
    client = create_app(store=store, feature1=FakeFeature1(), ai_mode=DownAi()).test_client()
    review_id = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "a0", "address_display": "x", "title": "t"},
    ).get_json()["id"]
    assert client.post(f"{_API}/assistant/turns", json={"review_id": review_id}).status_code == 503


def test_tool_review_inspect_returns_review():
    store = FakeStore()
    client = create_app(store=store, feature1=FakeFeature1(), ai_mode=FakeAiMode()).test_client()
    review_id = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "a0", "address_display": "x", "title": "t"},
    ).get_json()["id"]
    body = client.post(
        f"{_API}/tools/duediligence.review.inspect.v1", json={"site_review_id": review_id}
    ).get_json()
    assert body["site_review"]["id"] == review_id


def test_tool_evidence_summary_returns_constraints_and_buildings():
    store = FakeStore()
    client = create_app(store=store, feature1=FakeFeature1(), ai_mode=FakeAiMode()).test_client()
    review_id = client.post(
        f"{_API}/site-reviews",
        json={"property_ref": "a0", "address_display": "x", "title": "t"},
    ).get_json()["id"]
    body = client.post(
        f"{_API}/tools/duediligence.evidence.summary.v1", json={"site_review_id": review_id}
    ).get_json()
    assert body["constraints"] and body["buildings"]


def test_unknown_route_returns_problem():
    response = _client().get(f"{_API}/missing")
    assert response.status_code == 404
    assert response.mimetype == "application/problem+json"
