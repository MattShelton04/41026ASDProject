"""Structured failures at the AI tool and public HTTP boundary.

Every failure must be ``application/problem+json`` that names the right party: a malformed
tool input is the caller's 422, a broken dependency payload is a 503, and an unexpected
defect is a 500 that does not echo exception text. Werkzeug's HTML error page never escapes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient
from propertyscope_data_platform.http_support import register_error_handlers

TOOLS = "/api/data-platform/v1/tools"
RUN_ID = "60000000-0000-0000-0000-000000000041"
PROPERTY_REF = "a0000000-0000-0000-0000-000000000002"
Handler = Callable[[httpx.Request], httpx.Response]


def _client(database: Handler, requests: list[httpx.Request] | None = None) -> FlaskClient:
    def recording(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        return database(request)

    app = create_app(
        store_client=DataStoreClient(
            "http://database",
            "secret",
            client=httpx.Client(transport=httpx.MockTransport(recording)),
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    return app.test_client()


def _empty_page(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"items": [], "count": 0})


def _html_failure() -> httpx.Response:
    return httpx.Response(
        500, content=b"<html>private upstream trace</html>", headers={"Content-Type": "text/html"}
    )


@pytest.mark.parametrize(
    ("tool", "body", "maximum"),
    [
        ("sources.list.v1", {"limit": None}, 50),
        ("sources.list.v1", {"limit": [1]}, 50),
        ("sources.list.v1", {"limit": "abc"}, 50),
        ("releases.list.v1", {"limit": {}}, 50),
        ("releases.list.v1", {"limit": True}, 50),
        ("runs.list.v1", {"limit": None}, 25),
        ("runs.list.v1", {"limit": 0}, 25),
        ("properties.search.v1", {"query": "11 Example Street", "limit": [1, 2]}, 25),
        ("properties.search.v1", {"query": "11 Example Street", "limit": -3}, 25),
    ],
)
def test_malformed_tool_limit_is_a_caller_problem_and_never_reaches_the_database(
    tool: str, body: dict[str, Any], maximum: int
) -> None:
    requests: list[httpx.Request] = []

    response = _client(_empty_page, requests).post(
        f"{TOOLS}/{tool}", json=body, headers={"X-Request-ID": "tool-limit-test"}
    )

    assert response.status_code == 422
    assert response.content_type == "application/problem+json"
    problem = response.get_json()
    assert problem["code"] == "invalid_request"
    assert problem["detail"] == f"limit must be an integer from 1 to {maximum}"
    assert problem["request_id"] == "tool-limit-test"
    assert requests == []


def test_property_search_tool_caps_limit_at_its_catalogue_maximum() -> None:
    requests: list[httpx.Request] = []

    response = _client(_empty_page, requests).post(
        f"{TOOLS}/properties.search.v1", json={"query": "11 Example Street", "limit": 100}
    )

    assert response.status_code == 200
    assert requests[0].url.params["limit"] == "25"
    assert requests[0].url.params["q"] == "11 Example Street"


def test_property_search_tool_defaults_to_ten_results() -> None:
    requests: list[httpx.Request] = []

    _client(_empty_page, requests).post(
        f"{TOOLS}/properties.search.v1", json={"query": "11 Example Street"}
    )

    assert requests[0].url.params["limit"] == "10"


@pytest.mark.parametrize("tool", ["runs.inspect.v1", "runs.explain.v1"])
def test_unreadable_secondary_dependency_page_is_a_503_not_a_caller_error(tool: str) -> None:
    def database(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tasks"):
            return _html_failure()
        if request.url.path.endswith("/quality-results"):
            return httpx.Response(200, json={"items": []})
        return httpx.Response(200, json={"run": {"id": RUN_ID, "status": "failed"}})

    response = _client(database).post(f"{TOOLS}/{tool}", json={"run_id": RUN_ID})

    assert response.status_code == 503
    assert response.content_type == "application/problem+json"
    assert response.get_json()["code"] == "dependency_unavailable"
    text = response.get_data(as_text=True)
    assert "private upstream trace" not in text
    assert "Expecting value" not in text


def test_coverage_tool_reports_a_failed_property_lookup_instead_of_partial_evidence() -> None:
    def database(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/properties/search"):
            return httpx.Response(
                200, json={"items": [{"property_ref": PROPERTY_REF, "postcode": "2000"}]}
            )
        return httpx.Response(
            503,
            json={"code": "read_budget_exceeded", "status": 503},
            headers={"Content-Type": "application/problem+json"},
        )

    response = _client(database).post(f"{TOOLS}/coverage.inspect.v1", json={"locality": "SYDNEY"})

    assert response.status_code == 503
    assert response.get_json()["code"] == "read_budget_exceeded"


def test_coverage_tool_merges_evidence_per_dataset() -> None:
    row = {"dataset_id": "gnaf-nsw", "target_feature": "feature-1", "coverage_status": "accepted"}

    def database(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/properties/search"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"property_ref": PROPERTY_REF, "postcode": "2000"},
                        {"property_ref": RUN_ID, "postcode": "2000"},
                    ]
                },
            )
        return httpx.Response(200, json={"items": [row], "count": 1})

    response = _client(database).post(
        f"{TOOLS}/coverage.inspect.v1", json={"locality": "SYDNEY", "postcode": "2000"}
    )

    assert response.status_code == 200
    assert response.get_json() == {"items": [row]}


def test_unexpected_dependency_shape_is_a_problem_document_without_internal_text() -> None:
    def database(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "snapshot shape"})

    response = _client(database).get(f"/api/data-platform/v1/properties/{PROPERTY_REF}")

    assert response.status_code == 500
    assert response.content_type == "application/problem+json"
    problem = response.get_json()
    assert problem["code"] == "internal_error"
    assert problem["detail"] == "The service could not complete the request"
    assert "KeyError" not in response.get_data(as_text=True)
    assert "<html" not in response.get_data(as_text=True).lower()


def _raising_client(error: Exception) -> FlaskClient:
    app = Flask(__name__)

    def fail() -> str:
        raise error

    app.add_url_rule("/fail", view_func=fail)
    register_error_handlers(app)
    return app.test_client()


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (BadRequest(), 400, "bad_request"),
        (UnsupportedMediaType(), 415, "unsupported_media_type"),
        (RuntimeError("secret SQL text"), 500, "internal_error"),
        (TypeError("int() argument must be a string"), 500, "internal_error"),
    ],
)
def test_every_unhandled_failure_is_problem_json(error: Exception, status: int, code: str) -> None:
    response = _raising_client(error).get("/fail", headers={"X-Request-ID": "unhandled-test"})

    assert response.status_code == status
    assert response.content_type == "application/problem+json"
    body = response.get_json()
    assert (body["status"], body["code"], body["request_id"]) == (status, code, "unhandled-test")
    assert "secret SQL text" not in response.get_data(as_text=True)
    assert "int() argument" not in response.get_data(as_text=True)
