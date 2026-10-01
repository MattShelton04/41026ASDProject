from __future__ import annotations

import io
import json
from typing import Any

import pytest

from propertyscope_suburb_analytics.app import (
    APPROVED_TOOL_ALLOWLISTS,
    FEATURE_KEY,
    TOOL_ALLOWLIST,
    _validate_comparison,
    create_app,
)
from propertyscope_suburb_analytics.clients import ServiceError
from shared_testkit import assert_grounded_allowlist_accepted


class FakeClient:
    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if path == "/health/ready":
            return {"status": "ready"}
        if path == "/internal/v1/suburbs/NSW/Parramatta":
            return {"suburb": {"locality": "Parramatta", "state": "NSW"}}
        if path == "/internal/v1/published/context?locality=Parramatta":
            return {
                "locality": "Parramatta",
                "population": [{"sal_name": "Parramatta", "usual_resident_population": 30000}],
                "schools": [{"school_code": "1", "school_name": "Example School"}],
                "crime": [{"source_category_key": "property", "observed_months": ["2026-01"]}],
                "sources": [{"dataset_id": "bocsar-crime", "release_id": "release-1"}],
            }
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


class RunAi:
    def __init__(
        self, *, feature_key: str = FEATURE_KEY, allowlist: list[str] | None = None
    ) -> None:
        self.feature_key = feature_key
        self.allowlist = allowlist or list(TOOL_ALLOWLIST)

    def request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if method == "GET" and path == "/api/v1/agent-runs/run-1":
            return {
                "run": {
                    "id": "run-1",
                    "feature_key": self.feature_key,
                    "tool_allowlist": self.allowlist,
                    "status": "succeeded",
                }
            }
        if method == "GET" and path.startswith("/api/v1/agent-runs/run-1/events"):
            return {"items": []}
        if method == "POST" and path == "/api/v1/agent-runs/run-1/cancel":
            return {"id": "run-1", "status": "cancelling"}
        raise AssertionError((method, path, payload))


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


def test_saved_comparison_has_no_ai_run_endpoint() -> None:
    app = create_app(FakeClient(), UnavailableAi())
    status, payload = call(
        app, "/api/suburb-analytics/v1/suburb-comparisons/comparison-1/agent-runs", "POST", {}
    )
    assert status == 404
    assert payload["code"] == "route_not_found"


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
    assert ai.payload["tool_allowlist"] == list(TOOL_ALLOWLIST)
    assert "crime.compare.v1" not in ai.payload["tool_allowlist"]
    assert "trusted_identifiers" not in ai.payload
    objective = ai.payload["objective"]
    assert "do not infer crime causes" in objective.casefold()
    assert "Do not compare or rank suburbs" in objective


def test_assistant_rejects_comparison_context() -> None:
    app = create_app(FakeClient(), RecordingAi())
    status, payload = call(
        app,
        "/api/suburb-analytics/v1/assistant/turns",
        "POST",
        {"message": "Compare these", "context": {"comparison_id": "comparison-1"}},
    )
    assert status == 422
    assert "comparison context" in payload["detail"]


def test_grounded_runs_stay_owned_and_foreign_runs_are_hidden() -> None:
    def accepts(wire_allowlist: list[str]) -> bool:
        return tuple(wire_allowlist) in APPROVED_TOOL_ALLOWLISTS

    assert_grounded_allowlist_accepted(accepts, TOOL_ALLOWLIST)
    grounded = [*TOOL_ALLOWLIST, "context.retrieve.v1"]
    app = create_app(FakeClient(), RunAi(allowlist=grounded))
    for suffix in ("", "/events?after=0"):
        status, _ = call(app, f"/api/suburb-analytics/v1/assistant/turns/run-1{suffix}")
        assert status == 200
    status, _ = call(app, "/api/suburb-analytics/v1/assistant/turns/run-1/cancel", "POST", {})
    assert status == 200

    foreign = create_app(FakeClient(), RunAi(feature_key="student-4-due-diligence"))
    status, payload = call(foreign, "/api/suburb-analytics/v1/assistant/turns/run-1")
    assert status == 404
    assert payload["code"] == "assistant_turn_not_found"


def test_published_context_tool_returns_bounded_source_aware_evidence() -> None:
    app = create_app(FakeClient(), UnavailableAi())
    status, payload = call(
        app,
        "/api/suburb-analytics/v1/tools/suburb.published-context.v1",
        "POST",
        {"locality": "Parramatta"},
    )
    assert status == 200
    assert payload["status"] == "available"
    assert payload["population"]["usual_resident_population"] == 30000
    assert payload["sources"][0]["release_id"] == "release-1"
    assert any("not establish safety" in item for item in payload["limitations"])


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


@pytest.mark.parametrize("month", ["2026-00", "2026-13", "0000-01", "2026-1", "20x6-01"])
def test_saved_comparison_rejects_invalid_calendar_months(month: str) -> None:
    with pytest.raises(ValueError, match="month"):
        _validate_comparison(
            {
                "name": "Calendar test",
                "localities": ["Parramatta"],
                "measure": "count",
                "from_month": month,
                "to_month": "2026-12",
            }
        )


@pytest.mark.parametrize("version", [True, 0, "1"])
def test_saved_comparison_requires_positive_integer_version(version: object) -> None:
    with pytest.raises(ValueError, match="version"):
        _validate_comparison(
            {
                "name": "Version test",
                "localities": ["Parramatta"],
                "measure": "count",
                "from_month": "2026-01",
                "to_month": "2026-12",
                "version": version,
            },
            require_version=True,
        )
