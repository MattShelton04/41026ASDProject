"""Tests for the opt-in authenticated and redacted development evidence view."""

from pathlib import Path
from uuid import UUID, uuid4

from agent_core import transition_run
from ai_mode import create_app
from ai_mode.configuration import Settings
from ai_mode.services import AppServices
from shared_contracts import AgentStep, RunStatus, StepPhase, StepStatus


def test_evidence_view_is_hidden_without_bearer_token_and_redacts_fields(
    app_services: AppServices,
) -> None:
    settings = Settings(
        database_path=Path("unused.sqlite3"),
        openai_api_key=None,
        openai_timeout_seconds=1,
        max_model_response_bytes=10_000,
        evidence_access_token="development-token",
    )
    app = create_app(settings, services=app_services)
    app.config.update(TESTING=True)
    created = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Show safe evidence"},
    )
    run_id = UUID(created.get_json()["id"])
    detail = app_services.store.get(run_id)
    assert detail is not None
    planning = transition_run(detail.run, RunStatus.PLANNING, now=app_services.clock.now())
    app_services.store.save(
        planning,
        expected_version=detail.run.version,
        step=AgentStep(
            id=uuid4(),
            run_id=run_id,
            sequence=1,
            phase=StepPhase.PLAN,
            status=StepStatus.RUNNING,
            input={"password": "never-render-this"},
        ),
    )

    hidden = app.test_client().get(f"/development/agent-runs/{run_id}")
    visible = app.test_client().get(
        f"/development/agent-runs/{run_id}",
        headers={"Authorization": "Bearer development-token"},
    )

    assert hidden.status_code == 404
    assert visible.status_code == 200
    assert b"[REDACTED]" in visible.data
    assert b"never-render-this" not in visible.data
