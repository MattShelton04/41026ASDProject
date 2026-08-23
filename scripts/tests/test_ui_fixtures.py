"""Tests for the deterministic same-origin UI fixture host."""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.client import HTTPConnection
from urllib.request import Request, urlopen

import pytest
from scripts.ui_fixture_server import LOOPBACK_HOST, SCENARIO_COOKIE, UIFixtureServer
from scripts.ui_fixtures import SCENARIOS, fixture_response


@pytest.fixture
def fixture_origin() -> Iterator[str]:
    server = UIFixtureServer(0, "populated")
    thread = threading.Thread(target=server.serve_forever)
    thread.start()
    try:
        yield f"http://{LOOPBACK_HOST}:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _json(url: str, *, cookie: str | None = None) -> tuple[dict[str, object], object]:
    headers = {"Cookie": cookie} if cookie else {}
    with urlopen(Request(url, headers=headers), timeout=2) as response:
        return json.load(response), response.headers


def test_same_origin_host_serves_shared_feature_and_structured_unknown_api(
    fixture_origin: str,
) -> None:
    with urlopen(f"{fixture_origin}/", timeout=2) as response:
        assert b"PropertyScope NSW" in response.read()
    with urlopen(
        f"{fixture_origin}/features/data-platform/",
        timeout=2,
    ) as response:
        assert b"Data overview" in response.read()

    connection = HTTPConnection(LOOPBACK_HOST, int(fixture_origin.rsplit(":", 1)[1]))
    connection.request("GET", "/api/data-platform/v1/not-registered")
    response = connection.getresponse()
    problem = json.loads(response.read())
    assert response.status == 404
    assert response.getheader("Content-Type") == "application/problem+json; charset=utf-8"
    assert problem["code"] == "fixture_route_not_found"


def test_query_scenario_sets_session_cookie_used_by_api(fixture_origin: str) -> None:
    request = Request(f"{fixture_origin}/?scenario=empty")
    with urlopen(request, timeout=2) as response:
        cookie = response.headers["Set-Cookie"]
    assert cookie.startswith(f"{SCENARIO_COOKIE}=empty")

    body, _headers = _json(
        f"{fixture_origin}/api/data-platform/v1/properties/search?q=fixture",
        cookie=cookie,
    )

    assert body["items"] == []
    assert body["count"] == 0


def test_fixture_payload_is_stable_and_uses_contract_envelopes() -> None:
    first = fixture_response("GET", "/api/data-platform/v1/jobs", "limit=100", "populated")
    second = fixture_response("GET", "/api/data-platform/v1/jobs", "limit=100", "populated")

    assert first == second
    assert set(first.body) == {"items", "count", "limit", "offset", "next_offset"}
    assert {
        "id",
        "source_definition_id",
        "name",
        "profile_key",
        "dataset_id",
        "target_feature",
        "max_rows",
        "status",
        "version",
    } <= set(first.body["items"][0])


def test_required_scenarios_have_distinct_deterministic_behaviour() -> None:
    assert SCENARIOS == (
        "populated",
        "empty",
        "slow",
        "error",
        "partial",
        "long-content",
        "large",
        "validation-error",
    )
    route = "/api/data-platform/v1/properties/search"
    assert fixture_response("GET", route, "", "empty").body["items"] == []
    assert fixture_response("GET", route, "", "slow").delay_seconds > 0
    assert fixture_response("GET", route, "", "error").status == 503
    assert fixture_response("GET", route, "", "large").body["count"] == 80
    assert (
        "<script>"
        in fixture_response("GET", route, "", "long-content").body["items"][0]["address_display"]
    )
    validation = fixture_response(
        "POST",
        "/api/data-platform/v1/jobs",
        "",
        "validation-error",
    )
    assert validation.status == 422
    assert validation.content_type == "application/problem+json"


def test_partial_scenario_preserves_primary_content_and_fails_optional_calls() -> None:
    detail = fixture_response(
        "GET",
        "/api/data-platform/v1/properties/ps-fixture-0001",
        "",
        "partial",
    )
    map_context = fixture_response(
        "GET",
        "/api/data-platform/v1/properties/ps-fixture-0001/map-context",
        "",
        "partial",
    )
    overview = fixture_response("GET", "/api/data-platform/v1/overview", "", "partial")
    sources = fixture_response("GET", "/api/data-platform/v1/sources", "", "partial")

    assert detail.status == 200
    assert "property" in detail.body
    assert map_context.status == 503
    assert overview.status == 503
    assert sources.status == 200
    assert sources.body["items"]


def test_host_header_and_traversal_are_rejected(fixture_origin: str) -> None:
    port = int(fixture_origin.rsplit(":", 1)[1])
    connection = HTTPConnection(LOOPBACK_HOST, port)
    connection.request("GET", "/", headers={"Host": "example.test"})
    response = connection.getresponse()
    assert response.status == 403
    response.read()
    connection.close()

    connection = HTTPConnection(LOOPBACK_HOST, port)
    connection.request("GET", "/features/data-platform/%2e%2e/%2e%2e/README.md")
    response = connection.getresponse()
    assert response.status == 404
    response.read()
    connection.close()
