"""HTTP API: authentication, correlation, Problem Details and the workflow routes."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from flask import Flask
from flask.testing import FlaskClient

from multi_agent_server.app import create_app
from multi_agent_server.service import WorkflowService
from multi_agent_server.settings import MultiAgentSettings
from shared_contracts.multi_agent import (
    MULTI_AGENT_API_PREFIX,
    WORKFLOW_RUN_ID_HEADER,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunPage,
    WorkflowTemplateDescriptor,
    WorkflowTemplateList,
)
from shared_testkit import assert_problem_detail

API = MULTI_AGENT_API_PREFIX
RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"
TOKEN = "test-multi-agent-token-0123456789abcdef"
START = {
    "template_id": "example-readiness-review",
    "input": {"record_id": RECORD_ID},
    "requested_by": "feature-backend",
}


def start(client: FlaskClient) -> dict[str, Any]:
    response = client.post(f"{API}/runs", json=START, headers={"X-Request-ID": "req-123"})
    assert response.status_code == 202
    return response.get_json()


def test_liveness_is_public_and_everything_else_needs_the_token(app: Flask) -> None:
    anonymous = app.test_client()

    for path in ("/health", "/health/live"):
        response = anonymous.get(path)
        assert response.status_code == 200
        assert response.get_json()["service"] == "multi-agent-server"
    for path in ("/health/ready", f"{API}/templates", f"{API}/runs"):
        response = anonymous.get(path)
        assert response.status_code == 401
        assert response.content_type == "application/problem+json"
        assert_problem_detail(response.get_json(), status=401, code="unauthorized")
    wrong = anonymous.get(f"{API}/templates", headers={"Authorization": "Bearer wrong-token"})
    assert wrong.status_code == 401


def test_readiness_reports_store_templates_tools_and_provider(client: FlaskClient) -> None:
    response = client.get("/health/ready")

    body = response.get_json()
    assert response.status_code == 200
    assert set(body["checks"]) == {"state_store", "templates", "tool_gateway", "provider"}
    assert body["checks"]["templates"]["detail"] == "1 template(s) registered"
    assert body["checks"]["tool_gateway"]["detail"].startswith("fake:")


def test_templates_are_listed_with_input_schema_and_tools(client: FlaskClient) -> None:
    listing = WorkflowTemplateList.model_validate(client.get(f"{API}/templates").get_json())
    assert listing.count == 1
    descriptor = listing.items[0]
    assert descriptor.input_schema["required"] == ["record_id"]
    assert [tool.available for tool in descriptor.tools] == [True, True]

    one = client.get(f"{API}/templates/example-readiness-review")
    assert WorkflowTemplateDescriptor.model_validate(one.get_json()).template.version == "v1"
    missing = client.get(f"{API}/templates/nope")
    assert_problem_detail(missing.get_json(), status=404, code="template_not_found")


def test_start_returns_202_with_location_and_correlation_headers(client: FlaskClient) -> None:
    response = client.post(f"{API}/runs", json=START, headers={"X-Request-ID": "req-123"})

    run = WorkflowRun.model_validate(response.get_json())
    assert response.status_code == 202
    assert response.headers["Location"] == f"{API}/runs/{run.id}"
    assert response.headers[WORKFLOW_RUN_ID_HEADER] == str(run.id)
    assert response.headers["X-Request-ID"] == "req-123"
    assert response.headers["Cache-Control"] == "no-store"
    assert run.request_id == "req-123"
    assert run.requested_by == "feature-backend"


def test_full_workflow_over_http(client: FlaskClient) -> None:
    run = start(client)
    run_id = run["id"]

    current = client.get(f"{API}/runs/{run_id}")
    assert current.get_json()["state"] == "awaiting_human"
    assert current.headers[WORKFLOW_RUN_ID_HEADER] == run_id

    corrected = client.post(
        f"{API}/runs/{run_id}/decision",
        json={"decision": "correct", "note": "Recheck quality", "actor": "analyst"},
    )
    assert corrected.status_code == 200
    assert corrected.get_json()["round"] == 2

    approved = client.post(
        f"{API}/runs/{run_id}/decision", json={"decision": "approve", "actor": "analyst"}
    )
    assert approved.get_json()["state"] == "approved"

    conflict = client.post(
        f"{API}/runs/{run_id}/decision", json={"decision": "approve", "actor": "analyst"}
    )
    assert_problem_detail(conflict.get_json(), status=409, code="invalid_state_transition")

    history = WorkflowRunHistory.model_validate(
        client.get(f"{API}/runs/{run_id}/history").get_json()
    )
    assert history.history[-1].to_state.value == "approved"
    assert history.audit[-1].actor == "analyst"

    page = WorkflowRunPage.model_validate(
        client.get(f"{API}/runs?template_id=example-readiness-review&limit=5").get_json()
    )
    assert page.items[0].decision.value == "approve"


def test_cancel_route(client: FlaskClient) -> None:
    run_id = start(client)["id"]

    cancelled = client.post(f"{API}/runs/{run_id}/cancel", json={"actor": "operator"})
    assert cancelled.get_json()["state"] == "cancelled"
    again = client.post(f"{API}/runs/{run_id}/cancel")
    assert_problem_detail(again.get_json(), status=409, code="invalid_state_transition")
    bad_actor = client.post(f"{API}/runs/{uuid4()}/cancel", json={"actor": 5})
    assert_problem_detail(bad_actor.get_json(), status=400, code="invalid_request")


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"data": "not json", "content_type": "text/plain"}, 400, "invalid_request"),
        ({"json": [1, 2]}, 400, "invalid_request"),
        ({"json": {"template_id": "Bad Id"}}, 422, "invalid_request_body"),
        ({"json": {**START, "unexpected": True}}, 422, "invalid_request_body"),
        ({"json": {**START, "input": {"record_id": "nope"}}}, 422, "invalid_workflow_input"),
        ({"json": {**START, "template_id": "unknown"}}, 404, "template_not_found"),
    ],
)
def test_start_validation_errors_are_problem_details(
    client: FlaskClient, kwargs: dict[str, Any], status: int, code: str
) -> None:
    response = client.post(f"{API}/runs", **kwargs)
    assert response.status_code == status
    assert_problem_detail(response.get_json(), status=status, code=code)
    assert response.get_json()["request_id"]


def test_invalid_input_lists_field_issues(client: FlaskClient) -> None:
    response = client.post(f"{API}/runs", json={**START, "input": {"record_id": "nope"}})
    assert response.get_json()["errors"][0]["field"] == "record_id"


@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"decision": "reject", "actor": "a"}, 422, "invalid_request_body"),
        (
            {"decision": "partial", "note": "n", "actor": "a", "accepted_step_ids": ["ghost"]},
            422,
            "invalid_decision",
        ),
        ({"decision": "maybe", "actor": "a"}, 422, "invalid_request_body"),
    ],
)
def test_decision_validation(
    client: FlaskClient, body: dict[str, Any], status: int, code: str
) -> None:
    run_id = start(client)["id"]
    response = client.post(f"{API}/runs/{run_id}/decision", json=body)
    assert_problem_detail(response.get_json(), status=status, code=code)


def test_unknown_runs_and_malformed_ids_are_404(client: FlaskClient) -> None:
    for path in (
        f"{API}/runs/{uuid4()}",
        f"{API}/runs/not-a-uuid",
        f"{API}/runs/{uuid4()}/history",
    ):
        assert_problem_detail(client.get(path).get_json(), status=404, code="run_not_found")


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "limit=x", "state=unknown"])
def test_list_query_validation(client: FlaskClient, query: str) -> None:
    response = client.get(f"{API}/runs?{query}")
    assert_problem_detail(response.get_json(), status=400, code="invalid_request")


def test_correlation_and_transport_errors(client: FlaskClient) -> None:
    generated = client.get("/health")
    assert UUID(generated.headers["X-Request-ID"])
    unsafe = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    assert unsafe.headers["X-Request-ID"] != "bad id with spaces"
    trace = client.get("/health", headers={"traceparent": "garbage"})
    assert_problem_detail(trace.get_json(), status=400, code="traceparent_invalid")
    too_large = client.post(f"{API}/runs", data="x" * 70_000, content_type="application/json")
    assert_problem_detail(too_large.get_json(), status=413, code="request_too_large")
    not_allowed = client.delete(f"{API}/templates")
    assert not_allowed.status_code == 405
    assert not_allowed.content_type == "application/problem+json"


def test_unexpected_errors_are_contained(app: Flask) -> None:
    def explode() -> str:
        raise RuntimeError("boom")

    app.add_url_rule("/boom", "boom", explode)
    crashed = app.test_client().get("/boom", headers={"Authorization": f"Bearer {TOKEN}"})
    assert_problem_detail(crashed.get_json(), status=500, code="internal_error")


def test_factory_requires_a_token(service: WorkflowService) -> None:
    with pytest.raises(ValueError, match="MULTI_AGENT_SERVICE_TOKEN"):
        create_app(MultiAgentSettings(), service=service)


def test_factory_composes_from_settings_and_recovers_interrupted_runs(tmp_path: Any) -> None:
    from pathlib import Path

    fixtures = Path(__file__).parent / "fixtures"
    settings = MultiAgentSettings(
        token=TOKEN,
        state_directory=tmp_path / "state",
        template_paths=(fixtures / "workflow.yaml",),
        tool_fixture_path=fixtures / "tools.json",
        provider="deterministic",
        repository_root=tmp_path,
    )
    application = create_app(settings)
    client = application.test_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    response = client.post(f"{API}/runs", json=START, headers=headers)
    assert response.status_code == 202
    run_id = response.get_json()["id"]
    service = application.extensions["multi_agent_service"]
    settled = service.wait(UUID(run_id), timeout=10)
    assert settled.state.value == "awaiting_human"
    service.close()
