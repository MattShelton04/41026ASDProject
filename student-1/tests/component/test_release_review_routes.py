"""Feature 1 release-review proxy routes against the shared FakeMultiAgentServer.

The fake is loaded with Feature 1's real workflow manifest. Tests talk to the Multi-Agent Server
only over HTTP (``fake.transport()`` or ``fake.serve()``); they never import the server package.
"""

from __future__ import annotations

import socket
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from flask import Flask
from flask.testing import FlaskClient

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import (
    AiModeClient,
    DataStoreClient,
    MultiAgentClient,
    MultiAgentUnavailableError,
)
from propertyscope_data_platform.release_review_routes import (
    RELEASE_REVIEW_FEATURE_ID,
    RELEASE_REVIEW_TEMPLATE_ID,
)
from shared_contracts import PROBLEM_DETAIL_MEDIA_TYPE
from shared_contracts.multi_agent import (
    WORKFLOW_RUN_ID_HEADER,
    HumanDecisionKind,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunPage,
    WorkflowTemplate,
    WorkflowTemplateDescriptor,
)
from shared_testkit import FAKE_MULTI_AGENT_TOKEN, FakeMultiAgentServer

MANIFEST = Path(__file__).resolve().parents[2] / "config" / "multi-agent" / "workflow.yaml"
BASE = "/api/data-platform/v1/release-reviews"
RELEASE_ID = "60000000-0000-0000-0000-000000000042"
REQUEST_ID = "release-review-test-request-0001"


def _feature_template() -> WorkflowTemplate:
    return WorkflowTemplate.model_validate(yaml.safe_load(MANIFEST.read_text("utf-8")))


def _foreign_template(*, feature_id: str, template_id: str) -> WorkflowTemplate:
    document = yaml.safe_load(MANIFEST.read_text("utf-8"))
    document.update(id=template_id, feature_id=feature_id)
    return WorkflowTemplate.model_validate(document)


def _app(multi_agent: MultiAgentClient) -> Flask:
    offline = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    return create_app(
        store_client=DataStoreClient("http://database", "secret", client=offline),
        ai_mode_client=AiModeClient("http://ai", client=offline),
        multi_agent_client=multi_agent,
    )


def _client_for(fake: FakeMultiAgentServer, *, token: str = FAKE_MULTI_AGENT_TOKEN) -> FlaskClient:
    multi_agent = MultiAgentClient(
        "http://multi-agent",
        service_token=token,
        client=httpx.Client(transport=fake.transport()),
    )
    return _app(multi_agent).test_client()


@pytest.fixture
def fake() -> FakeMultiAgentServer:
    return FakeMultiAgentServer(
        [
            _feature_template(),
            _foreign_template(feature_id="student-2-market", template_id="f2-other-review"),
            _foreign_template(
                feature_id=RELEASE_REVIEW_FEATURE_ID, template_id="f1-some-other-template"
            ),
        ],
        recommendation=HumanDecisionKind.CORRECT,
        failed_checks=["no-quality-failures"],
        tool_results={"data.release_inspect.v1": {"release": {"id": RELEASE_ID}}},
    )


@pytest.fixture
def client(fake: FakeMultiAgentServer) -> FlaskClient:
    return _client_for(fake)


def _start(client: FlaskClient, **overrides: Any) -> Any:
    body: dict[str, Any] = {"input": {"release_id": RELEASE_ID}, "requested_by": "operator"}
    body.update(overrides)
    return client.post(BASE, json=body, headers={"X-Request-ID": REQUEST_ID})


def _foreign_run(fake: FakeMultiAgentServer, template_id: str) -> str:
    upstream = fake.handle(
        "POST",
        "/api/v1/multi-agent/runs",
        headers={
            "Authorization": f"Bearer {FAKE_MULTI_AGENT_TOKEN}",
            "Content-Type": "application/json",
        },
        body=(
            b'{"template_id": "' + template_id.encode() + b'", '
            b'"input": {"release_id": "' + RELEASE_ID.encode() + b'"}}'
        ),
    )
    assert upstream.status == 202
    return str(upstream.json()["id"])


