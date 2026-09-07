"""Server credentials cross feature AI adapters without entering user payloads."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import httpx
import pytest

TOKEN = "dedicated-local-host-token-1234567890"


@pytest.fixture(autouse=True)
def feature_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[2]
    for number in range(1, 6):
        monkeypatch.syspath_prepend(str(root / f"student-{number}/backend/src"))


@pytest.mark.parametrize(
    "module",
    [
        "propertyscope_data_platform",
        "propertyscope_market_intelligence",
        "propertyscope_due_diligence",
    ],
)
def test_httpx_ai_adapters_authenticate_owned_host(module: str) -> None:
    client_type: Any = import_module(f"{module}.clients").AiModeClient
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={})

    with httpx.Client(transport=httpx.MockTransport(respond)) as transport:
        client = client_type("http://host.test", client=transport, service_token=TOKEN)
        if module == "propertyscope_data_platform":
            client.create_run({"goal": "example"}, {"X-Request-ID": "req-1"})
            client.get("/api/v1/agent-runs/id", {})
            client.cancel_run("id", {})
        else:
            client.create_run({"goal": "example"})
            client.get("/api/v1/agent-runs/id")
            client.cancel("id")
    assert len(requests) == 3
    for request in requests:
        assert request.headers["X-PropertyScope-AI-Token"] == TOKEN
        assert TOKEN not in str(request.url)
        assert TOKEN.encode() not in request.content


def test_feature3_ai_adapter_authenticates_without_changing_database_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feature3 = import_module("propertyscope_suburb_analytics.clients")
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = b"{}"
    opening = Mock(return_value=response)
    monkeypatch.setattr(feature3, "urlopen", opening)
    feature3.HttpClient("http://host.test", service_token=TOKEN).request(
        "GET", "/api/v1/model-profiles"
    )
    assert opening.call_args.args[0].get_header("X-propertyscope-ai-token") == TOKEN
    feature3.HttpClient("http://database.test").request("GET", "/health/ready")
    assert opening.call_args.args[0].get_header("X-propertyscope-ai-token") is None


def test_feature5_ai_adapter_keeps_credential_out_of_user_body() -> None:
    transport = Mock()
    client = import_module("propertyscope_buyer_workspaces.integrations").AiModeClient(
        "http://host.test", service_token=TOKEN, transport=transport
    )
    client.create_run({"goal": "example"}, request_id="req-1", idempotency_key=None)
    client.get_run("run-1", request_id="req-1")
    for call in transport.request.call_args_list:
        assert call.kwargs["headers"]["X-PropertyScope-AI-Token"] == TOKEN
        assert TOKEN not in str(call.kwargs["json_body"])
