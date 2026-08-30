"""Component tests for the versioned agent-run HTTP API."""

from uuid import UUID, uuid4

from flask import Flask

from agent_core import transition_run
from ai_mode.api import _request_hash
from ai_mode.persistence import PersistenceError
from ai_mode.queue import RunQueueFullError
from ai_mode.services import AppServices
from shared_contracts import (
    AGENT_RUN_ID_HEADER,
    IDEMPOTENCY_KEY_HEADER,
    REQUEST_ID_HEADER,
    TRACEPARENT_HEADER,
    AgentRunRequest,
    AgentStep,
    ApprovalStatus,
    ModelRoleName,
    RunStatus,
    StepPhase,
    StepStatus,
    ToolCall,
    ToolError,
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


def test_model_registry_is_visible_and_unknown_profiles_are_rejected(app: Flask) -> None:
    client = app.test_client()
    services = app.extensions["ai_mode_services"]
    services.default_model_profile = "gemini-development.v1"

    catalogue = client.get("/api/v1/model-profiles")
    rejected = client.post(
        "/api/v1/agent-runs",
        json={
            "feature_key": "student-1-feature",
            "objective": "Find records",
            "model_profile": "unregistered.v1",
        },
    )

    assert catalogue.status_code == 200
    assert catalogue.get_json()["default_profile"] == "gemini-development.v1"
    assert {item["provider"] for item in catalogue.get_json()["models"]} == {
        "gemini",
        "openai",
    }
    assert {item["model_id"] for item in catalogue.get_json()["models"]} == {
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gpt-5.6-luna",
        "gpt-5.6-terra",
    }
    assert_problem_detail(rejected.get_json(), status=422, code="model_profile_not_supported")

    profile = services.model_registry.profiles[0]
    services.model_registry = services.model_registry.model_copy(
        update={
            "profiles": (
                profile.model_copy(
                    update={"role_models": {ModelRoleName.REVIEWER: "gpt-5.6-terra"}}
                ),
            )
        }
    )
    incompatible = client.post(
        "/api/v1/agent-runs",
        json={
            "feature_key": "student-1-feature",
            "objective": "Find records",
            "model_profile": "remote-standard.v1",
        },
    )
    assert_problem_detail(
        incompatible.get_json(),
        status=422,
        code="model_profile_role_incompatible",
    )


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


def test_unsafe_request_id_is_replaced_before_persistence_and_propagation(
    app: Flask, app_services: AppServices
) -> None:
    response = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find records"},
        headers={REQUEST_ID_HEADER: "unsafe request id"},
    )

    generated = response.headers[REQUEST_ID_HEADER]
    run = app_services.store.get(UUID(response.get_json()["id"]))
    assert response.status_code == 202
    assert generated != "unsafe request id"
    assert UUID(generated)
    assert run is not None and run.run.request_id == generated


def test_create_is_idempotent_for_exact_retries_and_conflicts_on_changed_input(
    app: Flask,
    app_services: AppServices,
) -> None:
    client = app.test_client()
    headers = {IDEMPOTENCY_KEY_HEADER: "create-run-key"}
    payload = {"feature_key": "student-1-feature", "objective": "Find records"}

    first = client.post("/api/v1/agent-runs", json=payload, headers=headers)
    replay = client.post("/api/v1/agent-runs", json=payload, headers=headers)
    conflict = client.post(
        "/api/v1/agent-runs",
        json={**payload, "objective": "Different objective"},
        headers=headers,
    )

    assert first.status_code == replay.status_code == 202
    assert replay.get_json() == first.get_json()
    assert_problem_detail(conflict.get_json(), status=409, code="idempotency_conflict")
    assert app_services.queue.run_ids == [UUID(first.get_json()["id"])]  # type: ignore[attr-defined]


def test_secure_default_changes_hash_while_explicit_v4_preserves_legacy_hash() -> None:
    command = AgentRunRequest(feature_key="student-1-feature", objective="Find records")

    assert _request_hash(command) == (
        "d10ef2e9f604364185f42b470ddc10f689a5dbbf34d02573381ba73a86b67307"
    )
    legacy = command.evolve(prompt_set="default.v4")
    assert _request_hash(legacy) == (
        "c40ec5e92affe3fa737c05b99ca1c5cb60f7309a8317cc519937abfc6004155b"
    )