def _assert_problem(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.get_json()
    assert response.mimetype == PROBLEM_DETAIL_MEDIA_TYPE
    assert response.headers["Cache-Control"] == "no-store"
    body = response.get_json()
    assert body["code"] == code
    return dict(body)


def test_template_route_returns_the_feature_workflow_descriptor(client: FlaskClient) -> None:
    response = client.get(f"{BASE}/template")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    descriptor = WorkflowTemplateDescriptor.model_validate(response.get_json())
    assert descriptor.template.id == RELEASE_REVIEW_TEMPLATE_ID
    assert descriptor.template.inputs[0].name == "release_id"


def test_start_pins_template_rewrites_location_and_passes_request_id(
    client: FlaskClient, fake: FakeMultiAgentServer
) -> None:
    response = _start(client, template_id="f2-other-review")

    assert response.status_code == 202
    assert response.headers["Cache-Control"] == "no-store"
    run = WorkflowRun.model_validate(response.get_json())
    assert run.template_id == RELEASE_REVIEW_TEMPLATE_ID
    assert run.feature_id == RELEASE_REVIEW_FEATURE_ID
    assert run.requested_by == "operator"
    assert response.headers["Location"] == f"{BASE}/{run.id}"
    assert response.headers[WORKFLOW_RUN_ID_HEADER] == str(run.id)
    assert response.headers["X-Request-ID"] == REQUEST_ID
    method, path, payload = fake.requests[-1]
    assert (method, path) == ("POST", "/api/v1/multi-agent/runs")
    assert payload == {
        "template_id": RELEASE_REVIEW_TEMPLATE_ID,
        "input": {"release_id": RELEASE_ID},
        "requested_by": "operator",
    }
    assert fake.run(run.id).request_id == REQUEST_ID


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        ([1, 2], "request body must be a JSON object"),
        ({"input": "not-an-object"}, "input must be a JSON object"),
        ({"release_id": RELEASE_ID}, "unexpected field(s): release_id"),
    ],
)
def test_start_rejects_malformed_bodies_before_calling_the_server(
    client: FlaskClient, fake: FakeMultiAgentServer, body: Any, detail: str
) -> None:
    response = client.post(BASE, json=body)

    problem = _assert_problem(response, 422, "invalid_release_review_request")
    assert problem["detail"] == detail
    assert fake.requests == []


def test_start_relays_server_input_validation_unchanged(client: FlaskClient) -> None:
    response = _start(client, input={"release_id": "not-a-uuid"})

    problem = _assert_problem(response, 422, "invalid_workflow_input")
    assert problem["errors"][0]["field"] == "release_id"
    assert problem["type"] == "urn:propertyscope:multi-agent:invalid_workflow_input"
    assert "Location" not in response.headers


def test_get_and_history_return_owned_runs(client: FlaskClient) -> None:
    run_id = _start(client).get_json()["id"]

    detail = client.get(f"{BASE}/{run_id}")
    assert detail.status_code == 200
    assert detail.headers["Cache-Control"] == "no-store"
    assert detail.headers[WORKFLOW_RUN_ID_HEADER] == run_id
    run = WorkflowRun.model_validate(detail.get_json())
    assert run.state.value == "awaiting_human"
    assert run.review is not None and run.review.recommendation is HumanDecisionKind.CORRECT

    history = client.get(f"{BASE}/{run_id}/history")
    assert history.status_code == 200
    assert history.headers["Cache-Control"] == "no-store"
    record = WorkflowRunHistory.model_validate(history.get_json())
    assert str(record.run_id) == run_id
    assert record.history

    # Polling cursors pass through: only newer entries come back.
    last_history = record.history[-1].sequence
    last_audit = record.audit[-1].sequence
    newer = client.get(
        f"{BASE}/{run_id}/history?after_history={last_history - 1}&after_audit={last_audit}"
    )
    assert newer.status_code == 200
    body = newer.get_json()
    assert [entry["sequence"] for entry in body["history"]] == [last_history]
    assert body["audit"] == []

    # The server's cursor validation is relayed unchanged.
    invalid = client.get(f"{BASE}/{run_id}/history?after_audit=-1")
    _assert_problem(invalid, 400, "invalid_request")


def test_list_is_scoped_to_feature_template_and_clamps_limit(
    client: FlaskClient, fake: FakeMultiAgentServer
) -> None:
    owned = _start(client).get_json()["id"]
    _foreign_run(fake, "f2-other-review")
    _foreign_run(fake, "f1-some-other-template")

    response = client.get(f"{BASE}?limit=5000&state=awaiting_human&template_id=f2-other-review")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    page = WorkflowRunPage.model_validate(response.get_json())
    assert [str(item.id) for item in page.items] == [owned]
    method, path, _ = fake.requests[-1]
    assert (method, path) == ("GET", "/api/v1/multi-agent/runs")

    default = client.get(BASE)
    assert default.get_json()["count"] == 1


