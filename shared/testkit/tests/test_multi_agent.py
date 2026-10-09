"""The in-memory Multi-Agent Server fake honours the published API contract."""

from __future__ import annotations

import json
import urllib.request
from typing import Any
from uuid import uuid4

import httpx
import pytest

from shared_contracts.multi_agent import (
    MULTI_AGENT_API_PREFIX,
    WORKFLOW_RUN_ID_HEADER,
    HumanDecisionKind,
    WorkflowRun,
    WorkflowRunHistory,
    WorkflowRunPage,
    WorkflowTemplate,
    WorkflowTemplateList,
)
from shared_testkit import FAKE_MULTI_AGENT_TOKEN, FakeMultiAgentServer, assert_problem_detail

API = MULTI_AGENT_API_PREFIX
RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"
TEMPLATE = WorkflowTemplate.model_validate(
    {
        "id": "example-review",
        "version": "v1",
        "feature_id": "example-feature",
        "title": "Example review",
        "objective": "Check a record before it is used.",
        "planner_guidance": "Read the record, then its quality results.",
        "inputs": [
            {"name": "record_id", "title": "Record", "format": "uuid"},
            {"name": "mode", "title": "Mode", "enum": ["quick", "full"], "required": False},
            {"name": "count", "title": "Count", "type": "integer", "required": False},
        ],
        "allowed_tools": ["example.record.v1", "example.quality.v1"],
        "steps": [
            {
                "id": "record",
                "title": "Read record",
                "purpose": "Fetch the record",
                "tool": "example.record.v1",
                "arguments": {"record_id": "{{input.record_id}}", "mode": "{{input.mode}}"},
            },
            {
                "id": "quality",
                "title": "Read quality",
                "purpose": "Fetch quality",
                "tool": "example.quality.v1",
                "arguments": {"record_id": "{{input.record_id}}"},
            },
        ],
        "reviewer_checks": [
            {
                "id": "record-found",
                "description": "The record exists",
                "severity": "critical",
                "recommendation": "Reject the request",
                "rule": {"kind": "step_succeeded", "step": "record"},
            },
            {
                "id": "quality-clean",
                "description": "No quality checks failed",
                "severity": "high",
                "recommendation": "Fix the failures",
                "rule": {"kind": "all_steps_succeeded"},
            },
        ],
    }
)
START = {"template_id": "example-review", "input": {"record_id": RECORD_ID}}


@pytest.fixture
def fake() -> FakeMultiAgentServer:
    return FakeMultiAgentServer([TEMPLATE], tool_results={"example.record.v1": {"items": 10}})


@pytest.fixture
def client(fake: FakeMultiAgentServer) -> httpx.Client:
    return httpx.Client(
        transport=fake.transport(),
        base_url="http://multi-agent",
        headers={"Authorization": f"Bearer {FAKE_MULTI_AGENT_TOKEN}"},
    )


def test_run_settles_for_a_human_decision(client: httpx.Client) -> None:
    response = client.post(f"{API}/runs", json=START, headers={"X-Request-ID": "req-1"})

    run = WorkflowRun.model_validate(response.json())
    assert response.status_code == 202
    assert response.headers["Location"] == f"{API}/runs/{run.id}"
    assert response.headers[WORKFLOW_RUN_ID_HEADER] == str(run.id)
    assert response.headers["X-Request-ID"] == "req-1"
    assert run.state.value == "awaiting_human"
    assert run.plan is not None and run.worker_output is not None and run.review is not None
    assert run.plan.steps[0].arguments == {"record_id": RECORD_ID}
    assert run.worker_output.evidence[0].excerpt == {"items": 10}
    assert run.review.recommendation is HumanDecisionKind.APPROVE
    assert {finding.outcome.value for finding in run.review.findings} == {"pass"}
    assert run.available_actions == ("approve", "correct", "partial", "reject", "cancel")