def test_traceparent_is_validated_and_persisted(app: Flask, app_services: AppServices) -> None:
    valid = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
    accepted = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find records"},
        headers={TRACEPARENT_HEADER: valid},
    )
    rejected = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find records"},
        headers={TRACEPARENT_HEADER: "not-a-trace"},
    )
    zero_trace = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find records"},
        headers={TRACEPARENT_HEADER: "00-00000000000000000000000000000000-0000000000000000-00"},
    )

    run = app_services.store.get(UUID(accepted.get_json()["id"]))
    assert run is not None and run.run.traceparent == valid
    assert_problem_detail(rejected.get_json(), status=400, code="traceparent_invalid")
    assert_problem_detail(zero_trace.get_json(), status=400, code="traceparent_invalid")


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


def test_events_use_an_exclusive_resumable_cursor(app: Flask) -> None:
    created = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find records"},
    )
    run_id = created.get_json()["id"]

    first = app.test_client().get(f"/api/v1/agent-runs/{run_id}/events")
    cursor = first.get_json()["next_cursor"]
    resumed = app.test_client().get(
        f"/api/v1/agent-runs/{run_id}/events",
        headers={"Last-Event-ID": str(cursor)},
    )

    assert first.status_code == 200
    assert [event["event_type"] for event in first.get_json()["items"]] == ["run.created"]
    assert first.get_json()["terminal"] is False
    assert resumed.get_json()["items"] == []
    assert resumed.get_json()["next_cursor"] == cursor


def test_terminal_event_page_is_true_only_after_all_events_are_consumed(
    app: Flask, app_services: AppServices
) -> None:
    created = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find records"},
    )
    run_id = UUID(created.get_json()["id"])
    detail = app_services.store.get(run_id)
    assert detail is not None
    planning = transition_run(detail.run, RunStatus.PLANNING, now=app_services.clock.now())
    app_services.store.save(planning, expected_version=detail.run.version)
    failed = transition_run(
        planning,
        RunStatus.FAILED,
        now=app_services.clock.now(),
        error=ToolError(code="test_failure", message="Expected test failure"),
    )
    app_services.store.save(failed, expected_version=planning.version)

    first = app.test_client().get(f"/api/v1/agent-runs/{run_id}/events?limit=1")
    first_page = first.get_json()
    second = app.test_client().get(
        f"/api/v1/agent-runs/{run_id}/events?limit=1&after={first_page['next_cursor']}"
    )
    second_page = second.get_json()
    final = app.test_client().get(
        f"/api/v1/agent-runs/{run_id}/events?limit=1&after={second_page['next_cursor']}"
    )

    assert first_page["terminal"] is False
    assert second_page["terminal"] is False
    assert final.get_json()["terminal"] is True
    assert len(first_page["items"]) == len(second_page["items"]) == 1
    assert len(final.get_json()["items"]) == 1


def test_event_cursor_rejects_values_outside_sqlite_integer_range(app: Flask) -> None:
    created = app.test_client().post(
        "/api/v1/agent-runs",
        json={"feature_key": "student-1-feature", "objective": "Find records"},
    )
    run_id = created.get_json()["id"]

    response = app.test_client().get(
        f"/api/v1/agent-runs/{run_id}/events?after=9223372036854775808"
    )

    assert_problem_detail(response.get_json(), status=400, code="event_cursor_invalid")


def test_request_body_limit_is_enforced_before_json_parsing(app: Flask) -> None:
    response = app.test_client().post(
        "/api/v1/agent-runs",
        data=b"{" + (b"x" * 70_000),
        content_type="application/json",
    )

    assert_problem_detail(response.get_json(), status=413, code="request_too_large")


def test_expected_and_unexpected_store_failures_use_safe_problem_details(
    app: Flask,
    app_services: AppServices,
) -> None:
    original = app_services.store

    class FailingStore:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def get(self, run_id: UUID):  # type: ignore[no-untyped-def]
            raise self.error

    app_services.store = FailingStore(PersistenceError("private database path"))  # type: ignore[assignment]
    expected = app.test_client().get(f"/api/v1/agent-runs/{uuid4()}")
    app_services.store = FailingStore(RuntimeError("private exception detail"))  # type: ignore[assignment]
    unexpected = app.test_client().get(f"/api/v1/agent-runs/{uuid4()}")
    app_services.store = original

    assert_problem_detail(expected.get_json(), status=503, code="state_store_unavailable")
    assert_problem_detail(unexpected.get_json(), status=500, code="internal_error")
    assert "private" not in expected.get_data(as_text=True)
    assert "private" not in unexpected.get_data(as_text=True)


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


def test_review_requires_json_media_type(app: Flask) -> None:
    response = app.test_client().post(
        f"/api/v1/agent-runs/{uuid4()}/reviews",
        data='{"decision":"approve","reviewer":"reviewer@example.test"}',
    )

    assert_problem_detail(response.get_json(), status=415, code="unsupported_media_type")