def test_list_filters_stray_items_the_server_returns() -> None:
    stray = {"id": str(uuid.uuid4()), "feature_id": "other", "template_id": "x"}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["template_id"] == RELEASE_REVIEW_TEMPLATE_ID
        assert request.url.params["feature_id"] == RELEASE_REVIEW_FEATURE_ID
        assert request.url.params["limit"] == "1"
        return httpx.Response(200, json={"items": [stray, "junk"], "count": 2})

    multi_agent = MultiAgentClient(
        "http://multi-agent",
        service_token="token",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    response = _app(multi_agent).test_client().get(f"{BASE}?limit=0")

    assert response.get_json() == {"items": [], "count": 0}


def test_list_rejects_non_integer_limit_and_relays_invalid_state(
    client: FlaskClient,
) -> None:
    _assert_problem(client.get(f"{BASE}?limit=many"), 422, "invalid_release_review_request")
    _assert_problem(client.get(f"{BASE}?state=bogus"), 400, "invalid_request")


def test_approve_records_a_terminal_decision(client: FlaskClient) -> None:
    run_id = _start(client).get_json()["id"]

    response = client.post(
        f"{BASE}/{run_id}/decision",
        json={"decision": "approve", "note": "", "actor": "operator"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    run = WorkflowRun.model_validate(response.get_json())
    assert run.state.value == "approved"
    assert run.available_actions == ()


def test_correct_starts_a_second_round_then_partial_accepts_steps(client: FlaskClient) -> None:
    run_id = _start(client).get_json()["id"]

    corrected = client.post(
        f"{BASE}/{run_id}/decision",
        json={"decision": "correct", "note": "Recheck the quality results", "actor": "operator"},
    )
    assert corrected.status_code == 200
    run = WorkflowRun.model_validate(corrected.get_json())
    assert run.round == 2
    assert run.state.value == "awaiting_human"
    assert [attempt.round for attempt in run.superseded] == [1]

    partial = client.post(
        f"{BASE}/{run_id}/decision",
        json={
            "decision": "partial",
            "note": "Release evidence is fine; queue is not needed",
            "actor": "operator",
            "accepted_step_ids": ["release"],
        },
    )
    assert partial.status_code == 200
    final = WorkflowRun.model_validate(partial.get_json())
    assert final.state.value == "partially_accepted"
    assert final.decisions[-1].accepted_step_ids == ("release",)


def test_reject_and_then_a_second_decision_conflicts(client: FlaskClient) -> None:
    run_id = _start(client).get_json()["id"]
    reject = {"decision": "reject", "note": "Blocking quality failure", "actor": "operator"}

    assert client.post(f"{BASE}/{run_id}/decision", json=reject).get_json()["state"] == "rejected"
    _assert_problem(
        client.post(f"{BASE}/{run_id}/decision", json=reject), 409, "invalid_state_transition"
    )


def test_invalid_decisions_relay_server_problems_unchanged(client: FlaskClient) -> None:
    run_id = _start(client).get_json()["id"]

    invalid_body = client.post(
        f"{BASE}/{run_id}/decision", json={"decision": "maybe", "actor": "operator"}
    )
    problem = _assert_problem(invalid_body, 422, "invalid_request_body")
    assert problem["errors"]

    unknown_step = client.post(
        f"{BASE}/{run_id}/decision",
        json={
            "decision": "partial",
            "note": "x",
            "actor": "operator",
            "accepted_step_ids": ["nope"],
        },
    )
    _assert_problem(unknown_step, 422, "invalid_decision")

    _assert_problem(
        client.post(f"{BASE}/{run_id}/decision", data="[]", content_type="application/json"),
        422,
        "invalid_release_review_request",
    )


def test_cancel_with_and_without_actor(client: FlaskClient) -> None:
    first = _start(client).get_json()["id"]
    second = _start(client).get_json()["id"]

    cancelled = client.post(f"{BASE}/{first}/cancel", json={"actor": "operator"})
    assert cancelled.status_code == 200
    assert cancelled.get_json()["state"] == "cancelled"
    assert cancelled.headers["Cache-Control"] == "no-store"

    bare = client.post(f"{BASE}/{second}/cancel")
    assert bare.get_json()["state"] == "cancelled"

    _assert_problem(client.post(f"{BASE}/{first}/cancel"), 409, "invalid_state_transition")
    _assert_problem(
        client.post(f"{BASE}/{first}/cancel", data="nope", content_type="application/json"),
        422,
        "invalid_release_review_request",
    )


@pytest.mark.parametrize("template_id", ["f2-other-review", "f1-some-other-template"])
@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    [
        ("GET", "", None),
        ("GET", "/history", None),
        ("POST", "/decision", {"decision": "approve", "note": "", "actor": "operator"}),
        ("POST", "/cancel", None),
    ],
)
def test_runs_of_another_feature_or_template_are_not_found(
    client: FlaskClient,
    fake: FakeMultiAgentServer,
    template_id: str,
    method: str,
    suffix: str,
    body: dict[str, Any] | None,
) -> None:
    run_id = _foreign_run(fake, template_id)

    response = client.open(f"{BASE}/{run_id}{suffix}", method=method, json=body)

    _assert_problem(response, 404, "release_review_not_found")
    assert fake.run(run_id).state.value == "awaiting_human"


def test_unknown_run_relays_server_not_found(client: FlaskClient) -> None:
    response = client.get(f"{BASE}/{uuid.uuid4()}")

    problem = _assert_problem(response, 404, "run_not_found")
    assert problem["type"] == "urn:propertyscope:multi-agent:run_not_found"


def test_empty_token_is_unavailable_without_contacting_the_server(
    fake: FakeMultiAgentServer,
) -> None:
    client = _client_for(fake, token="  ")

    for response in (client.get(f"{BASE}/template"), _start(client), client.get(BASE)):
        _assert_problem(response, 503, "multi_agent_unavailable")
    assert fake.requests == []


def test_rejected_service_credential_is_reported_as_unavailable(
    fake: FakeMultiAgentServer,
) -> None:
    response = _client_for(fake, token="wrong-token").get(f"{BASE}/template")

    problem = _assert_problem(response, 503, "multi_agent_unavailable")
    assert "token" not in problem["detail"].lower()


def test_transport_failure_maps_to_multi_agent_unavailable() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    multi_agent = MultiAgentClient(
        "http://multi-agent",
        service_token="token",
        client=httpx.Client(transport=httpx.MockTransport(refuse)),
    )
    client = _app(multi_agent).test_client()

    _assert_problem(client.get(f"{BASE}/{uuid.uuid4()}"), 503, "multi_agent_unavailable")
    _assert_problem(_start(client), 503, "multi_agent_unavailable")


def test_closed_port_maps_to_multi_agent_unavailable() -> None:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    multi_agent = MultiAgentClient(f"http://127.0.0.1:{port}", service_token="token")

    _assert_problem(
        _app(multi_agent).test_client().get(f"{BASE}/template"), 503, "multi_agent_unavailable"
    )


def test_unreadable_upstream_payload_maps_to_multi_agent_unavailable() -> None:
    multi_agent = MultiAgentClient(
        "http://multi-agent",
        service_token="token",
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _: httpx.Response(202, json={"id": "nope"}))
        ),
    )

    _assert_problem(_start(_app(multi_agent).test_client()), 503, "multi_agent_unavailable")