def test_correction_round_then_terminal_decision(client: httpx.Client) -> None:
    run_id = client.post(f"{API}/runs", json=START).json()["id"]

    corrected = client.post(
        f"{API}/runs/{run_id}/decision",
        json={"decision": "correct", "note": "Recheck", "actor": "analyst"},
    ).json()
    assert (corrected["state"], corrected["round"]) == ("awaiting_human", 2)
    assert corrected["superseded"][0]["round"] == 1
    assert corrected["worker_output"]["correction_note"] == "Recheck"

    final = client.post(
        f"{API}/runs/{run_id}/decision",
        json={"decision": "correct", "note": "Still wrong", "actor": "analyst"},
    )
    assert final.json()["state"] == "corrected"
    assert final.json()["available_actions"] == []

    history = WorkflowRunHistory.model_validate(client.get(f"{API}/runs/{run_id}/history").json())
    assert [entry.to_state.value for entry in history.history] == [
        "planning",
        "working",
        "reviewing",
        "awaiting_human",
        "working",
        "reviewing",
        "awaiting_human",
        "corrected",
    ]
    assert history.audit[-1].event.value == "decision.recorded"

    conflict = client.post(
        f"{API}/runs/{run_id}/decision", json={"decision": "approve", "actor": "analyst"}
    )
    assert_problem_detail(conflict.json(), status=409, code="invalid_state_transition")


@pytest.mark.parametrize(
    ("decision", "state"),
    [
        ({"decision": "approve", "actor": "a"}, "approved"),
        ({"decision": "reject", "note": "No", "actor": "a"}, "rejected"),
        (
            {"decision": "partial", "note": "Some", "actor": "a", "accepted_step_ids": ["record"]},
            "partially_accepted",
        ),
    ],
)
def test_terminal_decisions(client: httpx.Client, decision: dict[str, Any], state: str) -> None:
    run_id = client.post(f"{API}/runs", json=START).json()["id"]
    response = client.post(f"{API}/runs/{run_id}/decision", json=decision)
    assert response.json()["state"] == state
    assert response.json()["completed_at"] is not None


def test_listing_filters_and_validation(client: httpx.Client) -> None:
    first = client.post(f"{API}/runs", json=START).json()["id"]
    second = client.post(f"{API}/runs", json=START).json()["id"]
    client.post(f"{API}/runs/{first}/cancel", json={"actor": "operator"})

    page = WorkflowRunPage.model_validate(client.get(f"{API}/runs?limit=5").json())
    assert [str(item.id) for item in page.items] == [second, first]
    cancelled = client.get(f"{API}/runs", params={"state": "cancelled"}).json()
    assert [item["id"] for item in cancelled["items"]] == [first]
    assert client.get(f"{API}/runs", params={"feature_id": "other"}).json()["count"] == 0
    for query in ("limit=0", "limit=x", "state=nope"):
        response = client.get(f"{API}/runs?{query}")
        assert_problem_detail(response.json(), status=400, code="invalid_request")


def test_templates_and_health(fake: FakeMultiAgentServer, client: httpx.Client) -> None:
    listing = WorkflowTemplateList.model_validate(client.get(f"{API}/templates").json())
    assert listing.items[0].input_schema["required"] == ["record_id"]
    assert client.get(f"{API}/templates/example-review").json()["template"]["version"] == "v1"
    missing = client.get(f"{API}/templates/nope")
    assert_problem_detail(missing.json(), status=404, code="template_not_found")
    assert client.get("/health/ready").json()["checks"]["templates"]["status"] == "healthy"

    anonymous = httpx.Client(transport=fake.transport(), base_url="http://multi-agent")
    assert anonymous.get("/health").status_code == 200
    denied = anonymous.get(f"{API}/runs")
    assert denied.headers["content-type"] == "application/problem+json"
    assert_problem_detail(denied.json(), status=401, code="unauthorized")


@pytest.mark.parametrize(
    ("kwargs", "status", "code"),
    [
        ({"content": b"x", "headers": {"Content-Type": "text/plain"}}, 400, "invalid_request"),
        (
            {"content": b"{bad", "headers": {"Content-Type": "application/json"}},
            400,
            "invalid_request",
        ),
        ({"json": {"template_id": "Bad Id"}}, 422, "invalid_request_body"),
        ({"json": {**START, "template_id": "unknown"}}, 404, "template_not_found"),
        ({"json": {**START, "input": {"record_id": "nope"}}}, 422, "invalid_workflow_input"),
        ({"json": {**START, "input": {}}}, 422, "invalid_workflow_input"),
        ({"json": {**START, "input": {**START["input"], "x": 1}}}, 422, "invalid_workflow_input"),
        (
            {"json": {**START, "input": {**START["input"], "mode": "slow"}}},
            422,
            "invalid_workflow_input",
        ),
        (
            {"json": {**START, "input": {**START["input"], "count": True}}},
            422,
            "invalid_workflow_input",
        ),
    ],
)
def test_start_errors(client: httpx.Client, kwargs: dict[str, Any], status: int, code: str) -> None:
    response = client.post(f"{API}/runs", **kwargs)
    assert response.status_code == status
    assert_problem_detail(response.json(), status=status, code=code)


