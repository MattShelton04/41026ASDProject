"""Feature 3 comparison-review proxy routes against the shared HTTP test double."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import httpx
import yaml

from propertyscope_suburb_analytics.app import (
    COMPARISON_REVIEW_COLLECTION,
    COMPARISON_REVIEW_TEMPLATE_ID,
    FEATURE_KEY,
    create_app,
)
from propertyscope_suburb_analytics.clients import MultiAgentClient
from shared_contracts.multi_agent import MULTI_AGENT_API_PREFIX, WorkflowTemplate
from shared_testkit import FAKE_MULTI_AGENT_TOKEN, FakeMultiAgentServer

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "student-3/config/multi-agent/workflow.yaml"
COMPARISON_ID = "comparison-1"


class _Unused:
    base_url = "http://unused"

    def request(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("unrelated dependency was called")


def _template() -> WorkflowTemplate:
    return WorkflowTemplate.model_validate(yaml.safe_load(MANIFEST.read_text("utf-8")))


def _foreign_template() -> WorkflowTemplate:
    document = yaml.safe_load(MANIFEST.read_text("utf-8"))
    document.update(id="f2-foreign-review", feature_id="student-2-market-intelligence")
    return WorkflowTemplate.model_validate(document)


def _app(fake: FakeMultiAgentServer, *, token: str = FAKE_MULTI_AGENT_TOKEN) -> Any:
    reviews = MultiAgentClient(
        "http://multi-agent",
        service_token=token,
        client=httpx.Client(transport=fake.transport()),
    )
    unused = _Unused()
    return create_app(unused, unused, unused, reviews)


def _call(
    app: Any,
    path: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    *,
    request_id: str = "request-f3-review",
) -> tuple[int, dict[str, Any], dict[str, str]]:
    encoded = json.dumps(body).encode() if body is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path.split("?", 1)[0],
        "QUERY_STRING": path.partition("?")[2],
        "CONTENT_LENGTH": str(len(encoded)),
        "CONTENT_TYPE": "application/json",
        "HTTP_X_REQUEST_ID": request_id,
        "wsgi.input": io.BytesIO(encoded),
    }
    status: list[str] = []
    response_headers: list[tuple[str, str]] = []

    def start(value: str, headers: list[tuple[str, str]]) -> None:
        status.append(value)
        response_headers.extend(headers)

    payload = json.loads(b"".join(app(environ, start)))
    return int(status[0].split()[0]), payload, dict(response_headers)


def _fake() -> FakeMultiAgentServer:
    return FakeMultiAgentServer(
        [_template(), _foreign_template()],
        tool_results={
            "suburb.comparison.inspect.v1": {
                "comparison": {"id": COMPARISON_ID, "localities": ["BURWOOD", "NEWTOWN"]}
            },
            "crime.saved-comparison-evidence.v1": {
                "comparison_id": COMPARISON_ID,
                "coverage": "partial",
            },
        },
    )


def test_capability_and_template_are_exposed_without_leaking_the_service_token() -> None:
    app = _app(_fake())

    status, capability, _ = _call(app, f"{COMPARISON_REVIEW_COLLECTION}/capabilities")
    assert status == 200
    assert capability == {"comparison_review": {"enabled": True, "detail": None}}

    status, descriptor, headers = _call(app, f"{COMPARISON_REVIEW_COLLECTION}/template")
    assert status == 200
    assert descriptor["template"]["id"] == COMPARISON_REVIEW_TEMPLATE_ID
    assert headers["Cache-Control"] == "no-store"


def test_start_pins_the_template_and_returns_only_the_feature_location() -> None:
    app = _app(_fake())
    status, run, headers = _call(
        app,
        COMPARISON_REVIEW_COLLECTION,
        "POST",
        {
            "template_id": "f2-foreign-review",
            "input": {"suburb_comparison_id": COMPARISON_ID},
            "requested_by": "Feature 3 analyst",
        },
    )

    assert status == 202
    assert run["template_id"] == COMPARISON_REVIEW_TEMPLATE_ID
    assert run["feature_id"] == FEATURE_KEY
    assert headers["Location"] == f"{COMPARISON_REVIEW_COLLECTION}/{run['id']}"
    assert headers["X-Workflow-Run-ID"] == run["id"]


def test_detail_history_and_list_stay_scoped_to_feature_3() -> None:
    app = _app(_fake())
    _, created, _ = _call(
        app,
        COMPARISON_REVIEW_COLLECTION,
        "POST",
        {"input": {"suburb_comparison_id": COMPARISON_ID}},
    )
    run_id = created["id"]

    status, detail, _ = _call(app, f"{COMPARISON_REVIEW_COLLECTION}/{run_id}")
    assert status == 200
    assert detail["id"] == run_id

    status, history, _ = _call(
        app,
        f"{COMPARISON_REVIEW_COLLECTION}/{run_id}/history?after_history=0&after_audit=0",
    )
    assert status == 200
    assert history["run_id"] == run_id

    status, page, _ = _call(app, f"{COMPARISON_REVIEW_COLLECTION}?limit=500")
    assert status == 200
    assert [item["id"] for item in page["items"]] == [run_id]


def test_proxy_refuses_a_run_owned_by_another_feature() -> None:
    fake = _fake()
    upstream = httpx.Client(transport=fake.transport())
    created = upstream.post(
        f"http://multi-agent{MULTI_AGENT_API_PREFIX}/runs",
        headers={"Authorization": f"Bearer {FAKE_MULTI_AGENT_TOKEN}"},
        json={
            "template_id": "f2-foreign-review",
            "input": {"suburb_comparison_id": COMPARISON_ID},
        },
    )
    assert created.status_code == 202

    status, problem, _ = _call(_app(fake), f"{COMPARISON_REVIEW_COLLECTION}/{created.json()['id']}")
    assert status == 404
    assert problem["code"] == "comparison_review_not_found"


def test_invalid_proxy_fields_are_rejected_before_an_upstream_run_is_created() -> None:
    app = _app(_fake())
    status, problem, _ = _call(
        app,
        COMPARISON_REVIEW_COLLECTION,
        "POST",
        {"input": {"suburb_comparison_id": COMPARISON_ID}, "unexpected": True},
    )
    assert status == 422
    assert problem["code"] == "invalid_request"

    status, problem, _ = _call(app, f"{COMPARISON_REVIEW_COLLECTION}?limit=not-a-number")
    assert status == 422
    assert problem["code"] == "invalid_request"


def test_invalid_human_actor_is_rejected_before_the_decision_is_sent() -> None:
    app = _app(_fake())
    _, created, _ = _call(
        app,
        COMPARISON_REVIEW_COLLECTION,
        "POST",
        {"input": {"suburb_comparison_id": COMPARISON_ID}},
    )
    status, problem, _ = _call(
        app,
        f"{COMPARISON_REVIEW_COLLECTION}/{created['id']}/decision",
        "POST",
        {"decision": "approve", "actor": "<script>"},
    )
    assert status == 422
    assert problem["code"] == "invalid_request"


def test_unconfigured_server_degrades_without_breaking_saved_comparisons() -> None:
    fake = _fake()
    app = _app(fake, token="")

    status, capability, _ = _call(app, f"{COMPARISON_REVIEW_COLLECTION}/capabilities")
    assert status == 200
    assert capability["comparison_review"]["enabled"] is False

    status, problem, _ = _call(app, f"{COMPARISON_REVIEW_COLLECTION}/template")
    assert status == 503
    assert problem["code"] == "multi_agent_unavailable"


def test_multi_agent_client_forwards_only_valid_correlation_and_its_own_token() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"template": {"id": COMPARISON_REVIEW_TEMPLATE_ID}})

    client = MultiAgentClient(
        "http://multi-agent",
        service_token="server-token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    client.template(
        COMPARISON_REVIEW_TEMPLATE_ID,
        {
            "X-Request-ID": "request-123",
            "traceparent": "invalid",
            "Authorization": "Bearer browser-token",
            "Cookie": "private=yes",
        },
    )

    assert seen[0].headers["Authorization"] == "Bearer server-token"
    assert seen[0].headers["X-Request-ID"] == "request-123"
    assert "traceparent" not in seen[0].headers
    assert "cookie" not in seen[0].headers
