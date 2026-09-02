from __future__ import annotations

import io
import json
from typing import Any

from propertyscope_suburb_analytics.app import create_app
from propertyscope_suburb_analytics.clients import ServiceError


class FakeClient:
    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path == "/health/ready":
            return {"status": "ready"}
        if path == "/internal/v1/suburbs/NSW/Parramatta":
            return {"suburb": {"locality": "Parramatta", "state": "NSW"}}
        if "crime-series" in path:
            return {
                "items": [
                    {
                        "month": "2026-01",
                        "value": 4,
                        "unit": "count",
                        "zero_missing_state": "observed",
                        "measure_source": "fixture_count",
                        "source_release": "demo-2026.1",
                    }
                ],
                "count": 1,
            }
        if path.startswith("/internal/v1/suburb-comparisons/"):
            return {
                "comparison": {
                    "id": "comparison-1",
                    "name": "Two suburbs",
                    "localities": ["Parramatta", "Newtown"],
                    "from_month": "2026-01",
                    "to_month": "2026-06",
                    "measure": "count",
                    "version": 1,
                }
            }
        if path == "/internal/v1/suburb-comparisons":
            return {"items": [], "count": 0}
        raise AssertionError(path)


class UnavailableAi:
    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        raise ServiceError(503, {"code": "dependency_unavailable"})


class RecordingAi:
    def __init__(self) -> None:
        self.payload: dict[str, Any] | None = None

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        assert method == "POST" and path == "/api/v1/agent-runs"
        self.payload = payload
        return {"id": "run-1", "status": "queued"}


def call(
    app: Any, path: str, method: str = "GET", body: dict[str, Any] | None = None
) -> tuple[int, dict[str, Any]]:
    encoded = json.dumps(body or {}).encode()
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path.split("?", 1)[0],
        "QUERY_STRING": path.partition("?")[2],
        "CONTENT_LENGTH": str(len(encoded)) if body is not None else "0",
        "wsgi.input": io.BytesIO(encoded),
    }
    status: list[str] = []
    result = b"".join(app(environ, lambda value, headers: status.append(value)))
    return int(status[0].split()[0]), json.loads(result)


def test_comparison_rejects_mixed_or_incomplete_selection() -> None:
    app = create_app(FakeClient(), UnavailableAi())
    status, payload = call(
        app, "/api/suburb-analytics/v1/crime/compare?localities=Parramatta&measure=count"
    )
    assert status == 422
    assert payload["code"] == "incomparable_selection"


def test_same_measure_comparison_returns_neutral_limitations() -> None:
    app = create_app(FakeClient(), UnavailableAi())
    status, payload = call(
        app, "/api/suburb-analytics/v1/crime/compare?localities=Parramatta,Newtown&measure=count"
    )
    assert status == 200
    assert len(payload["series"]) == 2
    assert any("not a safety ranking" in item for item in payload["limitations"])


def test_ai_failure_does_not_hide_deterministic_feature() -> None:
    app = create_app(FakeClient(), UnavailableAi())
    status, payload = call(
        app, "/api/suburb-analytics/v1/suburb-comparisons/comparison-1/agent-runs", "POST", {}
    )
    assert status == 503
    assert "saved comparisons and charts still work" in payload["detail"]


def test_assistant_turn_is_bounded_to_neutral_feature_tools() -> None:
    ai = RecordingAi()
    app = create_app(FakeClient(), ai)
    status, payload = call(
        app,
        "/api/suburb-analytics/v1/assistant/turns",
        "POST",
        {"message": "What evidence is available?", "context": {"locality": "Parramatta"}},
    )
    assert status == 202 and payload["id"] == "run-1"
    assert ai.payload is not None
    assert ai.payload["tool_allowlist"] == [
        "suburb.snapshot.v1",
        "crime.compare.v1",
        "crime.methodology.v1",
    ]
    objective = ai.payload["objective"]
    assert "do not infer crime causes" in objective
    assert "rank safety/desirability" in objective


def test_assistant_failure_explains_deterministic_fallback() -> None:
    app = create_app(FakeClient(), UnavailableAi())
    status, payload = call(
        app,
        "/api/suburb-analytics/v1/assistant/turns",
        "POST",
        {"message": "Summarise Parramatta", "context": {"locality": "Parramatta"}},
    )
    assert status == 503
    assert "saved comparisons and charts still work" in payload["detail"]
