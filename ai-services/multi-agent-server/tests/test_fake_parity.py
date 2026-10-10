"""The shared_testkit fake answers the same scenario with the same statuses and shapes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from flask import Flask

from multi_agent_server.templates import load_template
from shared_contracts.multi_agent import MULTI_AGENT_API_PREFIX
from shared_testkit import FakeMultiAgentServer

API = MULTI_AGENT_API_PREFIX
TOKEN = "test-multi-agent-token-0123456789abcdef"
RECORD_ID = "8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11"
TEMPLATE = Path(__file__).parent / "fixtures" / "workflow.yaml"
START = {"template_id": "example-readiness-review", "input": {"record_id": RECORD_ID}}


def scenario(client: httpx.Client) -> list[tuple[int, Any]]:
    """Exercise every route; return (status, shape) pairs to compare."""
    observed: list[tuple[int, Any]] = []

    def record(response: httpx.Response, shape: Callable[[Any], Any]) -> Any:
        body = response.json()
        observed.append((response.status_code, shape(body)))
        return body

    def keys(body: Any) -> Any:
        return sorted(body)

    def problem(body: Any) -> Any:
        return body["code"]

    record(client.get(f"{API}/templates"), lambda body: body["count"])
    record(client.get(f"{API}/templates/example-readiness-review"), keys)
    record(client.get(f"{API}/templates/missing"), problem)
    run = record(client.post(f"{API}/runs", json=START), keys)
    record(client.post(f"{API}/runs", json={**START, "input": {}}), problem)
    record(client.post(f"{API}/runs", json={"template_id": "Bad"}), problem)
    record(client.get(f"{API}/runs/{run['id']}"), lambda body: (body["state"], keys(body)))
    record(
        client.post(
            f"{API}/runs/{run['id']}/decision",
            json={"decision": "correct", "note": "again", "actor": "a"},
        ),
        lambda body: (body["state"], body["round"], len(body["superseded"])),
    )
    record(
        client.post(
            f"{API}/runs/{run['id']}/decision",
            json={"decision": "partial", "note": "n", "actor": "a", "accepted_step_ids": ["x"]},
        ),
        problem,
    )
    record(
        client.post(
            f"{API}/runs/{run['id']}/decision",
            json={"decision": "approve", "actor": "a"},
        ),
        lambda body: (body["state"], body["available_actions"]),
    )
    record(
        client.post(f"{API}/runs/{run['id']}/cancel"),
        problem,
    )
    record(client.get(f"{API}/runs?limit=0"), problem)
    record(client.get(f"{API}/runs?limit=5"), lambda body: (body["count"], keys(body["items"][0])))
    full = record(client.get(f"{API}/runs/{run['id']}/history"), keys)
    record(
        client.get(
            f"{API}/runs/{run['id']}/history",
            params={"after_history": full["history"][-1]["sequence"] - 1, "after_audit": 999},
        ),
        lambda body: (len(body["history"]), body["audit"], body["state"]),
    )
    record(client.get(f"{API}/runs/{run['id']}/history?after_audit=-1"), problem)
    record(client.get(f"{API}/runs/{uuid4()}/history?after_audit=x"), problem)
    record(client.get(f"{API}/runs/not-a-uuid"), problem)
    return observed


@pytest.fixture
def real(app: Flask) -> httpx.Client:
    return httpx.Client(
        transport=httpx.WSGITransport(app=app),
        base_url="http://multi-agent",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )


def test_fake_matches_the_server(real: httpx.Client) -> None:
    fake = FakeMultiAgentServer([load_template(TEMPLATE)], token=TOKEN)
    double = httpx.Client(
        transport=fake.transport(),
        base_url="http://multi-agent",
        headers={"Authorization": f"Bearer {TOKEN}"},
    )

    assert scenario(double) == scenario(real)