def test_route_errors(client: httpx.Client) -> None:
    run_id = client.post(f"{API}/runs", json=START).json()["id"]
    for path in (
        f"{API}/runs/{uuid4()}",
        f"{API}/runs/not-a-uuid",
        f"{API}/runs/{uuid4()}/history",
    ):
        assert_problem_detail(client.get(path).json(), status=404, code="run_not_found")
    for path in ("/elsewhere", f"{API}/unknown", f"{API}/runs/{run_id}/other"):
        assert_problem_detail(client.get(path).json(), status=404, code="not_found")
    not_allowed = client.delete(f"{API}/templates")
    assert_problem_detail(not_allowed.json(), status=405, code="method_not_allowed")
    ghost = client.post(
        f"{API}/runs/{run_id}/decision",
        json={"decision": "partial", "note": "n", "actor": "a", "accepted_step_ids": ["ghost"]},
    )
    assert_problem_detail(ghost.json(), status=422, code="invalid_decision")
    no_note = client.post(
        f"{API}/runs/{run_id}/decision", json={"decision": "reject", "actor": "a"}
    )
    assert_problem_detail(no_note.json(), status=422, code="invalid_request_body")
    bad_actor = client.post(f"{API}/runs/{run_id}/cancel", json={"actor": 5})
    assert_problem_detail(bad_actor.json(), status=400, code="invalid_request")
    assert client.post(f"{API}/runs/{run_id}/cancel").json()["state"] == "cancelled"
    again = client.post(f"{API}/runs/{run_id}/cancel")
    assert_problem_detail(again.json(), status=409, code="invalid_state_transition")


def test_manual_settlement_failure_and_failed_checks() -> None:
    fake = FakeMultiAgentServer([TEMPLATE], auto_settle=False)
    client = httpx.Client(
        transport=fake.transport(),
        base_url="http://multi-agent",
        headers={"Authorization": f"Bearer {FAKE_MULTI_AGENT_TOKEN}"},
    )
    run_id = client.post(f"{API}/runs", json=START).json()["id"]
    assert client.get(f"{API}/runs/{run_id}").json()["state"] == "planning"

    settled = fake.settle(
        run_id, recommendation=HumanDecisionKind.CORRECT, failed_checks=["quality-clean"]
    )
    assert settled.review is not None
    failed = [finding for finding in settled.review.findings if finding.outcome.value == "fail"]
    assert [(item.check_id, item.severity.value) for item in failed] == [("quality-clean", "high")]
    with pytest.raises(ValueError, match="cannot settle"):
        fake.settle(run_id)

    corrected = client.post(
        f"{API}/runs/{run_id}/decision",
        json={"decision": "correct", "note": "again", "actor": "a"},
    ).json()
    assert corrected["state"] == "working"
    assert fake.settle(run_id).round == 2

    other = client.post(f"{API}/runs", json=START).json()["id"]
    failed_run = fake.fail(other, code="tools_unavailable", message="MCP is down")
    assert failed_run.error is not None and failed_run.error.code == "tools_unavailable"
    with pytest.raises(ValueError, match="already finished"):
        fake.fail(other)
    assert len(fake.runs()) == 2
    assert fake.run(other).state.value == "failed"
    assert ("POST", f"{API}/runs", START) in fake.requests


def test_wsgi_and_loopback_server(fake: FakeMultiAgentServer) -> None:
    wsgi = httpx.Client(
        transport=httpx.WSGITransport(app=fake),
        base_url="http://multi-agent",
        headers={"Authorization": f"Bearer {FAKE_MULTI_AGENT_TOKEN}"},
    )
    assert wsgi.post(f"{API}/runs", json=START).status_code == 202
    assert wsgi.get(f"{API}/runs").json()["count"] == 1

    with fake.serve() as base_url:
        request = urllib.request.Request(  # noqa: S310 - loopback fake server URL
            f"{base_url}{API}/runs",
            data=json.dumps(START).encode(),
            headers={
                "Authorization": f"Bearer {FAKE_MULTI_AGENT_TOKEN}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - loopback fake server URL
            assert response.status == 202
            assert json.loads(response.read())["state"] == "awaiting_human"
    assert len(fake.runs()) == 2