def test_routes_work_against_a_real_socket(fake: FakeMultiAgentServer) -> None:
    with fake.serve() as base_url:
        client = _app(MultiAgentClient(base_url, service_token=fake.token)).test_client()
        started = _start(client)
        assert started.status_code == 202
        run_id = started.get_json()["id"]
        assert client.get(f"{BASE}/{run_id}").get_json()["id"] == run_id
    assert fake.run(run_id).request_id == REQUEST_ID


def test_client_sends_bearer_token_and_only_allowlisted_headers() -> None:
    seen: list[httpx.Request] = []

    def capture(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={})

    multi_agent = MultiAgentClient(
        "http://multi-agent/",
        service_token=" secret ",
        client=httpx.Client(transport=httpx.MockTransport(capture)),
    )
    assert multi_agent.configured
    multi_agent.history(
        uuid.UUID(int=1),
        {"X-Request-ID": REQUEST_ID, "Cookie": "session=1", "Authorization": "Bearer user"},
    )
    multi_agent.history(uuid.UUID(int=1), {}, {"after_history": 3, "after_audit": "12"})

    request = seen[0]
    assert str(request.url) == (
        "http://multi-agent/api/v1/multi-agent/runs/00000000-0000-0000-0000-000000000001/history"
    )
    assert seen[1].url.params == httpx.QueryParams({"after_history": "3", "after_audit": "12"})
    assert request.headers["Authorization"] == "Bearer secret"
    assert request.headers["X-Request-ID"] == REQUEST_ID
    assert "Cookie" not in request.headers


def test_unconfigured_client_raises_a_distinct_error() -> None:
    multi_agent = MultiAgentClient("http://multi-agent")

    assert not multi_agent.configured
    with pytest.raises(MultiAgentUnavailableError, match="not configured"):
        multi_agent.template(RELEASE_REVIEW_TEMPLATE_ID, {})
