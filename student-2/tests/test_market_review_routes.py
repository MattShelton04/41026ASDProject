"""Feature 2 market-brief proxy routes against the shared FakeMultiAgentServer.

The fake is loaded with Feature 2's real workflow manifest, so the template the proxy pins and
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

from propertyscope_market_intelligence.app import create_app
from propertyscope_market_intelligence.clients import MultiAgentClient
from propertyscope_market_intelligence.market_review_routes import (
    MARKET_BRIEF_DISABLED_DETAIL,
    MARKET_BRIEF_FEATURE_ID,
    MARKET_BRIEF_TEMPLATE_ID,
    brief_capabilities,
)
from shared_contracts.multi_agent import WORKFLOW_RUN_ID_HEADER, WorkflowTemplate
from shared_testkit import FAKE_MULTI_AGENT_TOKEN, FakeMultiAgentServer

MANIFEST = Path(__file__).resolve().parents[1] / "config" / "multi-agent" / "workflow.yaml"
BASE = "/api/market-intelligence/v1/market-briefs"
CASE_ID = "60000000-0000-4000-8000-000000000010"
PROBLEM_MEDIA_TYPE = "application/problem+json"


def _feature_template() -> WorkflowTemplate:
    return WorkflowTemplate.model_validate(yaml.safe_load(MANIFEST.read_text("utf-8")))


def _foreign_template(*, feature_id: str, template_id: str) -> WorkflowTemplate:
    document = yaml.safe_load(MANIFEST.read_text("utf-8"))
    document.update(id=template_id, feature_id=feature_id)
    return WorkflowTemplate.model_validate(document)


class _Offline:
    """Feature 2's other dependencies, unreachable: these tests are about the proxy alone."""

    state = "verified"

    def request(self, *_args: Any, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(503, json={"status": 503})

    def ready(self) -> bool:
        return False

    def validate_property(self, _property_ref: str) -> str:
        return "unavailable"

    def create_run(self, _payload: Any) -> httpx.Response:
        return httpx.Response(503, json={"status": 503})

    def get(self, _path: str, **_kwargs: Any) -> httpx.Response:
        return httpx.Response(503, json={"status": 503})

    def cancel(self, _run_id: str) -> httpx.Response:
        return httpx.Response(503, json={"status": 503})


def _refuse(_request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("multi-agent server is not listening")


def _client_for(fake: FakeMultiAgentServer, *, token: str = FAKE_MULTI_AGENT_TOKEN) -> FlaskClient:
    multi_agent = MultiAgentClient(
        "http://multi-agent",
        service_token=token,
        client=httpx.Client(transport=fake.transport()),
    )
    offline = _Offline()
    return create_app(
        store=offline, feature1=offline, ai_mode=offline, multi_agent=multi_agent
    ).test_client()


@pytest.fixture
def fake() -> FakeMultiAgentServer:
    return FakeMultiAgentServer(
        [
            _feature_template(),
            # A run owned by another feature, and one owned by Feature 2 under a different
            # template: the proxy must refuse both with 404.
            _foreign_template(
                feature_id="student-4-due-diligence", template_id="f4-some-other-review"
            ),
            _foreign_template(
                feature_id=MARKET_BRIEF_FEATURE_ID, template_id="f2-some-other-template"
            ),
        ],
        tool_results={"market.cases.inspect.v1": {"market_case": {"name": "Sydney 2025 snapshot"}}},
    )


@pytest.fixture
def client(fake: FakeMultiAgentServer) -> FlaskClient:
    return _client_for(fake)


def _start(client: FlaskClient) -> str:
    created = client.post(BASE, json={"input": {"market_case_id": CASE_ID}})
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
            {"template_id": template_id, "input": {"market_case_id": CASE_ID}}
        ).encode(),
    )
    return str(upstream.json()["id"])


def test_template_is_pinned_to_feature_2(client: FlaskClient) -> None:
    response = client.get(f"{BASE}/template")
    assert response.status_code == 200
    template = response.get_json()["template"]
    assert template["id"] == MARKET_BRIEF_TEMPLATE_ID
    assert template["feature_id"] == MARKET_BRIEF_FEATURE_ID


def test_start_returns_202_and_points_location_at_this_feature(client: FlaskClient) -> None:
    created = client.post(
        BASE, json={"input": {"market_case_id": CASE_ID}, "requested_by": "Burhan"}
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
        json={"input": {"market_case_id": CASE_ID}, "template_id": "f1-release-readiness-review"},
    )
    assert created.status_code == 202
    assert created.get_json()["template_id"] == MARKET_BRIEF_TEMPLATE_ID


def test_unexpected_start_fields_are_rejected(client: FlaskClient) -> None:
    rejected = client.post(BASE, json={"input": {}, "feature_id": "student-1-propertyscope"})
    assert rejected.status_code == 422
    assert rejected.get_json()["code"] == "invalid_market_brief_request"


def test_status_and_history_are_readable(client: FlaskClient) -> None:
    run_id = _start(client)
    detail = client.get(f"{BASE}/{run_id}")
    assert detail.status_code == 200
    assert detail.get_json()["template_id"] == MARKET_BRIEF_TEMPLATE_ID
    history = client.get(f"{BASE}/{run_id}/history?after_history=0&after_audit=0")
    assert history.status_code == 200
    assert "history" in history.get_json()


