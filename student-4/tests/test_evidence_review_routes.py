"""Feature 4 evidence-review proxy routes against the shared FakeMultiAgentServer.

The fake is loaded with Feature 4's real workflow manifest, so the template the proxy pins and
the one the tests assert on cannot drift apart. Tests reach the Multi-Agent Server only over HTTP
through ``fake.transport()``; the server package is never imported (a student slice must not).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from flask.testing import FlaskClient

from propertyscope_due_diligence.api import FEATURE_KEY
from propertyscope_due_diligence.app import create_app
from propertyscope_due_diligence.clients import MultiAgentClient, forwarded_headers
from propertyscope_due_diligence.evidence_review_routes import (
    EVIDENCE_REVIEW_DISABLED_DETAIL,
    EVIDENCE_REVIEW_FEATURE_ID,
    EVIDENCE_REVIEW_TEMPLATE_ID,
)
from shared_contracts import REQUEST_ID_HEADER
from shared_contracts.multi_agent import WORKFLOW_RUN_ID_HEADER, WorkflowTemplate
from shared_testkit import FAKE_MULTI_AGENT_TOKEN, FakeMultiAgentServer

MANIFEST = Path(__file__).resolve().parents[1] / "config" / "multi-agent" / "workflow.yaml"
BASE = "/api/due-diligence/v1/evidence-reviews"
REVIEW_ID = "d4000000-0000-0000-0000-000000000001"
PROBLEM_MEDIA_TYPE = "application/problem+json"


def _feature_template() -> WorkflowTemplate:
    return WorkflowTemplate.model_validate(yaml.safe_load(MANIFEST.read_text("utf-8")))


def _foreign_template(*, feature_id: str, template_id: str) -> WorkflowTemplate:
    document = yaml.safe_load(MANIFEST.read_text("utf-8"))
    document.update(id=template_id, feature_id=feature_id)
    return WorkflowTemplate.model_validate(document)


class _Offline:
    """Feature 4's other dependencies, unreachable: these tests are about the proxy alone."""

    def request(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(503, json={"status": 503})

    def ready(self) -> bool:
        return False


def _refuse(_request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("multi-agent server is not listening")


def _app_with(multi_agent: MultiAgentClient) -> FlaskClient:
    offline = _Offline()
    return create_app(
        store=offline, feature1=offline, ai_mode=offline, multi_agent=multi_agent
    ).test_client()


def _client_for(fake: FakeMultiAgentServer, *, token: str = FAKE_MULTI_AGENT_TOKEN) -> FlaskClient:
    return _app_with(
        MultiAgentClient(
            "http://multi-agent",
            service_token=token,
            client=httpx.Client(transport=fake.transport()),
        )
    )


def _stub_client(handler: Any) -> FlaskClient:
    """A configured proxy whose upstream answers with ``handler``."""
    return _app_with(
        MultiAgentClient(
            "http://multi-agent",
            service_token=FAKE_MULTI_AGENT_TOKEN,
            client=httpx.Client(transport=httpx.MockTransport(handler)),
        )
    )


@pytest.fixture
def fake() -> FakeMultiAgentServer:
    return FakeMultiAgentServer(
        [
            _feature_template(),
            # A run owned by another feature, and one owned by Feature 4 under a different
            # template: the proxy must refuse both with 404.
            _foreign_template(
                feature_id="student-2-market-intelligence", template_id="f2-some-other-brief"
            ),
            _foreign_template(
                feature_id=EVIDENCE_REVIEW_FEATURE_ID, template_id="f4-some-other-template"
            ),
        ],
        tool_results={
            "duediligence.review.inspect.v1": {"site_review": {"id": REVIEW_ID}},
        },
    )


@pytest.fixture
def client(fake: FakeMultiAgentServer) -> FlaskClient:
    return _client_for(fake)


def _start(client: FlaskClient) -> str:
    created = client.post(BASE, json={"input": {"site_review_id": REVIEW_ID}})
    assert created.status_code == 202, created.get_json()
    return str(created.get_json()["id"])


def _foreign_run(fake: FakeMultiAgentServer, template_id: str) -> str:
    """Start a run the proxy does not own, straight against the fake server."""
    upstream = fake.handle(
        "POST",
        "/api/v1/multi-agent/runs",
        headers={
            "Authorization": f"Bearer {FAKE_MULTI_AGENT_TOKEN}",
            "Content-Type": "application/json",
        },
        body=json.dumps(
            {"template_id": template_id, "input": {"site_review_id": REVIEW_ID}}
        ).encode(),
    )
    return str(upstream.json()["id"])


def test_manifest_belongs_to_this_feature() -> None:
    template = _feature_template()
    assert template.id == EVIDENCE_REVIEW_TEMPLATE_ID
    assert template.feature_id == EVIDENCE_REVIEW_FEATURE_ID == FEATURE_KEY
    # Every tool the workflow may call is one of Feature 4's own read-only tools.
    assert set(template.allowed_tools) == {
        "duediligence.review.inspect.v1",
        "duediligence.evidence.summary.v1",
    }


def test_template_is_pinned_to_feature_4(client: FlaskClient) -> None:
    response = client.get(f"{BASE}/template")
    assert response.status_code == 200
    template = response.get_json()["template"]
    assert template["id"] == EVIDENCE_REVIEW_TEMPLATE_ID
    assert template["feature_id"] == EVIDENCE_REVIEW_FEATURE_ID


def test_start_returns_202_and_points_location_at_this_feature(client: FlaskClient) -> None:
    created = client.post(
        BASE, json={"input": {"site_review_id": REVIEW_ID}, "requested_by": "Michael White"}
    )
    assert created.status_code == 202
    run_id = created.get_json()["id"]
    # The browser must never be pointed at the host Multi-Agent Server.
    assert created.headers["Location"] == f"{BASE}/{run_id}"
    assert created.headers[WORKFLOW_RUN_ID_HEADER] == str(run_id)
    assert created.headers["Cache-Control"] == "no-store"


def test_a_client_supplied_template_id_is_never_forwarded(client: FlaskClient) -> None:
    created = client.post(
        BASE,
        json={"input": {"site_review_id": REVIEW_ID}, "template_id": "f2-market-case-brief"},
    )
    assert created.status_code == 202
    assert created.get_json()["template_id"] == EVIDENCE_REVIEW_TEMPLATE_ID


@pytest.mark.parametrize(
    "body",
    [
        {"input": {}, "feature_id": "student-2-market-intelligence"},
        {"input": "not-an-object"},
        ["not", "an", "object"],
    ],
)
def test_malformed_start_requests_are_rejected(client: FlaskClient, body: Any) -> None:
    rejected = client.post(BASE, json=body)
    assert rejected.status_code == 422
    assert rejected.get_json()["code"] == "invalid_evidence_review_request"


def test_an_invalid_requester_is_reported_against_its_field(client: FlaskClient) -> None:
    rejected = client.post(
        BASE, json={"input": {"site_review_id": REVIEW_ID}, "requested_by": "<script>"}
    )
    assert rejected.status_code == 422
    assert rejected.get_json()["errors"][0]["field"] == "requested_by"


def test_status_and_history_are_readable(client: FlaskClient) -> None:
    run_id = _start(client)
    detail = client.get(f"{BASE}/{run_id}")
    assert detail.status_code == 200
    assert detail.get_json()["input"] == {"site_review_id": REVIEW_ID}
    history = client.get(f"{BASE}/{run_id}/history?after_history=0&after_audit=0")
    assert history.status_code == 200
    assert "history" in history.get_json()


def test_a_decision_is_relayed_and_its_actor_is_bounded(client: FlaskClient) -> None:
    run_id = _start(client)
    decided = client.post(
        f"{BASE}/{run_id}/decision",
        json={"decision": "approve", "actor": "Michael White", "note": "Questions are grounded."},
    )
    assert decided.status_code == 200, decided.get_json()

    for actor, message in (
        ("  ", "actor must not be empty"),
        (7, "actor must be a string"),
        ("x" * 101, "actor must be at most 100 characters"),
    ):
        rejected = client.post(
            f"{BASE}/{run_id}/decision", json={"decision": "approve", "actor": actor}
        )
        assert rejected.status_code == 422
        assert rejected.content_type == PROBLEM_MEDIA_TYPE
        assert rejected.get_json()["errors"][0] == {
            "field": "actor",
            "message": message,
            "code": "invalid_actor",
        }


@pytest.mark.parametrize("note", ["bad\x07note", "x" * 2001, 42])
def test_an_unsafe_note_is_refused_before_the_audit_trail(client: FlaskClient, note: Any) -> None:
    run_id = _start(client)
    rejected = client.post(
        f"{BASE}/{run_id}/decision",
        json={"decision": "reject", "actor": "Michael", "note": note},
    )
    assert rejected.status_code == 422
    assert rejected.get_json()["errors"][0]["code"] == "invalid_note"


def test_a_decision_without_a_json_object_is_rejected(client: FlaskClient) -> None:
    rejected = client.post(f"{BASE}/{uuid.uuid4()}/decision", data="nope")
    assert rejected.status_code == 422


def test_another_features_run_is_not_found(fake: FakeMultiAgentServer, client: FlaskClient) -> None:
    run_id = _foreign_run(fake, "f2-some-other-brief")
    for method, path, body in (
        ("get", f"{BASE}/{run_id}", None),
        ("get", f"{BASE}/{run_id}/history", None),
        ("post", f"{BASE}/{run_id}/decision", {"decision": "approve", "actor": "Michael"}),
        ("post", f"{BASE}/{run_id}/cancel", {"actor": "Michael"}),
    ):
        refused = getattr(client, method)(path, json=body)
        assert refused.status_code == 404, path
        assert refused.get_json()["code"] == "evidence_review_not_found"


def test_a_run_of_another_template_in_this_feature_is_not_found(
    fake: FakeMultiAgentServer, client: FlaskClient
) -> None:
    run_id = _foreign_run(fake, "f4-some-other-template")
    assert client.get(f"{BASE}/{run_id}").status_code == 404


def test_an_unknown_run_relays_the_servers_problem(client: FlaskClient) -> None:
    missing = client.get(f"{BASE}/{uuid.uuid4()}")
    assert missing.status_code == 404
    assert missing.content_type == PROBLEM_MEDIA_TYPE


def test_the_list_is_scoped_to_this_feature_and_template(
    fake: FakeMultiAgentServer, client: FlaskClient
) -> None:
    _start(client)
    _foreign_run(fake, "f4-some-other-template")
    page = client.get(f"{BASE}?limit=500&state=awaiting_human")
    assert page.status_code == 200
    items = page.get_json()["items"]
    assert items
    assert all(
        item["feature_id"] == EVIDENCE_REVIEW_FEATURE_ID
        and item["template_id"] == EVIDENCE_REVIEW_TEMPLATE_ID
        for item in items
    )


def test_a_non_integer_limit_is_rejected(client: FlaskClient) -> None:
    rejected = client.get(f"{BASE}?limit=many")
    assert rejected.status_code == 422
    assert rejected.get_json()["code"] == "invalid_evidence_review_request"


def test_a_run_can_be_cancelled(client: FlaskClient) -> None:
    run_id = _start(client)
    cancelled = client.post(f"{BASE}/{run_id}/cancel", json={"actor": "Michael"})
    assert cancelled.status_code in {200, 409}
    invalid = client.post(f"{BASE}/{run_id}/cancel", json={"actor": "  "})
    assert invalid.status_code == 422
    malformed = client.post(f"{BASE}/{run_id}/cancel", data="[]", content_type="application/json")
    assert malformed.status_code == 422


def test_without_a_service_token_the_feature_degrades_to_503(
    fake: FakeMultiAgentServer,
) -> None:
    """The required cloud baseline supplies an empty token on purpose."""
    unconfigured = _client_for(fake, token="")
    for path in (f"{BASE}/template", BASE, f"{BASE}/{uuid.uuid4()}"):
        response = unconfigured.get(path)
        assert response.status_code == 503, path
        assert response.get_json()["code"] == "multi_agent_unavailable"
        assert response.content_type == PROBLEM_MEDIA_TYPE
    started = unconfigured.post(BASE, json={"input": {"site_review_id": REVIEW_ID}})
    assert started.status_code == 503


def test_capabilities_answer_200_when_the_server_is_not_configured(
    fake: FakeMultiAgentServer,
) -> None:
    """A deployment with the AI tier off gets a clear answer, not the 503 other routes give."""
    response = _client_for(fake, token="").get(f"{BASE}/capabilities")
    assert response.status_code == 200
    assert response.get_json() == {
        "evidence_review": {"enabled": False, "detail": EVIDENCE_REVIEW_DISABLED_DETAIL}
    }


def test_capabilities_report_enabled_when_the_server_answers(
    fake: FakeMultiAgentServer,
) -> None:
    response = _client_for(fake).get(f"{BASE}/capabilities")
    assert response.get_json() == {"evidence_review": {"enabled": True, "detail": None}}


def test_an_unreachable_server_is_disabled_and_its_routes_answer_503() -> None:
    """A token is not enough: CI issues one to a stack whose Multi-Agent Server never starts."""
    http = _stub_client(_refuse)
    capability = http.get(f"{BASE}/capabilities")
    assert capability.status_code == 200
    assert capability.get_json()["evidence_review"]["enabled"] is False
    assert http.get(f"{BASE}/template").status_code == 503


def test_a_rejected_service_token_is_a_deployment_fault() -> None:
    http = _stub_client(lambda _request: httpx.Response(401, json={"code": "unauthorized"}))
    response = http.get(f"{BASE}/template")
    assert response.status_code == 503
    assert response.get_json()["code"] == "multi_agent_unavailable"


@pytest.mark.parametrize(
    "upstream",
    [
        httpx.Response(200, text="not json"),
        httpx.Response(200, json=["not", "an", "object"]),
        httpx.Response(302, headers={"Location": "http://elsewhere"}),
        httpx.Response(202, json={"id": "not-a-uuid"}),
    ],
)
def test_an_unusable_upstream_answer_becomes_503(upstream: httpx.Response) -> None:
    http = _stub_client(lambda _request: upstream)
    response = http.post(BASE, json={"input": {"site_review_id": REVIEW_ID}})
    assert response.status_code == 503
    assert response.get_json()["code"] == "multi_agent_unavailable"


def test_a_failed_list_relays_the_servers_problem() -> None:
    http = _stub_client(
        lambda _request: httpx.Response(
            400,
            json={"code": "invalid_request", "status": 400},
            headers={"content-type": PROBLEM_MEDIA_TYPE},
        )
    )
    response = http.get(BASE)
    assert response.status_code == 400
    assert response.content_type == PROBLEM_MEDIA_TYPE


def test_only_valid_correlation_headers_are_forwarded_with_the_token() -> None:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"template": {}}, headers={REQUEST_ID_HEADER: "abc"})

    request_id = str(uuid.uuid4())
    response = _stub_client(record).get(
        f"{BASE}/template", headers={REQUEST_ID_HEADER: request_id, "Cookie": "session=secret"}
    )
    assert response.status_code == 200
    assert response.headers[REQUEST_ID_HEADER] == "abc"
    sent = seen[0].headers
    assert sent["Authorization"] == f"Bearer {FAKE_MULTI_AGENT_TOKEN}"
    assert sent[REQUEST_ID_HEADER] == request_id
    assert "cookie" not in sent
    assert forwarded_headers({REQUEST_ID_HEADER: " ", "traceparent": "garbage"}) == {}
