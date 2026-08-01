"""Component tests for the versioned agent-run HTTP API."""

from uuid import UUID, uuid4

from flask import Flask

from agent_core import transition_run
from ai_mode.queue import RunQueueFullError
from ai_mode.services import AppServices
from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    REQUEST_ID_HEADER,
    AgentStep,
    ApprovalStatus,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolCall,
)
from shared_testkit import assert_problem_detail


def test_create_validates_media_type_and_contract(app: Flask) -> None:
    client = app.test_client()

    media_response = client.post("/api/v1/agent-runs", data="{}")
    validation_response = client.post(
        "/api/v1/agent-runs", json={"feature_key": "INVALID SPACE", "objective": ""}
    )

    assert_problem_detail(media_response.get_json(), status=415, code="unsupported_media_type")
    assert_problem_detail(validation_response.get_json(), status=422, code="validation_failed")


def test_create_persists_before_enqueue_and_propagates_request_id(
    app: Flask, app_services: AppServices
) -> None:
    response = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find verified records"},
        headers={REQUEST_ID_HEADER: "request-123"},
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["status"] == "queued"
    assert response.headers[REQUEST_ID_HEADER] == "request-123"
    assert response.headers[AGENT_RUN_ID_HEADER] == payload["id"]
    assert response.headers["Location"].endswith(payload["id"])
    detail = app_services.store.get(app_services.ids.new())
    assert detail is not None
    assert detail.run.request_id == "request-123"
    assert app_services.queue.run_ids == [detail.run.id]  # type: ignore[attr-defined]


def test_create_remains_accepted_when_wakeup_queue_is_full(
    app: Flask, app_services: AppServices
) -> None:
    class FullQueue:
        def enqueue(self, run_id: UUID) -> None:
            raise RunQueueFullError("full")

    app_services.queue = FullQueue()

    response = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find records"},
    )

    assert response.status_code == 202
    run_id = UUID(response.get_json()["id"])
    assert response.headers[AGENT_RUN_ID_HEADER] == str(run_id)
    assert app_services.store.get(run_id) is not None


def test_get_and_cancel_are_typed_and_cancellation_is_idempotent(
    app: Flask, app_services: AppServices
) -> None:
    created = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find records"},
    )
    run_id = created.get_json()["id"]

    detail = app.test_client().get(f"/api/v1/agent-runs/{run_id}")
    cancelled = app.test_client().post(f"/api/v1/agent-runs/{run_id}/cancel")
    repeated = app.test_client().post(f"/api/v1/agent-runs/{run_id}/cancel")

    assert detail.status_code == 200
    assert detail.get_json()["run"]["id"] == run_id
    assert cancelled.get_json()["status"] == "cancelled"
    assert repeated.get_json() == cancelled.get_json()


def test_missing_run_uses_shared_problem_contract(app: Flask) -> None:
    response = app.test_client().get("/api/v1/agent-runs/00000000-0000-0000-0000-000000000000")

    assert_problem_detail(response.get_json(), status=404, code="agent_run_not_found")


def test_review_approval_is_persisted_and_requeues_exactly_one_action(
    app: Flask, app_services: AppServices
) -> None:
    created = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Delete one record"},
    )
    run_id = UUID(created.get_json()["id"])
    detail = app_services.store.get(run_id)
    assert detail is not None
    planning = transition_run(detail.run, RunStatus.PLANNING, now=app_services.clock.now())
    app_services.store.save(planning, expected_version=detail.run.version)
    ready = transition_run(planning, RunStatus.READY, now=app_services.clock.now())
    app_services.store.save(ready, expected_version=planning.version)
    review_required = transition_run(ready, RunStatus.REVIEW_REQUIRED, now=app_services.clock.now())
    step_id = uuid4()
    call = ToolCall(
        id=uuid4(),
        run_id=run_id,
        step_id=step_id,
        tool_name="student_1.records.delete.v1",
        tool_version="v1",
        arguments={"record_id": 1},
        idempotency_key=f"{run_id}:1:v1",
        approval_status=ApprovalStatus.PENDING,
    )
    pending = AgentStep(
        id=step_id,
        run_id=run_id,
        sequence=1,
        phase=StepPhase.ACT,
        status=StepStatus.PENDING,
        input={"tool_call": call.model_dump(mode="json")},
    )
    app_services.store.save(
        review_required,
        expected_version=ready.version,
        step=pending,
    )

    response = app.test_client().post(
        f"/api/v1/agent-runs/{run_id}/reviews",
        json={"decision": "approve", "reviewer": "reviewer@example.test"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["run"]["status"] == "ready"
    assert payload["reviews"][0]["decision"] == "approve"
    assert app_services.queue.run_ids == [run_id, run_id]  # type: ignore[attr-defined]
