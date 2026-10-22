"""CI smoke validates AI degradation, not a successful live-provider run."""

from __future__ import annotations

import ast
import json
import runpy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/compose_smoke.py"


@pytest.mark.parametrize("parent_exists", [False, True])
def test_initial_smoke_creates_state_directory_and_restart_can_read_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, parent_exists: bool
) -> None:
    """Exercise the CI entry point without Docker, network access or seeded-data writes."""
    smoke = runpy.run_path(str(SCRIPT))
    state = tmp_path / ".propertyscope-runtime" / "nested" / "student5-smoke.json"
    if parent_exists:
        state.parent.mkdir(parents=True)
    assert state.parent.exists() is parent_exists

    def fake_request(
        base_url: str, method: str, path: str, *args: Any, **kwargs: Any
    ) -> tuple[int, dict[str, Any]]:
        assert base_url == "http://student5.test"
        if path.endswith(("case-summary-runs", "assistant/turns")):
            return 503, {"code": "integration_unavailable"}
        if path.endswith("evidence-reviews/template"):
            return 503, {"code": "multi_agent_unavailable"}
        if path.endswith("/evidence"):
            return 200, {"sections": {"feature_3": {"state": "unavailable"}}}
        if method == "GET" and path.endswith("/seed"):
            return 404, {}
        if method == "DELETE":
            return 200, {}
        return (201 if method == "POST" else 200), {
            "id": "persisted",
            "name": "Compose persistence probe",
            "version": 1,
            "status": "paused",
            "property_validation_state": "unavailable",
            "journey_stage": "Inspecting",
            "completed": True,
            "total": 10,
            "items": [{"id": "seed"}],
        }

    response = MagicMock()
    response.__enter__.return_value.status = 200
    response.__enter__.return_value.read.return_value = b"/features/buyer-workspaces/#buyer-cases"
    monkeypatch.setitem(smoke["initial"].__globals__, "request", fake_request)
    monkeypatch.setitem(
        smoke["initial"].__globals__, "dependency_urlopen", lambda *args, **kwargs: response
    )
    smoke["initial"]("http://student5.test", "http://shared.test", state)
    assert json.loads(state.read_text("utf-8")) == {
        "case_id": "persisted",
        "deleted_seed_id": "seed",
    }
    smoke["verify_restart"]("http://student5.test", state)


def test_smoke_checks_do_not_depend_on_optimisable_assertions() -> None:
    assert not any(
        isinstance(node, ast.Assert) for node in ast.walk(ast.parse(SCRIPT.read_text("utf-8")))
    )
    smoke = runpy.run_path(str(SCRIPT))
    with pytest.raises(RuntimeError, match="expected failure"):
        smoke["require"](False, "expected failure")


@pytest.mark.parametrize("available", [False, True])
def test_compose_smoke_requires_ai_disabled(
    monkeypatch: pytest.MonkeyPatch, available: bool
) -> None:
    smoke = runpy.run_path(str(SCRIPT))
    requests: list[tuple[str, str]] = []

    def fake_request(
        base_url: str, method: str, path: str, *args: Any, **kwargs: Any
    ) -> tuple[int, dict[str, Any]]:
        assert base_url == "http://student5.test"
        requests.append((method, path))
        return (
            202 if available else 503,
            {
                "code": "multi_agent_unavailable"
                if path.endswith("/template")
                else "integration_unavailable"
            },
        )

    check = smoke["check_ai_disabled"]
    monkeypatch.setitem(check.__globals__, "request", fake_request)
    if available:
        with pytest.raises(RuntimeError):
            check("http://student5.test", "case-id")
    else:
        check("http://student5.test", "case-id")
        assert requests == [
            ("POST", "/api/buyer-workspaces/v1/buyer-cases/case-id/case-summary-runs"),
            ("POST", "/api/buyer-workspaces/v1/assistant/turns"),
            ("GET", "/api/buyer-workspaces/v1/buyer-cases/case-id/evidence-reviews/template"),
        ]