def test_a_decision_is_relayed_and_its_actor_is_bounded(client: FlaskClient) -> None:
    run_id = _start(client)
    decided = client.post(
        f"{BASE}/{run_id}/decision",
        json={"decision": "approve", "actor": "Burhan Naeem", "note": "Figures match."},
    )
    assert decided.status_code == 200, decided.get_json()

    rejected = client.post(f"{BASE}/{run_id}/decision", json={"decision": "approve", "actor": "  "})
    assert rejected.status_code == 422
    body = rejected.get_json()
    assert body["errors"][0] == {
        "field": "actor",
        "message": "actor must not be empty",
        "code": "invalid_actor",
    }
    assert rejected.content_type == PROBLEM_MEDIA_TYPE


def test_a_control_character_note_is_refused_before_the_audit_trail(client: FlaskClient) -> None:
    run_id = _start(client)
    rejected = client.post(
        f"{BASE}/{run_id}/decision",
        json={"decision": "reject", "actor": "Burhan", "note": "bad\x07note"},
    )
    assert rejected.status_code == 422
    assert rejected.get_json()["errors"][0]["code"] == "invalid_note"


def test_another_features_run_is_not_found(fake: FakeMultiAgentServer, client: FlaskClient) -> None:
    run_id = _foreign_run(fake, "f4-some-other-review")
    refused = client.get(f"{BASE}/{run_id}")
    assert refused.status_code == 404
    assert refused.get_json()["code"] == "market_brief_not_found"


def test_a_run_of_another_template_in_this_feature_is_not_found(
    fake: FakeMultiAgentServer, client: FlaskClient
) -> None:
    run_id = _foreign_run(fake, "f2-some-other-template")
    refused = client.get(f"{BASE}/{run_id}")
    assert refused.status_code == 404


def test_the_list_is_scoped_to_this_feature_and_template(client: FlaskClient) -> None:
    _start(client)
    page = client.get(f"{BASE}?limit=5")
    assert page.status_code == 200
    items = page.get_json()["items"]
    assert items
    assert all(
        item["feature_id"] == MARKET_BRIEF_FEATURE_ID
        and item["template_id"] == MARKET_BRIEF_TEMPLATE_ID
        for item in items
    )


def test_a_non_integer_limit_is_rejected(client: FlaskClient) -> None:
    rejected = client.get(f"{BASE}?limit=many")
    assert rejected.status_code == 422
    assert rejected.get_json()["code"] == "invalid_market_brief_request"


def test_a_run_can_be_cancelled(client: FlaskClient) -> None:
    run_id = _start(client)
    cancelled = client.post(f"{BASE}/{run_id}/cancel", json={"actor": "Burhan"})
    assert cancelled.status_code in {200, 409}


def test_without_a_service_token_the_feature_degrades_to_503(
    fake: FakeMultiAgentServer,
) -> None:
    """The required cloud baseline supplies an empty token on purpose."""
    unconfigured = _client_for(fake, token="")
    for method, path in (
        ("get", f"{BASE}/template"),
        ("get", BASE),
        ("get", f"{BASE}/{uuid.uuid4()}"),
    ):
        response = getattr(unconfigured, method)(path)
        assert response.status_code == 503, path
        assert response.get_json()["code"] == "multi_agent_unavailable"
        assert response.content_type == PROBLEM_MEDIA_TYPE

    started = unconfigured.post(BASE, json={"input": {"market_case_id": CASE_ID}})
    assert started.status_code == 503


def test_capabilities_report_configuration_without_a_network_call() -> None:
    assert brief_capabilities(multi_agent_configured=True) == {
        "market_brief": {"enabled": True, "detail": None}
    }
    disabled = brief_capabilities(multi_agent_configured=False)
    assert disabled["market_brief"]["enabled"] is False
    assert disabled["market_brief"]["detail"]


def test_capabilities_answer_200_when_the_server_is_not_configured(
    fake: FakeMultiAgentServer,
) -> None:
    """A deployment with the AI tier off must get a clear answer, not the 503 other routes give.

    CI's visual-capture stack and the required cloud baseline both run Compose without a
    Multi-Agent Server, so the page asks this before it mounts the panel.
    """
    response = _client_for(fake, token="").get(f"{BASE}/capabilities")
    assert response.status_code == 200
    assert response.get_json() == {
        "market_brief": {"enabled": False, "detail": MARKET_BRIEF_DISABLED_DETAIL}
    }


def test_capabilities_report_enabled_when_a_token_is_configured(
    fake: FakeMultiAgentServer,
) -> None:
    response = _client_for(fake).get(f"{BASE}/capabilities")
    assert response.status_code == 200
    assert response.get_json() == {"market_brief": {"enabled": True, "detail": None}}


def test_capabilities_do_not_depend_on_the_server_being_reachable(
    fake: FakeMultiAgentServer,
) -> None:
    """It answers from configuration alone, so an unreachable server is still `enabled`."""
    unreachable = MultiAgentClient(
        "http://multi-agent",
        service_token=FAKE_MULTI_AGENT_TOKEN,
        client=httpx.Client(transport=httpx.MockTransport(_refuse)),
    )
    offline = _Offline()
    http = create_app(
        store=offline, feature1=offline, ai_mode=offline, multi_agent=unreachable
    ).test_client()
    assert http.get(f"{BASE}/capabilities").get_json()["market_brief"]["enabled"] is True
    # The routes that do need the server still answer 503.
    assert http.get(f"{BASE}/template").status_code == 503
