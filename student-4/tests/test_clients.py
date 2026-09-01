"""Tests for the backend HTTP clients using httpx.MockTransport (no network)."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from propertyscope_due_diligence.clients import (
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
