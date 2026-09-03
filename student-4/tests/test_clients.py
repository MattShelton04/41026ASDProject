"""Tests for the backend HTTP clients using httpx.MockTransport (no network)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from propertyscope_due_diligence.clients import (
    AiModeClient,
    DependencyUnavailableError,
    DueDiligenceStoreClient,
    Feature1Client,
)


def _mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_store_client_request_sends_internal_token_and_params():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["token"] = request.headers.get("X-PropertyScope-Internal-Token", "")
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"items": []})

    store = DueDiligenceStoreClient("http://db:5402", "tok", client=_mock_client(handler))
    response = store.request("GET", "/internal/due-diligence/v1/site-reviews", params={"limit": 5})
    assert response.status_code == 200
    assert seen["token"] == "tok"
    assert "limit=5" in seen["url"]


def test_store_client_ready_true_and_false():
    ready = DueDiligenceStoreClient(
        "http://db", "t", client=_mock_client(lambda request: httpx.Response(200))
    )
    assert ready.ready() is True
    unready = DueDiligenceStoreClient(
        "http://db", "t", client=_mock_client(lambda request: httpx.Response(500))
    )
    assert unready.ready() is False


def test_store_client_transport_error_raises_and_ready_false():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    store = DueDiligenceStoreClient("http://db", "t", client=_mock_client(boom))
    with pytest.raises(DependencyUnavailableError):
        store.request("GET", "/internal/due-diligence/v1/site-reviews")
    assert store.ready() is False


def test_feature1_validate_maps_all_states():
    valid = Feature1Client("http://f1", client=_mock_client(lambda r: httpx.Response(200, json={})))
    assert valid.validate("a0") == "valid"
    missing = Feature1Client("http://f1", client=_mock_client(lambda r: httpx.Response(404)))
    assert missing.validate("zzz") == "not_found"
    errored = Feature1Client("http://f1", client=_mock_client(lambda r: httpx.Response(500)))
    assert errored.validate("a0") == "unavailable"

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    down = Feature1Client("http://f1", client=_mock_client(boom))
    assert down.validate("a0") == "unavailable"


def test_feature1_search_projects_and_bounds_results():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "q=11+Example" in str(request.url) or "q=11%20Example" in str(request.url)
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "property_ref": "a0",
                        "address_display": "11 Example Street, Sydney NSW 2000",
                        "resolution_status": "verified",
                        "locality": "SYDNEY",
                        "postcode": "2000",
                    },
                    {"address_display": "missing ref"},
                    "not-a-dict",
                ]
            },
        )

    client = Feature1Client("http://f1", client=_mock_client(handler))
    result = client.search("11 Example Street", limit=5)
    assert result["available"] is True
    assert len(result["items"]) == 1
    assert result["items"][0]["property_ref"] == "a0"
    assert result["items"][0]["resolution_status"] == "verified"


def test_feature1_search_degrades_when_unavailable_or_rejected():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    down = Feature1Client("http://f1", client=_mock_client(boom))
    assert down.search("anything") == {"available": False, "items": []}

    rejected = Feature1Client("http://f1", client=_mock_client(lambda r: httpx.Response(422)))
    assert rejected.search("anything") == {"available": True, "items": []}


def test_feature1_coordinates_reads_the_property_record():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).endswith("/properties/a0")
        return httpx.Response(200, json={"property": {"longitude": 151.0, "latitude": -33.9}})

    client = Feature1Client("http://f1", client=_mock_client(handler))
    assert client.coordinates("a0") == (151.0, -33.9)


def test_feature1_coordinates_none_when_missing_or_unavailable():
    missing = Feature1Client("http://f1", client=_mock_client(lambda r: httpx.Response(404)))
    assert missing.coordinates("a0") is None

    no_coords = Feature1Client(
        "http://f1", client=_mock_client(lambda r: httpx.Response(200, json={"property": {}}))
    )
    assert no_coords.coordinates("a0") is None

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    down = Feature1Client("http://f1", client=_mock_client(boom))
    assert down.coordinates("a0") is None


def test_ai_mode_client_create_get_cancel():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        return httpx.Response(202, json={"id": "run-1"})

    ai = AiModeClient("http://ai:5005", client=_mock_client(handler))
    assert ai.create_run({"feature_key": "student-4-due-diligence"}).status_code == 202
    assert seen["url"].endswith("/api/v1/agent-runs")
    assert ai.get("/api/v1/agent-runs/run-1").status_code == 202
    assert ai.cancel("run-1").status_code == 202


def test_ai_mode_client_transport_error_raises():
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    ai = AiModeClient("http://ai:5005", client=_mock_client(boom))
    with pytest.raises(DependencyUnavailableError):
        ai.create_run({})
