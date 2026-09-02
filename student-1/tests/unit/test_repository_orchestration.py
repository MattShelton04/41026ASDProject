from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any, cast

import pytest
from flask import Flask
from psycopg import errors

from propertyscope_data_store.api import create_blueprint, register_error_handlers
from propertyscope_data_store.errors import ConflictError, ValidationError
from propertyscope_data_store.persistence_support import project_run
from propertyscope_data_store.query_specs import PROPERTY_RECORD_SPEC
from propertyscope_data_store.repository import (
    PROPERTY_SEARCH_CANDIDATE_LIMIT,
    PropertyScopeStore,
    PropertySearchResults,
    _is_supported_acquisition_scope,
    _normalise_property_query,
)
from propertyscope_data_store.runtime_registry import RuntimeRegistry, load_runtime_registry

FEATURE_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_REGISTRY = load_runtime_registry(FEATURE_ROOT / "config" / "job-profiles")


def test_complete_psi_scope_remains_supported_alongside_bounded_year_ranges() -> None:
    assert _is_supported_acquisition_scope(
        {
            "profile": "full-data",
            "all_records": True,
            "all_history": True,
            "include_current_weekly": True,
        },
        import_profile="psi-sales",
    )


class ScriptedConnection:
    def __init__(self, responses: Sequence[Mapping[str, Any] | None]) -> None:
        self.responses = list(responses)
        self.queries: list[str] = []
        self.parameters: list[Sequence[object] | None] = []
        self.current: Mapping[str, Any] | None = None
        self.committed = False
        self.commit_count = 0

    def execute(self, query: str, parameters: Sequence[object] | None = None) -> ScriptedConnection:
        self.queries.append(" ".join(query.split()))
        self.parameters.append(parameters)
        self.current = self.responses.pop(0)
        return self

    def fetchone(self) -> Mapping[str, Any] | None:
        return self.current

    def commit(self) -> None:
        self.committed = True
        self.commit_count += 1

    def rollback(self) -> None:
        pass


class ConnectedStore(PropertyScopeStore):
    def __init__(
        self,
        connection: ScriptedConnection,
        *,
        runtime_registry: RuntimeRegistry | None = None,
    ) -> None:
        self.test_connection = connection
        self._runtime_registry = cast(RuntimeRegistry, runtime_registry)

    @contextmanager
    def connection(self) -> Iterator[Any]:
        yield self.test_connection


class CancellableConnection(ScriptedConnection):
    def __init__(self, responses: Sequence[Mapping[str, Any] | None]) -> None:
        super().__init__(responses)
        self.cancelled = Event()

    def cancel(self) -> None:
        self.cancelled.set()


def _consumer_import_values(release_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": "a" * 64,
        "record_count": 3,
        "artifact_path": f"/api/data-platform/v1/dataset-releases/{release_id}/artifact",
        "expected_release_version": 2,
        "comment": "Reviewed",
        "idempotency_key": "delivery-key-one",
        "request_id": "request-one",
    }
    values.update(overrides)
    return values


class SequencedConnectionStore(PropertyScopeStore):
    def __init__(self, connections: Sequence[ScriptedConnection]) -> None:
        self.connections = list(connections)
        self.lock = Lock()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        with self.lock:
            connection = self.connections.pop(0)
        yield connection


def test_repository_reuses_one_collaborator_per_persistence_aggregate() -> None:
    store = ConnectedStore(ScriptedConnection([]))

    assert store._properties() is store._properties()
    assert store._releases() is store._releases()


def test_import_watcher_cancels_source_scale_insertion_statement() -> None:
    operation_id = uuid.uuid4()
    connection = CancellableConnection([])

    class CancelledStore(ConnectedStore):
        def import_cancel_requested(self, requested: uuid.UUID) -> bool:
            assert requested == operation_id
            return True

    with CancelledStore(connection)._cancellable_import_connection(operation_id):
        assert connection.cancelled.wait(1.5)


@pytest.mark.parametrize(
    "phase_key",
    [
        "artifact_verification",
        "typed_staging",
        "identity_revision_derivation",
        "address_resolution",
        "target_materialisation",
        "verification",
    ],
)
def test_every_durable_import_phase_remains_exactly_cancellable(phase_key: str) -> None:
    operation_id = uuid.uuid4()
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()
    progress = ScriptedConnection(
        [
            {"ingestion_run_id": run_id, "run_task_id": task_id},
            None,
            None,
        ]
    )
    statement = CancellableConnection([])
    cancellation = ScriptedConnection([{"cancel_requested_at": datetime.now(UTC)}])
    store = SequencedConnectionStore([progress, statement, cancellation])

    store.update_import_progress(
        operation_id,
        phase_key=phase_key,
        phase=phase_key.replace("_", " "),
        rows_processed=0,
        bytes_processed=0,
    )
    with store._cancellable_import_connection(operation_id):
        assert statement.cancelled.wait(1.5)

    assert "progress_phase_key=%s" in progress.queries[0]
    assert progress.parameters[0] is not None
    assert progress.parameters[0][0] == phase_key


def test_import_watcher_cancels_source_scale_work_after_lease_loss() -> None:
    operation_id = uuid.uuid4()
    connection = CancellableConnection([])
    lease_failed = Event()

    class ActiveStore(ConnectedStore):
        def import_cancel_requested(self, requested: uuid.UUID) -> bool:
            assert requested == operation_id
            return False

    with ActiveStore(connection)._cancellable_import_connection(
        operation_id,
        lease_failed_event=lease_failed,
    ):
        lease_failed.set()
        assert connection.cancelled.wait(1.5)


def test_import_watcher_cancels_source_scale_work_during_loader_shutdown() -> None:
    operation_id = uuid.uuid4()
    connection = CancellableConnection([])
    loader_stopped = Event()

    class ActiveStore(ConnectedStore):
        def import_cancel_requested(self, requested: uuid.UUID) -> bool:
            assert requested == operation_id
            return False

    with ActiveStore(connection)._cancellable_import_connection(
        operation_id,
        stop_event=loader_stopped,
    ):
        loader_stopped.set()
        assert connection.cancelled.wait(1.5)


def test_activation_watcher_cancels_candidate_index_materialisation() -> None:
    operation_id = uuid.uuid4()
    release_id = uuid.uuid4()
    connection = CancellableConnection(
        [
            {
                "id": operation_id,
                "dataset_release_id": release_id,
                "dataset_id": "gnaf-nsw",
                "release_status": "awaiting_review",
                "release_version": 4,
                "expected_release_version": 4,
            }
        ]
    )
    original_execute = connection.execute

    def execute_until_cancelled(
        query: str, parameters: Sequence[object] | None = None
    ) -> CancellableConnection:
        if "UPDATE warehouse.gnaf_address SET published=TRUE" in query:
            assert connection.cancelled.wait(1.5)
            raise RuntimeError("statement cancelled")
        return cast(CancellableConnection, original_execute(query, parameters))

    connection.execute = execute_until_cancelled  # type: ignore[method-assign]
    stop = Event()
    stop.set()

    with pytest.raises(RuntimeError, match="statement cancelled"):
        ConnectedStore(connection).materialize_release_activation(
            operation_id,
            worker_id="loader-1",
            lease_token="lease-1",
            stop_event=stop,
        )
    assert connection.cancelled.is_set()


def test_activation_heartbeat_uses_a_separate_transaction_during_materialisation() -> None:
    operation_id = uuid.uuid4()
    release_id = uuid.uuid4()
    source_update_started = Event()
    allow_source_commit = Event()
    work = {
        "id": operation_id,
        "dataset_release_id": release_id,
        "dataset_id": "gnaf-nsw",
        "release_status": "awaiting_review",
        "release_version": 4,
        "expected_release_version": 4,
    }

    class BlockingWarehouseConnection(ScriptedConnection):
        def execute(
            self, query: str, parameters: Sequence[object] | None = None
        ) -> ScriptedConnection:
            if "UPDATE warehouse.gnaf_address SET published=TRUE" in query:
                self.queries.append(" ".join(query.split()))
                self.parameters.append(parameters)
                source_update_started.set()
                assert allow_source_commit.wait(2)
                self.current = None
                return self
            return super().execute(query, parameters)

    validation = ScriptedConnection([work])
    warehouse = BlockingWarehouseConnection([])
    heartbeat = ScriptedConnection([{"id": operation_id, "status": "running"}])
    marker = ScriptedConnection([{"id": operation_id, "status": "running"}])
    store = SequencedConnectionStore([validation, warehouse, heartbeat, marker])
    failure: list[BaseException] = []

    def materialize() -> None:
        try:
            store.materialize_release_activation(
                operation_id,
                worker_id="loader-1",
                lease_token="lease-1",
            )
        except Exception as error:  # pragma: no cover - asserted after joining the thread
            failure.append(error)

    worker = Thread(target=materialize)
    worker.start()
    assert source_update_started.wait(1)
    renewed = store.heartbeat_release_activation(
        operation_id,
        worker_id="loader-1",
        lease_token="lease-1",
        lease_seconds=120,
    )
    assert renewed["status"] == "running"
    allow_source_commit.set()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert failure == []
    assert warehouse.commit_count == 1
    assert marker.commit_count == 1


def test_job_creation_derives_registered_runtime_versions() -> None:
    source_id = uuid.uuid4()
    connection = ScriptedConnection([{"id": uuid.uuid4()}])
    values = {
        "source_definition_id": source_id,
        "name": "PSI sales",
        "profile_key": "nsw-psi-sales-year",
        "adapter_key": "psi-bulk",
        "release_builder_key": "property-sales",
        "import_profile_key": "psi-sales",
        "target_feature": "feature-2",
        "dataset_id": "nsw-psi-sales",
        "refresh_strategy": "full_refresh",
        "default_run_mode": "full_refresh",
        "quality_policy_key": "psi-sales.v1",
        "status": "active",
        "schedule_text": "manual",
    }

    ConnectedStore(connection, runtime_registry=RUNTIME_REGISTRY).create_job(values)

    parameters = connection.parameters[0]
    assert parameters is not None
    assert parameters[4] == "1.0.0"
    assert parameters[6] == "1.0.0"
    assert parameters[8] == "4.0.0"
    assert parameters[10] == "1.0.0"
    assert parameters[16] == "1.0.0"


def test_job_creation_rejects_unregistered_runtime_components() -> None:
    with pytest.raises(ConflictError, match="unknown runtime profile"):
        ConnectedStore(ScriptedConnection([]), runtime_registry=RUNTIME_REGISTRY).create_job(
            {"profile_key": "unknown"}
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("profile_version", "9.9.9"),
        ("adapter_key", "fixture-snapshot"),
        ("adapter_version", "9.9.9"),
        ("release_builder_key", "property-snapshot"),
        ("release_builder_version", "9.9.9"),
        ("import_profile_key", "property-fixture"),
        ("import_profile_version", "9.9.9"),
        ("quality_policy_key", "property-fixture.v1"),
        ("quality_policy_version", "9.9.9"),
    ),
)
def test_job_creation_rejects_runtime_values_that_conflict_with_profile(
    field: str, value: str
) -> None:
    with pytest.raises(ConflictError, match=rf"{field} conflicts with profile"):
        ConnectedStore(ScriptedConnection([]), runtime_registry=RUNTIME_REGISTRY).create_job(
            {
                "profile_key": "nsw-psi-sales-year",
                field: value,
            }
        )


def test_job_creation_fails_closed_without_injected_runtime_registry() -> None:
    with pytest.raises(ConflictError, match="runtime registry was not configured"):
        ConnectedStore(ScriptedConnection([])).create_job({"profile_key": "nsw-psi-sales-year"})


def test_claim_reconciles_expiry_and_only_claims_the_first_eligible_stage() -> None:
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()
    claimed = {
        "id": task_id,
        "ingestion_run_id": run_id,
        "logical_key": "00/discover",
        "stage": "discover",
        "status": "claimed",
    }
    connection = ScriptedConnection(
        [
            None,  # expired cancellation task reconciliation
            None,  # pending cancellation task reconciliation
            None,  # cancellation run reconciliation
            None,  # non-cancelled expired lease reconciliation
            claimed,
            None,  # run moves from queued to planning
            {"profile_key": "fixture", "run_mode": "full_refresh"},
        ]
    )

    task = ConnectedStore(connection).claim_task(worker_id="runner-1", lease_seconds=30)

    assert task is not None and task["id"] == str(task_id)
    run_update = next(
        query for query in connection.queries if "UPDATE ops.ingestion_run SET status=%s" in query
    )
    assert "SET status=%s" in run_update
    run_update_parameters = connection.parameters[5]
    assert run_update_parameters is not None
    assert run_update_parameters[0] == "discovering"
    candidate = next(query for query in connection.queries if "WITH candidate AS" in query)
    assert "predecessor.logical_key<task.logical_key" in candidate
    assert "predecessor.status NOT IN ('succeeded','skipped')" in candidate
    assert "run.status IN ('queued','planning','discovering','acquiring','staging'" in candidate
    interruption = next(
        query for query in connection.queries if "SET status='interrupted'" in query
    )
    assert "UPDATE ops.run_task task SET status='interrupted'" in interruption
    assert "UPDATE ops.ingestion_run run SET status='interrupted'" in interruption
    assert "task.lease_expires_at<=%s" in interruption
    assert "run.cancel_requested_at IS NULL" in interruption
    assert connection.committed is True


def test_queued_cancellation_is_immediately_terminal_and_cancels_pending_tasks() -> None:
    run_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            {"id": run_id, "status": "queued"},
            {"id": run_id, "status": "queued"},
            None,
            None,
            {"count": 0},
            {
                "id": run_id,
                "status": "cancelled",
                "run_mode": "full_refresh",
                "parent_run_id": None,
            },
        ]
    )

    run = ConnectedStore(connection).request_cancel(run_id)

    assert run["status"] == "cancelled"
    assert run["execution_semantics"] == "new_pipeline_run"
    assert "FOR UPDATE" not in connection.queries[0]
    assert "cancel_requested_at=COALESCE" in connection.queries[1]
    assert "version=" not in connection.queries[1]
    task_update = connection.queries[2]
    assert "status IN ('pending','retry_wait')" in task_update
    assert "SET status='cancelled'" in task_update
    run_update_parameters = connection.parameters[5]
    assert run_update_parameters is not None
    assert run_update_parameters[4] is True


def test_cancel_retry_replays_the_durable_cancelled_outcome() -> None:
    run_id = uuid.uuid4()
    cancelled_at = datetime.now(UTC)
    connection = ScriptedConnection(
        [
            {
                "id": run_id,
                "status": "cancelled",
                "cancel_requested_at": cancelled_at,
                "run_mode": "full_refresh",
                "parent_run_id": None,
            },
            None,
            None,
            {"count": 0},
            {
                "id": run_id,
                "status": "cancelled",
                "cancel_requested_at": cancelled_at,
                "run_mode": "full_refresh",
                "parent_run_id": None,
            },
        ]
    )

    run = ConnectedStore(connection).request_cancel(run_id)

    assert run["status"] == "cancelled"
    assert run["cancel_requested_at"] == cancelled_at.isoformat()
    assert len(connection.queries) == 5
    release_cleanup = connection.queries[4]
    assert "UPDATE ops.dataset_release SET status='abandoned'" in release_cleanup
    assert "status IN ('draft','candidate')" in release_cleanup


def test_cancel_retry_reconciles_cleanup_failure_after_intent_commit() -> None:
    class CleanupFailureConnection(ScriptedConnection):
        def execute(
            self, query: str, parameters: Sequence[object] | None = None
        ) -> ScriptedConnection:
            if "UPDATE ops.run_task SET status='cancelled'" in query:
                raise RuntimeError("simulated cleanup crash")
            return super().execute(query, parameters)

    run_id = uuid.uuid4()
    cancelled_at = datetime.now(UTC)
    first = CleanupFailureConnection(
        [
            {"id": run_id, "status": "staging", "cancel_requested_at": None},
            {"id": run_id, "status": "staging", "cancel_requested_at": cancelled_at},
        ]
    )
    with pytest.raises(RuntimeError, match="simulated cleanup crash"):
        ConnectedStore(first).request_cancel(run_id)
    assert first.commit_count == 1
    assert "cancel_requested_at=COALESCE" in first.queries[1]

    retry = ScriptedConnection(
        [
            {"id": run_id, "status": "staging", "cancel_requested_at": cancelled_at},
            {"id": run_id, "status": "staging", "cancel_requested_at": cancelled_at},
            None,
            None,
            {"count": 0},
            {
                "id": run_id,
                "status": "cancelled",
                "cancel_requested_at": cancelled_at,
                "run_mode": "full_refresh",
                "parent_run_id": None,
            },
        ]
    )
    reconciled = ConnectedStore(retry).request_cancel(run_id)
    assert reconciled["status"] == "cancelled"
    assert "UPDATE ops.dataset_release SET status='abandoned'" in retry.queries[5]


def test_active_cancellation_remains_cooperative_until_the_lease_finishes() -> None:
    run_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            {"id": run_id, "status": "acquiring"},
            {"id": run_id, "status": "acquiring"},
            None,
            None,
            {"count": 1},
            {
                "id": run_id,
                "status": "acquiring",
                "run_mode": "full_refresh",
                "parent_run_id": None,
            },
        ]
    )

    run = ConnectedStore(connection).request_cancel(run_id)

    assert run["status"] == "acquiring"
    assert "FOR UPDATE" not in connection.queries[0]
    assert connection.commit_count == 2
    run_update_parameters = connection.parameters[5]
    assert run_update_parameters is not None
    assert run_update_parameters[4] is False


def test_active_cancellation_is_acknowledged_by_the_next_task_heartbeat() -> None:
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            {
                "id": task_id,
                "ingestion_run_id": run_id,
                "status": "cancelled",
            },
            None,
            None,
            None,
        ]
    )

    task = ConnectedStore(connection).heartbeat_task(
        task_id,
        worker_id="runner-1",
        lease_token="lease-token",
        lease_seconds=300,
    )

    assert task["status"] == "cancelled"
    heartbeat = connection.queries[0]
    assert "run.cancel_requested_at IS NOT NULL" in heartbeat
    assert "RETURNING task.*" in heartbeat
    assert "status IN ('pending','retry_wait')" in connection.queries[1]
    assert "UPDATE ops.dataset_release SET status='abandoned'" in connection.queries[2]
    assert "status IN ('draft','candidate')" in connection.queries[2]
    assert "UPDATE ops.ingestion_run SET status='cancelled'" in connection.queries[3]
    assert connection.committed is True


def test_task_finish_after_persisted_cancel_abandons_only_the_candidate() -> None:
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            {
                "id": task_id,
                "ingestion_run_id": run_id,
                "stage": "import",
                "status": "succeeded",
            },
            {"cancel_requested_at": datetime.now(UTC)},
            None,
            None,
            None,
        ]
    )

    ConnectedStore(connection).complete_task(
        task_id,
        worker_id="runner-1",
        lease_token="lease-1",
        rows_in=10,
        rows_out=10,
    )

    release_cleanup = connection.queries[3]
    assert "UPDATE ops.dataset_release SET status='abandoned'" in release_cleanup
    assert "status IN ('draft','candidate')" in release_cleanup
    assert "accepted" not in release_cleanup
    assert "UPDATE ops.ingestion_run SET status='cancelled'" in connection.queries[4]


def test_resume_requeues_cancelled_unfinished_task_from_interrupted_run() -> None:
    run_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            None,
            {"id": run_id, "status": "queued", "run_mode": "full_refresh", "parent_run_id": None},
        ]
    )
    store = ConnectedStore(connection)
    store.get_run = lambda run_id: {  # type: ignore[method-assign]
        "id": str(run_id),
        "status": "interrupted",
        "run_mode": "full_refresh",
        "parent_run_id": None,
        "requested_scope_json": {"profile": "full-data", "all_records": True},
    }

    run = store.resume_run(run_id)

    assert run["status"] == "queued"
    assert "'cancelled'" in connection.queries[0]
    assert "'interrupted'" in connection.queries[0]


def test_run_projection_truthfully_describes_retry_execution() -> None:
    assert (
        project_run({"parent_run_id": None, "run_mode": "full_refresh"})["execution_semantics"]
        == "new_pipeline_run"
    )
    assert (
        project_run({"parent_run_id": uuid.uuid4(), "run_mode": "full_refresh"})[
            "execution_semantics"
        ]
        == "full_pipeline_retry"
    )
    assert (
        project_run({"parent_run_id": uuid.uuid4(), "run_mode": "reprocess_cached"})[
            "execution_semantics"
        ]
        == "cached_artifact_reprocess"
    )


def test_terminal_run_counts_rows_once_from_the_import_stage() -> None:
    run_id = uuid.uuid4()
    task_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            {
                "id": task_id,
                "ingestion_run_id": run_id,
                "stage": "build_release",
                "status": "succeeded",
            },
            {"cancel_requested_at": None},
            {"count": 0},
            None,
        ]
    )

    ConnectedStore(connection).complete_task(
        task_id,
        worker_id="runner-1",
        lease_token="lease-1",
        rows_in=1,
        rows_out=1,
    )

    terminal_update = connection.queries[3]
    assert "stage='acquire'" in terminal_update
    assert "stage='import'" in terminal_update
    assert "sum(rows_out)" not in terminal_update


class ArtifactStore(PropertyScopeStore):
    def __init__(self, existing: dict[str, Any] | None) -> None:
        self.existing = existing
        self.query = ""
        self.parameters: Sequence[Any] = ()

    def _fetch_one(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
        self.query = " ".join(query.split())
        self.parameters = params
        return self.existing


def test_artifact_replay_is_scoped_to_run_lineage() -> None:
    run_id = uuid.uuid4()
    existing = {
        "id": uuid.uuid4(),
        "content_sha256": "a" * 64,
        "storage_key": f"sha256/{'a' * 64}",
        "media_type": "application/json",
        "bytes": 100,
    }
    store = ArtifactStore(existing)

    artifact, created = store.register_artifact(
        {
            "ingestion_run_id": run_id,
            "logical_key": "01/acquire",
            "artifact_kind": "canonical_import",
            "content_sha256": "a" * 64,
            "storage_key": f"sha256/{'a' * 64}",
            "media_type": "application/json",
            "bytes": 100,
        }
    )

    assert created is False
    assert artifact == existing
    assert "ingestion_run_id=%s" in store.query
    assert store.parameters == (run_id, "01/acquire", "canonical_import")


def test_artifact_lineage_replay_rejects_changed_payload() -> None:
    store = ArtifactStore(
        {
            "content_sha256": "a" * 64,
            "storage_key": f"sha256/{'a' * 64}",
            "media_type": "application/json",
            "bytes": 100,
        }
    )

    with pytest.raises(ConflictError, match="artifact idempotency"):
        store.register_artifact(
            {
                "ingestion_run_id": uuid.uuid4(),
                "logical_key": "01/acquire",
                "artifact_kind": "canonical_import",
                "content_sha256": "b" * 64,
                "storage_key": f"sha256/{'b' * 64}",
                "media_type": "application/json",
                "bytes": 100,
            }
        )


def test_source_snapshot_registration_persists_publisher_release_context() -> None:
    run_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            None,
            {"id": artifact_id, "artifact_kind": "source_snapshot"},
            None,
        ]
    )
    snapshot = {
        "schema_version": "propertyscope.source-snapshot.v1",
        "source_release": "psi-year-2025",
        "objects": [{"logical_key": "psi-year-2025"}],
    }

    artifact, created = ConnectedStore(connection).register_artifact(
        {
            "ingestion_run_id": run_id,
            "run_task_id": uuid.uuid4(),
            "logical_key": "00/discover",
            "artifact_kind": "source_snapshot",
            "storage_key": f"sha256/{'a' * 64}",
            "content_sha256": "a" * 64,
            "media_type": "application/json",
            "bytes": 100,
            "schema_version": "propertyscope.source-snapshot.v1",
            "retention_class": "candidate",
            "source_snapshot": snapshot,
        }
    )

    assert created is True
    assert artifact["id"] == str(artifact_id)
    snapshot_update = next(query for query in connection.queries if "source_snapshot_json" in query)
    assert "UPDATE ops.ingestion_run" in snapshot_update


class SearchStore:
    def __init__(self) -> None:
        self.query_text: str | None = None

    def list_sources(
        self, *, status: str | None, query_text: str | None, limit: int, offset: int
    ) -> list[dict[str, Any]]:
        del status, limit, offset
        self.query_text = query_text
        return []


def test_source_collection_forwards_trimmed_search_query() -> None:
    store = SearchStore()
    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(cast(PropertyScopeStore, store), internal_token="secret")
    )
    register_error_handlers(app)

    response = app.test_client().get(
        "/internal/data-platform/v1/sources?q=%20schools%20",
        headers={"X-PropertyScope-Internal-Token": "secret"},
    )

    assert response.status_code == 200
    assert store.query_text == "schools"


def test_collection_rejects_unbounded_search_query() -> None:
    store = SearchStore()
    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(cast(PropertyScopeStore, store), internal_token="secret")
    )
    register_error_handlers(app)

    response = app.test_client().get(
        f"/internal/data-platform/v1/sources?q={'x' * 201}",
        headers={"X-PropertyScope-Internal-Token": "secret"},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "invalid_request"


class PropertyQueryStore(PropertyScopeStore):
    def __init__(self) -> None:
        self.query = ""
        self.params: Sequence[Any] = ()

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        self.query = " ".join(query.split())
        self.params = params
        return []


def test_property_search_requires_an_accepted_identity_generation() -> None:
    store = PropertyQueryStore()

    results = store.search_properties("11 example street", state="NSW", limit=25)

    assert results.items == []
    assert results.total == 0
    assert "accepted_addresses AS MATERIALIZED" in store.query
    assert "FROM warehouse.gnaf_address address" in store.query
    assert "accepted.dataset_release_id=address.dataset_release_id" in store.query
    assert "COALESCE(address.property_ref, md5('propertyscope-gnaf:'" in store.query
    assert "registry.address_alias alias" in store.query
    assert "lower(address.address_display)" in store.query
    assert "LIKE '%%' || %s || '%%'" in store.query
    assert "word_similarity(%s,document.search_text)" in store.query
    assert "CASE WHEN match_kind='canonical' THEN 0 ELSE 1 END" in store.query
    assert "document.search_text %% %s" not in store.query
    assert "count(*) OVER ()" not in store.query
    assert store.params[-2] == 25
    assert store.query.count("%s") == len(store.params)


def test_property_search_bounds_worst_case_documents_before_scoring() -> None:
    store = PropertyQueryStore()

    store.search_properties("parramatta", state="NSW", limit=25)

    assert "search_documents AS MATERIALIZED" in store.query
    assert "SELECT * FROM search_documents LIMIT %s" in store.query
    assert store.query.index("candidate_documents AS") < store.query.index("candidates AS")
    assert store.params.count(PROPERTY_SEARCH_CANDIDATE_LIMIT + 1) == 2
    assert store.params.count(PROPERTY_SEARCH_CANDIDATE_LIMIT) == 2


def test_property_search_excludes_legacy_rows_owned_by_the_accepted_warehouse() -> None:
    store = PropertyQueryStore()

    store.search_properties("parramatta", state="NSW", limit=25)

    assert store.query.count("FROM warehouse.gnaf_address accepted_address") == 2
    assert store.query.count("accepted_address.gnaf_pid)::uuid) =property.property_ref") == 2
    assert store.query.count("accepted.dataset_release_id=accepted_address.dataset_release_id") == 2


def test_property_search_reports_an_honest_bounded_total_without_full_count() -> None:
    class BoundedSearchStore(PropertyQueryStore):
        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            super()._fetch_all(query, params)
            return [
                {
                    "property_ref": str(uuid.uuid4()),
                    "total_count": PROPERTY_SEARCH_CANDIDATE_LIMIT,
                    "total_is_lower_bound": True,
                }
                for _ in range(25)
            ]

    results = BoundedSearchStore().search_properties("parramatta", state="NSW", limit=25, offset=50)

    assert len(results.items) == 25
    assert results.total == PROPERTY_SEARCH_CANDIDATE_LIMIT
    assert results.total_is_lower_bound is True


def test_property_search_out_of_range_offset_retains_the_bounded_total() -> None:
    class OutOfRangeSearchStore(PropertyQueryStore):
        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            super()._fetch_all(query, params)
            return [
                {
                    "property_ref": None,
                    "total_count": 17,
                    "total_is_lower_bound": False,
                }
            ]

    results = OutOfRangeSearchStore().search_properties(
        "parramatta", state="NSW", limit=25, offset=1_000_000
    )

    assert results.items == []
    assert results.total == 17
    assert results.total_is_lower_bound is False


def test_property_search_normalises_display_punctuation() -> None:
    assert (
        _normalise_property_query("  Unit 5/15 Example St., Wollongong NSW 2500 ")
        == "unit 5 15 example st wollongong nsw 2500"
    )


def test_property_search_does_not_broaden_punctuation_only_input() -> None:
    store = PropertyQueryStore()

    results = store.search_properties("--", state="NSW", limit=25)

    assert results.items == []
    assert results.total == 0
    assert store.query == ""


@pytest.mark.parametrize("query", ["street", "NSW", "street nsw", "road", "Sydney", "Sydney NSW"])
def test_property_search_rejects_underspecified_common_queries(query: str) -> None:
    store = PropertyQueryStore()

    with pytest.raises(ValidationError, match="street number, postcode, locality"):
        store.search_properties(query, state="NSW", limit=25)

    assert store.query == ""


@pytest.mark.parametrize("query", ["2000", "Parramatta", "11 Example Street"])
def test_property_search_accepts_selective_property_queries(query: str) -> None:
    store = PropertyQueryStore()

    store.search_properties(query, state="NSW", limit=25)

    assert store.query


def test_property_search_uses_structured_columns_for_short_numeric_queries() -> None:
    store = PropertyQueryStore()

    store.search_properties("11", state="NSW", limit=25)

    assert "address.street_number_first=%s" in store.query
    assert "property.street_number_first=%s" in store.query
    assert "alias.is_current AND FALSE" in store.query
    assert "AND trim(regexp_replace(lower(address.address_display)" not in store.query
    assert store.params[0] == 11
    assert store.params[2] == 11
    assert store.query.count("%s") == len(store.params)


def test_property_search_uses_structured_columns_for_postcodes() -> None:
    store = PropertyQueryStore()

    store.search_properties("2000", state="NSW", limit=25)

    assert "address.postcode=%s" in store.query
    assert "property.postcode=%s" in store.query
    assert store.params[0] == "2000"
    assert store.params[2] == "2000"


def test_locality_summary_uses_one_accepted_generation_and_opt_in_street_grouping() -> None:
    release_id = uuid.uuid4()

    class LocalityStore(PropertyQueryStore):
        def __init__(self) -> None:
            super().__init__()
            self.queries: list[str] = []

        def _fetch_one(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
            self.queries.append(" ".join(query.split()))
            return {
                "dataset_release_id": release_id,
                "dataset_id": "gnaf-nsw",
                "release_version": "2026.08.31",
                "schema_version": "propertyscope.property-snapshot.v2",
                "accepted_at": datetime(2026, 8, 31, tzinfo=UTC),
                "total": 42,
                "with_unit_number": 12,
                "min_latitude": -34.1,
                "max_latitude": -34.0,
                "min_longitude": 151.0,
                "max_longitude": 151.1,
            }

        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            self.queries.append(" ".join(query.split()))
            self.params = params
            return [{"street_name": "EXAMPLE", "address_count": 9}]

    store = LocalityStore()
    result = store.locality_summary(locality=" sutherland ", postcode="2232", include_streets=True)

    assert result["availability"]["status"] == "available"
    assert result["total_registered_addresses"] == 42
    assert result["unit_number_summary"] == {
        "with_unit_number": 12,
        "without_unit_number": 30,
    }
    assert result["scope"] == {"locality": "SUTHERLAND", "postcode": "2232", "state": "NSW"}
    assert result["top_streets"] == [{"street_name": "EXAMPLE", "address_count": 9}]
    assert len(store.queries) == 2
    assert "serving.accepted_generation" in store.queries[0]
    assert "%s::text IS NULL OR address.locality=%s" in store.queries[0]
    assert "%s::text IS NULL OR address.postcode=%s" in store.queries[0]
    assert "GROUP BY street_name" in store.queries[1]
    assert "%s::text IS NULL OR locality=%s" in store.queries[1]
    assert "%s::text IS NULL OR postcode=%s" in store.queries[1]


def test_locality_summary_reports_missing_accepted_generation_without_street_scan() -> None:
    class UnavailableLocalityStore(PropertyQueryStore):
        def _fetch_one(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
            self.query = " ".join(query.split())
            self.params = params
            return None

    result = UnavailableLocalityStore().locality_summary(
        locality=None, postcode="2000", include_streets=True
    )

    assert result["availability"]["status"] == "dataset_unavailable"
    assert result["total_registered_addresses"] == 0
    assert result["top_streets"] == []


def test_property_sale_history_is_bounded_to_latest_revisions_in_accepted_generation() -> None:
    release_id = uuid.uuid4()

    class SaleHistoryStore(PropertyQueryStore):
        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            super()._fetch_all(query, params)
            base = {
                "present": True,
                "dataset_release_id": release_id,
                "release_version": "2026.08.31",
                "schema_version": "propertyscope.property-sales.v3",
                "accepted_at": datetime(2026, 8, 31, tzinfo=UTC),
                "contract_date": "2026-01-01",
                "settlement_date": "2026-02-01",
                "price_aud": 900_000,
            }
            return [
                {**base, "source_business_key": f"sale-{index}", "source_revision": 2}
                for index in range(3)
            ]

    store = SaleHistoryStore()
    property_ref = uuid.uuid4()
    result = store.property_sale_history(property_ref, limit=2)

    assert result["count"] == 2
    assert result["has_more"] is True
    assert result["supported"] is True
    assert result["availability"]["status"] == "available"
    assert result["release"]["dataset_release_id"] == release_id
    assert "accepted.dataset_id='nsw-psi-sales'" in store.query
    assert "accepted.target_feature='feature-2'" in store.query
    assert "DISTINCT ON (sale.source_business_key)" in store.query
    assert "sale.source_revision DESC" in store.query
    assert "sale.dataset_release_id=accepted.dataset_release_id" in store.query
    assert store.params == (property_ref, property_ref, property_ref, 3)


def test_property_sale_history_reports_unsupported_without_scanning_other_generations() -> None:
    class UnsupportedHistoryStore(PropertyQueryStore):
        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            super()._fetch_all(query, params)
            return [
                {
                    "present": True,
                    "dataset_release_id": None,
                    "release_version": None,
                    "schema_version": None,
                    "accepted_at": None,
                    "source_business_key": None,
                }
            ]

    result = UnsupportedHistoryStore().property_sale_history(uuid.uuid4(), limit=50)

    assert result == {
        "items": [],
        "count": 0,
        "limit": 50,
        "has_more": False,
        "supported": False,
        "availability": {
            "status": "dataset_unavailable",
            "reason": "No accepted NSW PSI generation is available.",
            "accepted_release_id": None,
        },
        "release": None,
    }


def test_property_sale_history_distinguishes_an_incompatible_accepted_contract() -> None:
    pointer_id = uuid.uuid4()

    class IncompatibleHistoryStore(PropertyQueryStore):
        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            super()._fetch_all(query, params)
            return [
                {
                    "present": True,
                    "pointer_release_id": pointer_id,
                    "pointer_schema_version": "propertyscope.fixture.v1",
                    "dataset_release_id": None,
                    "release_version": None,
                    "schema_version": None,
                    "accepted_at": None,
                    "source_business_key": None,
                }
            ]

    result = IncompatibleHistoryStore().property_sale_history(uuid.uuid4(), limit=50)

    assert result["availability"] == {
        "status": "unsupported_contract",
        "reason": "The accepted NSW PSI generation uses an unsupported schema.",
        "accepted_release_id": pointer_id,
    }
    assert result["items"] == []


def test_property_seifa_uses_only_the_accepted_release_and_exact_nsw_locality() -> None:
    release_id = uuid.uuid4()
    property_ref = uuid.uuid4()

    class SeifaStore(PropertyQueryStore):
        def __init__(self) -> None:
            super().__init__()
            self.queries: list[str] = []

        def _fetch_one(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
            normalised = " ".join(query.split())
            self.queries.append(normalised)
            if "SELECT address.locality" in normalised:
                assert params == (property_ref, property_ref)
                return {"locality": " Abbotsford "}
            assert params == ()
            return {
                "dataset_release_id": release_id,
                "release_version": "2021",
                "schema_version": "propertyscope.seifa-area.v1",
                "accepted_at": datetime(2026, 9, 2, tzinfo=UTC),
                "activated_at": datetime(2026, 9, 2, tzinfo=UTC),
                "source_name": "ABS SEIFA 2021",
                "publisher": "Australian Bureau of Statistics",
                "source_url": "https://www.abs.gov.au/",
                "licence_id": "cc-by-4.0",
                "licence_url": "https://www.abs.gov.au/website-privacy-copyright-and-disclaimer",
            }

        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            self.queries.append(" ".join(query.split()))
            assert params == (release_id, "ABBOTSFORD")
            return [
                {
                    "sal_code": "10003",
                    "sal_name": "Abbotsford (NSW)",
                    "locality_name": "ABBOTSFORD",
                    "state": "NSW",
                    "reference_year": 2021,
                    "irsd_score": "1062.49",
                    "irsd_australia_decile": 9,
                    "irsad_score": "1108.08",
                    "irsad_australia_decile": 10,
                    "ier_score": "1013.12",
                    "ier_australia_decile": 5,
                    "ieo_score": "1120.99",
                    "ieo_australia_decile": 10,
                    "usual_resident_population": 5431,
                }
            ]

    result = SeifaStore().property_seifa(property_ref)

    assert result["supported"] is True
    assert result["area"]["sal_code"] == "10003"
    assert result["area"]["irsad_australia_decile"] == 10
    assert result["attribution"] == "Based on Australian Bureau of Statistics data"
    assert result["match_method"] == "exact-normalised-locality-and-state"


def test_property_seifa_reports_when_no_compatible_release_is_accepted() -> None:
    property_ref = uuid.uuid4()

    class UnavailableSeifaStore(PropertyQueryStore):
        def _fetch_one(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
            if "SELECT address.locality" in query:
                return {"locality": "Sydney"}
            self.query = " ".join(query.split())
            return None

    store = UnavailableSeifaStore()
    result = store.property_seifa(property_ref)

    assert result["supported"] is False
    assert result["availability"] == "no_accepted_release"
    assert "serving.accepted_generation" in store.query


class PropertySearchApiStore:
    def __init__(self) -> None:
        self.page: tuple[str, int, int] | None = None

    def search_properties(
        self, query: str, *, state: str, limit: int, offset: int = 0
    ) -> PropertySearchResults:
        self.page = (query, limit, offset)
        return PropertySearchResults(
            items=[
                {
                    "property_ref": str(uuid.uuid4()),
                    "address_display": "11 Example Street, Sydney NSW 2000",
                }
            ],
            total=3,
        )

    def property_sale_history(self, property_ref: uuid.UUID, *, limit: int) -> dict[str, Any]:
        return {
            "items": [{"source_business_key": "sale-1"}],
            "count": 1,
            "limit": limit,
            "has_more": False,
            "supported": True,
            "availability": {
                "status": "available",
                "reason": "Accepted sale history is available.",
                "accepted_release_id": str(uuid.uuid4()),
            },
            "release": {"dataset_release_id": str(uuid.uuid4())},
        }

    def property_seifa(self, property_ref: uuid.UUID) -> dict[str, Any]:
        return {
            "supported": True,
            "availability": "available",
            "property_ref": str(property_ref),
            "area": {"sal_code": "10003", "irsad_australia_decile": 10},
        }


def test_property_search_api_returns_stable_pagination_metadata() -> None:
    store = PropertySearchApiStore()
    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(cast(PropertyScopeStore, store), internal_token="secret")
    )
    register_error_handlers(app)

    response = app.test_client().get(
        "/internal/data-platform/v1/properties/search?q=Example&limit=1&offset=2",
        headers={"X-PropertyScope-Internal-Token": "secret"},
    )

    assert response.status_code == 200
    assert store.page == ("Example", 1, 2)
    assert response.get_json() == {
        "items": response.get_json()["items"],
        "count": 1,
        "total": 3,
        "total_is_lower_bound": False,
        "limit": 1,
        "offset": 2,
        "next_offset": None,
        "query": "Example",
        "supported": True,
    }


def test_property_sale_history_api_applies_its_small_read_bound() -> None:
    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(
            cast(PropertyScopeStore, PropertySearchApiStore()), internal_token="secret"
        )
    )
    register_error_handlers(app)

    response = app.test_client().get(
        f"/internal/data-platform/v1/properties/{uuid.uuid4()}/sale-history?limit=7",
        headers={"X-PropertyScope-Internal-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.get_json()["limit"] == 7
    assert response.get_json()["count"] == 1


def test_property_seifa_api_returns_the_area_evidence() -> None:
    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(
            cast(PropertyScopeStore, PropertySearchApiStore()), internal_token="secret"
        )
    )
    register_error_handlers(app)

    response = app.test_client().get(
        f"/internal/data-platform/v1/properties/{uuid.uuid4()}/seifa",
        headers={"X-PropertyScope-Internal-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.get_json()["area"] == {
        "sal_code": "10003",
        "irsad_australia_decile": 10,
    }


def test_property_search_api_does_not_inflate_total_for_out_of_range_offset() -> None:
    class OutOfRangeApiStore(PropertySearchApiStore):
        def search_properties(
            self, query: str, *, state: str, limit: int, offset: int = 0
        ) -> PropertySearchResults:
            self.page = (query, limit, offset)
            return PropertySearchResults(items=[], total=17)

    store = OutOfRangeApiStore()
    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(cast(PropertyScopeStore, store), internal_token="secret")
    )
    register_error_handlers(app)

    response = app.test_client().get(
        "/internal/data-platform/v1/properties/search?q=Example&limit=25&offset=1000",
        headers={"X-PropertyScope-Internal-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.get_json()["items"] == []
    assert response.get_json()["total"] == 17
    assert response.get_json()["total_is_lower_bound"] is False
    assert response.get_json()["next_offset"] is None


def test_release_collection_excludes_retired_assessment_sources() -> None:
    store = PropertyQueryStore()

    store.list_releases(status="accepted", limit=100, offset=0)

    assert "JOIN ops.source_definition source" in store.query
    assert "source.status<>'retired'" in store.query
    assert "release.status=%s" in store.query


class PreviewStore(PropertyScopeStore):
    def __init__(self) -> None:
        self.required_calls = 0
        self.preview_query = ""
        self.preview_parameters: Sequence[Any] = ()

    def _required(self, query: str, params: Sequence[Any]) -> dict[str, Any]:
        del query, params
        self.required_calls += 1
        if self.required_calls == 1:
            return {
                "id": str(uuid.uuid4()),
                "dataset_id": "nsw-government-schools",
                "release_version": "2026-08",
                "status": "candidate",
                "record_count": 2210,
                "import_profile_key": "schools-master",
            }
        return {"count": 2210}

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        self.preview_query = " ".join(query.split())
        self.preview_parameters = params
        return [{"school_code": "1001", "school_name": "Example Public School"}]


def test_release_preview_uses_fixed_profile_projection_and_bounds() -> None:
    release_id = uuid.uuid4()
    store = PreviewStore()

    preview = store.preview_release_records(release_id, limit=25, offset=50)

    assert "FROM warehouse.school" in store.preview_query
    assert "dataset_release_id=%s" in store.preview_query
    assert store.preview_parameters == (release_id, 25, 50)
    assert preview["profile"] == "schools-master"
    assert preview["total"] == 2210
    assert preview["next_offset"] == 51


def test_gnaf_preview_derives_stable_property_ref_without_warehouse_rewrite() -> None:
    assert "COALESCE(property_ref,md5('propertyscope-gnaf:' || gnaf_pid)::uuid)" in " ".join(
        PROPERTY_RECORD_SPEC.select_sql.split()
    )


class ScopedPsiPreviewStore(PropertyScopeStore):
    def __init__(self, release_id: uuid.UUID) -> None:
        self.release_id = release_id
        self.required_calls = 0
        self.select_query = ""
        self.select_parameters: Sequence[Any] = ()
        self.count_parameters: Sequence[Any] = ()

    def _required(self, query: str, params: Sequence[Any]) -> dict[str, Any]:
        self.required_calls += 1
        if self.required_calls == 1:
            return {
                "id": str(self.release_id),
                "dataset_id": "nsw-psi-sales",
                "release_version": "release-example",
                "status": "candidate",
                "record_count": 237_349,
                "coverage_json": {"release_scope": {"years": [2025], "maximum_records": 250_000}},
                "import_profile_key": "psi-sales",
            }
        self.count_parameters = params
        return {"count": 237_349}

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        self.select_query = " ".join(query.split())
        self.select_parameters = params
        return [
            {
                "source_business_key": "001:P1:1",
                "source_revision": 1,
                "source_era": "post-2001",
                "source_row_sha256": "a" * 64,
            }
        ]


def test_release_preview_uses_the_same_registered_psi_scope_as_the_export() -> None:
    release_id = uuid.uuid4()
    store = ScopedPsiPreviewStore(release_id)

    preview = store.preview_release_records(release_id, limit=25, offset=0)

    assert "source_partition_year=ANY(%s)" in store.select_query
    assert store.select_parameters == (release_id, [2025], 25, 0)
    assert store.count_parameters == (release_id, [2025])
    assert preview["total"] == 237_349
    assert preview["items"] == [
        {
            "source_business_key": "001:P1:1",
            "source_revision": 1,
            "source_era": "post-2001",
        }
    ]


class SalesSourceStore(PropertyScopeStore):
    def __init__(self, release_id: uuid.UUID) -> None:
        self.release_id = release_id
        self.required_calls = 0
        self.select_query = ""
        self.select_parameters: Sequence[Any] = ()

    def _required(self, query: str, params: Sequence[Any]) -> dict[str, Any]:
        del query, params
        self.required_calls += 1
        if self.required_calls == 1:
            return {
                "id": str(self.release_id),
                "dataset_id": "nsw-psi-sales",
                "release_version": "2026-08",
                "status": "accepted",
                "schema_version": "propertyscope.property-sales.v2",
                "import_profile_key": "psi-sales",
            }
        return {"count": 12_345}

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        self.select_query = " ".join(query.split())
        self.select_parameters = params
        return [{"source_business_key": "001:P1:1", "source_revision": 1}]


def test_sales_source_feed_pages_complete_accepted_generation_by_year() -> None:
    release_id = uuid.uuid4()
    store = SalesSourceStore(release_id)

    page = store.release_sales_source_records(release_id, year=1999, limit=1000, offset=2000)

    assert "FROM warehouse.psi_sale" in store.select_query
    assert "source_partition_year=%s" in store.select_query
    assert "property_id AS source_property_id" in store.select_query
    assert store.select_parameters == (release_id, 1999, 1000, 2000)
    assert page["schema_version"] == "propertyscope.psi-source-records.v1"
    assert page["total"] == 12_345
    assert page["next_offset"] == 2001


def test_release_export_binding_is_atomic_and_requires_matching_evidence() -> None:
    release_id = uuid.uuid4()
    run_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    digest = "a" * 64
    manifest = {
        "release_id": str(release_id),
        "product_schema_version": "propertyscope.school-points.v1",
        "content_sha256": digest,
        "record_count": 2,
        "byte_count": 400,
    }
    updated = {
        "id": release_id,
        "status": "candidate",
        "schema_version": "propertyscope.school-points.v1",
        "content_sha256": digest,
        "record_count": 2,
        "artifact_record_id": artifact_id,
        "manifest_json": manifest,
    }
    connection = ScriptedConnection(
        [
            {"id": release_id, "status": "draft", "ingestion_run_id": run_id},
            {
                "id": artifact_id,
                "ingestion_run_id": run_id,
                "artifact_kind": "release_export",
                "schema_version": "propertyscope.school-points.v1",
                "content_sha256": digest,
                "bytes": 400,
            },
            {"total": 1, "passed": 1},
            updated,
        ]
    )

    result = ConnectedStore(connection).bind_release_export(
        release_id,
        {
            "artifact_record_id": artifact_id,
            "schema_version": "propertyscope.school-points.v1",
            "content_sha256": digest,
            "record_count": 2,
            "manifest": manifest,
        },
    )

    assert result["status"] == "candidate"
    assert connection.committed is True
    update = next(query for query in connection.queries if "status='candidate'" in query)
    assert "artifact_record_id=%s" in update
    assert "manifest_json=%s" in update


def test_candidate_export_replay_allows_new_clock_but_rejects_changed_evidence() -> None:
    release_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    digest = "b" * 64
    connection = ScriptedConnection(
        [
            {
                "id": release_id,
                "status": "candidate",
                "schema_version": "propertyscope.property-sales.v2",
                "content_sha256": digest,
                "record_count": 1,
                "artifact_record_id": artifact_id,
                "manifest_json": {
                    "created_at": "2026-08-16T00:00:00Z",
                    "source_release": "2025",
                },
            },
            {"id": artifact_id},
        ]
    )

    with pytest.raises(ConflictError, match="immutable evidence"):
        ConnectedStore(connection).bind_release_export(
            release_id,
            {
                "artifact_record_id": artifact_id,
                "schema_version": "propertyscope.property-sales.v2",
                "content_sha256": digest,
                "record_count": 1,
                "manifest": {
                    "created_at": "2026-08-17T00:00:00Z",
                    "source_release": "2026",
                },
            },
        )


def test_release_product_projection_is_bound_to_one_candidate_generation() -> None:
    release_id = uuid.uuid4()
    connection = ScriptedConnection([])

    class ProjectionStore(ConnectedStore):
        def _required(self, query: str, params: Sequence[Any]) -> dict[str, Any]:
            connection.queries.append(" ".join(query.split()))
            connection.parameters.append(params)
            if "ops.dataset_release" in query:
                return {
                    "id": release_id,
                    "coverage_json": {"years": [2025], "maximum_records": 250_000},
                    "import_profile_key": "psi-sales",
                }
            return {"count": 1}

        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            connection.queries.append(" ".join(query.split()))
            connection.parameters.append(params)
            return [{"source_business_key": "sale-1", "source_revision": 1}]

    page = ProjectionStore(connection).release_product_records(release_id, limit=25, cursor=None)

    assert page["release_id"] == str(release_id)
    assert page["candidate_generation_id"] == str(release_id)
    assert page["total"] == 1
    assert all(
        release_id in parameters for parameters in connection.parameters if parameters is not None
    )
    projection = next(query for query in connection.queries if "warehouse.psi_sale" in query)
    assert "dataset_release_id=%s" in projection
    assert "source_partition_year=ANY" not in projection
    assert "EXTRACT(YEAR FROM contract_date)" not in projection
    assert "ORDER BY source_business_key,source_revision" in projection


def test_bound_candidate_fields_are_not_publicly_mutable() -> None:
    release_id = uuid.uuid4()

    class CandidateStore(PropertyScopeStore):
        def __init__(self) -> None:
            pass

        def get_release(self, requested: uuid.UUID) -> dict[str, Any]:
            assert requested == release_id
            return {"id": str(release_id), "status": "candidate"}

    with pytest.raises(ConflictError, match="immutable"):
        CandidateStore().update_release(release_id, {"version": 1, "record_count": 999})


def test_public_release_creation_cannot_skip_governed_draft_state() -> None:
    store = PropertyScopeStore.__new__(PropertyScopeStore)
    with pytest.raises(ConflictError, match="drafts"):
        store.create_release({"status": "accepted"})


def test_source_licence_policy_is_immutable_after_release_evidence_exists() -> None:
    source_id = uuid.uuid4()
    current = {
        "id": str(source_id),
        "name": "Source",
        "publisher": "Publisher",
        "source_url": "https://example.invalid/source",
        "adapter_key": "fixture-property",
        "cadence": "fixture",
        "licence_id": "licence-v1",
        "licence_url": "https://example.invalid/licence",
        "redistribution_policy": "committed-synthetic-fixture",
        "target_features_json": ["feature-1"],
        "status": "active",
        "notes": None,
    }
    connection = ScriptedConnection([{"id": source_id}, {"id": uuid.uuid4()}])

    class SourceStore(ConnectedStore):
        def get_source(self, requested: uuid.UUID) -> dict[str, Any]:
            assert requested == source_id
            return current

    with pytest.raises(ConflictError, match="immutable"):
        SourceStore(connection).update_source(
            source_id,
            {"version": 1, "redistribution_policy": "metadata-only"},
        )


def test_publication_idempotency_key_cannot_be_reused_for_another_release() -> None:
    first_release = uuid.uuid4()
    second_release = uuid.uuid4()

    class ReceiptStore(PropertyScopeStore):
        def __init__(self) -> None:
            pass

        def get_release(self, release_id: uuid.UUID) -> dict[str, Any]:
            return {"id": str(release_id)}

        def _fetch_one(self, query: str, params: Sequence[Any]) -> dict[str, Any] | None:
            del query, params
            return {
                "dataset_release_id": first_release,
                "status": "accepted",
                "schema_version": "propertyscope.property-sales.v2",
                "content_sha256": "f" * 64,
                "rows_received": 1,
                "rows_accepted": 1,
                "rows_rejected": 0,
            }

    with pytest.raises(ConflictError, match="idempotency key arguments"):
        ReceiptStore().record_publication_receipt(
            second_release,
            {
                "target_feature": "feature-2",
                "consumer_operation_id": "same-operation-key",
                "status": "accepted",
                "schema_version": "propertyscope.property-sales.v2",
                "content_sha256": "f" * 64,
                "rows_received": 1,
                "rows_accepted": 1,
                "rows_rejected": 0,
                "request_id": "request-1",
            },
        )


def test_address_publication_does_not_rewrite_immutable_warehouse_generation() -> None:
    """A source-scale publish derives stable IDs without updating every warehouse row."""
    release_id = uuid.uuid4()
    connection = ScriptedConnection([None, None, None, None])

    ConnectedStore(connection)._publish_address_property_spine(
        cast(Any, connection),
        release_id,
        datetime(2026, 8, 26, tzinfo=UTC),
        identifier_scheme="gnaf_pid",
    )

    assert not any("UPDATE warehouse.gnaf_address" in query for query in connection.queries)
    property_upsert = next(
        query for query in connection.queries if "INSERT INTO registry.property" in query
    )
    identifier_upsert = next(
        query for query in connection.queries if "INSERT INTO registry.property_identifier" in query
    )
    coverage_upsert = next(
        query for query in connection.queries if "INSERT INTO serving.property_coverage" in query
    )
    assert "IS DISTINCT FROM" in property_upsert
    assert "WHERE NOT registry.property_identifier.is_current" in identifier_upsert
    assert "IS DISTINCT FROM" in coverage_upsert


def test_activation_queue_validates_receipt_without_switching_accepted_pointer() -> None:
    release_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            None,
            {
                "id": release_id,
                "status": "awaiting_review",
                "version": 4,
                "schema_version": "propertyscope.property-snapshot.v1",
                "content_sha256": "a" * 64,
                "record_count": 5_190_134,
                "receipt_id": receipt_id,
                "receipt_status": "accepted",
                "receipt_schema_version": "propertyscope.property-snapshot.v1",
                "receipt_content_sha256": "a" * 64,
                "rows_received": 5_190_134,
                "rows_accepted": 5_190_134,
                "rows_rejected": 0,
            },
            {"count": 0},
            None,
            {
                "id": operation_id,
                "dataset_release_id": release_id,
                "publication_receipt_id": receipt_id,
                "expected_release_version": 4,
                "review_comment": "Reviewed full source",
                "status": "queued",
            },
        ]
    )

    operation, created = ConnectedStore(connection).create_release_activation(
        release_id,
        {
            "publication_receipt_id": receipt_id,
            "expected_release_version": 4,
            "comment": "Reviewed full source",
            "idempotency_key": "publish-large-gnaf",
        },
    )

    assert created is True
    assert operation["status"] == "queued"
    assert not any("status='accepted'" in query for query in connection.queries)
    assert not any("serving.accepted_generation" in query for query in connection.queries)
    assert connection.committed is True


def test_activation_queue_rejects_partial_release_coverage() -> None:
    release_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            None,
            {
                "id": release_id,
                "status": "awaiting_review",
                "version": 4,
                "coverage_json": {"profile": "psi-year-range", "complete": False},
                "receipt_id": receipt_id,
            },
        ]
    )

    with pytest.raises(ConflictError, match="partial release"):
        ConnectedStore(connection).create_release_activation(
            release_id,
            {
                "publication_receipt_id": receipt_id,
                "expected_release_version": 4,
                "comment": "Reviewed partial source",
                "idempotency_key": "publish-partial-psi",
            },
        )

    assert not any("INSERT INTO ops.release_activation" in query for query in connection.queries)


def test_activation_queue_coalesces_a_second_nonterminal_release_version() -> None:
    release_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    existing_id = uuid.uuid4()
    evidence = {
        "id": release_id,
        "status": "awaiting_review",
        "version": 4,
        "schema_version": "propertyscope.property-snapshot.v1",
        "content_sha256": "a" * 64,
        "record_count": 5_190_134,
        "receipt_id": receipt_id,
        "receipt_status": "accepted",
        "receipt_schema_version": "propertyscope.property-snapshot.v1",
        "receipt_content_sha256": "a" * 64,
        "rows_received": 5_190_134,
        "rows_accepted": 5_190_134,
        "rows_rejected": 0,
    }
    pending = {
        "id": existing_id,
        "dataset_release_id": release_id,
        "publication_receipt_id": uuid.uuid4(),
        "expected_release_version": 4,
        "review_comment": "First review",
        "status": "running",
        "idempotency_key": "first-browser-request",
    }
    connection = ScriptedConnection([None, evidence, {"count": 0}, pending])

    operation, created = ConnectedStore(connection).create_release_activation(
        release_id,
        {
            "publication_receipt_id": receipt_id,
            "expected_release_version": 4,
            "comment": "Repeated review",
            "idempotency_key": "retry-after-timeout",
        },
    )

    assert created is False
    assert operation["id"] == str(existing_id)
    assert not any("INSERT INTO ops.release_activation" in query for query in connection.queries)


def test_activation_queue_recovers_winner_that_terminalises_after_unique_race() -> None:
    release_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    winner_id = uuid.uuid4()
    evidence = {
        "id": release_id,
        "status": "awaiting_review",
        "version": 4,
        "schema_version": "propertyscope.property-snapshot.v1",
        "content_sha256": "a" * 64,
        "record_count": 5_190_134,
        "receipt_id": receipt_id,
        "receipt_status": "accepted",
        "receipt_schema_version": "propertyscope.property-snapshot.v1",
        "receipt_content_sha256": "a" * 64,
        "rows_received": 5_190_134,
        "rows_accepted": 5_190_134,
        "rows_rejected": 0,
    }
    winner = {
        "id": winner_id,
        "dataset_release_id": release_id,
        "publication_receipt_id": receipt_id,
        "expected_release_version": 4,
        "review_comment": "Competing review",
        "status": "succeeded",
        "idempotency_key": "competing-request",
    }

    class UniqueRaceConnection(ScriptedConnection):
        def execute(
            self, query: str, parameters: Sequence[object] | None = None
        ) -> ScriptedConnection:
            if "INSERT INTO ops.release_activation" in query:
                self.queries.append(" ".join(query.split()))
                self.parameters.append(parameters)
                raise errors.UniqueViolation("competing activation")
            return super().execute(query, parameters)

    connection = UniqueRaceConnection([None, evidence, {"count": 0}, None, None, winner])

    operation, created = ConnectedStore(connection).create_release_activation(
        release_id,
        {
            "publication_receipt_id": receipt_id,
            "expected_release_version": 4,
            "comment": "Repeated review",
            "idempotency_key": "retry-after-race",
        },
    )

    assert created is False
    assert operation["id"] == str(winner_id)
    assert operation["status"] == "succeeded"
    fallback = connection.queries[-1]
    assert "status IN" not in fallback
    assert "ORDER BY requested_at DESC LIMIT 1" in fallback


@pytest.mark.parametrize(
    ("activation_status", "expected_http", "expected_outcome"),
    [
        ("queued", 202, "pending"),
        ("running", 202, "pending"),
        ("succeeded", 200, "completed"),
        ("failed", 409, None),
    ],
)
def test_activation_api_distinguishes_active_and_terminal_outcomes(
    activation_status: str,
    expected_http: int,
    expected_outcome: str | None,
) -> None:
    release_id = uuid.uuid4()
    operation_id = uuid.uuid4()

    class ActivationApiStore:
        def create_release_activation(
            self, requested_release_id: uuid.UUID, values: Mapping[str, Any]
        ) -> tuple[dict[str, Any], bool]:
            assert requested_release_id == release_id
            assert values["idempotency_key"] == "publication-key"
            return {"id": operation_id, "status": activation_status}, False

    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(cast(PropertyScopeStore, ActivationApiStore()), internal_token="secret")
    )
    register_error_handlers(app)

    response = app.test_client().post(
        f"/internal/data-platform/v1/releases/{release_id}/activations",
        headers={"X-PropertyScope-Internal-Token": "secret"},
        json={
            "publication_receipt_id": str(uuid.uuid4()),
            "expected_release_version": 4,
            "comment": "Reviewed",
            "idempotency_key": "publication-key",
        },
    )

    assert response.status_code == expected_http
    body = response.get_json()
    if activation_status == "failed":
        assert response.content_type == "application/problem+json"
        assert body["code"] == "release_activation_failed"
        assert "fresh request" in body["detail"]
    else:
        assert body["outcome"] == expected_outcome
        assert body["activation"]["status"] == activation_status


def test_activation_claim_recovers_expired_lease_with_bounded_attempts() -> None:
    operation_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            None,
            {
                "id": operation_id,
                "status": "claimed",
                "attempt_number": 2,
                "lease_owner": "loader-2",
                "lease_token": "new-token",
            },
        ]
    )

    claimed = ConnectedStore(connection).claim_release_activation(
        worker_id="loader-2", lease_seconds=120
    )

    assert claimed is not None and claimed["id"] == str(operation_id)
    retry_limit = connection.queries[0]
    claim = connection.queries[1]
    assert "attempt_number>=3" in retry_limit
    assert "lease_expires_at<=%s" in claim
    assert "attempt_number<3" in claim
    assert "FOR UPDATE SKIP LOCKED LIMIT 1" in claim


def test_import_claim_interrupts_expired_work_before_claiming_queued_work() -> None:
    operation_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            None,
            None,
            {
                "id": operation_id,
                "status": "claimed",
                "lease_owner": "loader-2",
                "lease_token": "new-token",
            },
        ]
    )

    claimed = ConnectedStore(connection).claim_import(worker_id="loader-2", lease_seconds=120)

    assert claimed is not None and claimed["id"] == str(operation_id)
    cancelled = connection.queries[0]
    assert "SET status='cancelled'" in cancelled
    assert "run.cancel_requested_at IS NOT NULL" in cancelled
    interruption = connection.queries[1]
    assert "UPDATE ops.import_operation operation SET status='interrupted'" in interruption
    assert "run.cancel_requested_at IS NULL" in interruption
    assert "operation.status IN ('claimed','running')" in interruption
    assert "operation.lease_expires_at<=%s" in interruption
    interruption_parameters = connection.parameters[1]
    assert interruption_parameters is not None
    assert "import_lease_expired" in str(interruption_parameters[0])
    claim = connection.queries[2]
    assert "WHERE status='queued'" in claim
    assert "FOR UPDATE SKIP LOCKED LIMIT 1" in claim
    assert connection.committed is True


def test_import_claim_terminalises_expired_work_for_a_cancelled_run() -> None:
    connection = ScriptedConnection([None, None, None])

    claimed = ConnectedStore(connection).claim_import(worker_id="loader-2", lease_seconds=120)

    assert claimed is None
    cancellation = connection.queries[0]
    assert "SET status='cancelled'" in cancellation
    assert "finished_at=%s" in cancellation
    assert "run.cancel_requested_at IS NOT NULL" in cancellation
    assert "space_recovery_status='needed'" in cancellation
    assert "measure_then_target_exact_relations" in cancellation
    assert "warehouse.psi_sale" in cancellation
    assert "warehouse.bocsar_observation" in cancellation
    assert "warehouse.bocsar_coverage" in cancellation
    assert (
        "operation.progress_phase_key IN ('target_materialisation','verification')" in cancellation
    )
    assert "false)" in cancellation
    assert "automatic_destructive_maintenance',false" in cancellation
    cancellation_parameters = connection.parameters[0]
    assert cancellation_parameters is not None
    assert "operator_cancelled" in str(cancellation_parameters[1])
    assert "WHERE status='queued'" in connection.queries[2]


@pytest.mark.parametrize(
    ("progress_phase_key", "destination_may_have_been_touched"),
    [("typed_staging", False), ("target_materialisation", True), ("verification", True)],
)
def test_cancelled_import_projects_bounded_relation_scoped_space_recovery(
    progress_phase_key: str, destination_may_have_been_touched: bool
) -> None:
    operation_id = uuid.uuid4()
    completed = {
        "id": operation_id,
        "status": "cancelled",
        "space_recovery_status": "needed",
    }
    connection = ScriptedConnection(
        [
            {
                "id": operation_id,
                "import_profile_key": "bocsar-sparse",
                "progress_phase_key": progress_phase_key,
            },
            completed,
        ]
    )

    result = ConnectedStore(connection).finish_import(
        operation_id,
        worker_id="loader-1",
        lease_token="lease-token",
        status="cancelled",
        counts={},
        result=None,
        error={"code": "operator_cancelled"},
    )

    assert result["space_recovery_status"] == "needed"
    update = connection.queries[1]
    assert "space_recovery_status=%s" in update
    assert "space_recovery_policy_json=%s" in update
    parameters = connection.parameters[1]
    assert parameters is not None
    policy = str(parameters[9])
    assert "warehouse.bocsar_observation" in policy
    assert "warehouse.bocsar_coverage" in policy
    assert "automatic_destructive_maintenance" in policy
    expected_flag = str(destination_may_have_been_touched).lower()
    assert f'"destination_may_have_been_touched":{expected_flag}' in policy


def test_interrupted_import_reenqueue_increments_attempt_once_and_replay_is_stable() -> None:
    operation_id = uuid.uuid4()
    resumed = ScriptedConnection([{"id": operation_id, "status": "queued", "attempt_number": 2}])

    operation = ConnectedStore(resumed).enqueue_import(operation_id)

    assert operation["attempt_number"] == 2
    assert "CASE WHEN status='interrupted'" in resumed.queries[0]
    assert "THEN attempt_number+1 ELSE attempt_number END" in resumed.queries[0]

    replay = ScriptedConnection(
        [None, {"id": operation_id, "status": "queued", "attempt_number": 2}]
    )
    replayed = ConnectedStore(replay).enqueue_import(operation_id)

    assert replayed["attempt_number"] == 2


def test_activation_state_trace_terminalises_an_interrupted_third_attempt() -> None:
    connection = ScriptedConnection([None, None])

    claimed = ConnectedStore(connection).claim_release_activation(
        worker_id="loader-4", lease_seconds=120
    )

    assert claimed is None
    terminalise = connection.queries[0]
    assert "UPDATE ops.release_activation SET status='failed'" in terminalise
    assert "status IN ('claimed','running','interrupted')" in terminalise
    assert "lease_expires_at IS NULL OR lease_expires_at<=%s" in terminalise
    assert "attempt_number>=3" in terminalise
    claim = connection.queries[1]
    assert "attempt_number<3" in claim
    assert connection.committed is True


def test_activation_final_pointer_transaction_contains_no_source_scale_dml() -> None:
    release_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    predecessor_id = uuid.uuid4()
    now = datetime.now(UTC)
    operation = {
        "id": operation_id,
        "dataset_release_id": release_id,
        "publication_receipt_id": uuid.uuid4(),
        "expected_release_version": 4,
        "review_comment": "Reviewed full source",
        "status": "running",
        "lease_owner": "loader-1",
        "lease_token": "token",
        "lease_expires_at": now + timedelta(minutes=2),
        "materialized_at": now,
        "dataset_id": "gnaf-nsw",
        "target_feature": "feature-1",
        "release_status": "awaiting_review",
        "release_version": 4,
        "receipt_status": "accepted",
        "receipt_schema_version": "propertyscope.property-snapshot.v1",
        "receipt_content_sha256": "b" * 64,
        "rows_received": 5_190_134,
        "rows_accepted": 5_190_134,
        "rows_rejected": 0,
        "schema_version": "propertyscope.property-snapshot.v1",
        "content_sha256": "b" * 64,
        "record_count": 5_190_134,
    }
    connection = ScriptedConnection(
        [
            operation,
            None,
            {"id": predecessor_id},
            None,
            {"id": release_id, "status": "accepted"},
            None,
            {**operation, "status": "succeeded"},
        ]
    )

    result = ConnectedStore(connection).finish_release_activation(
        operation_id,
        worker_id="loader-1",
        lease_token="token",
        status="succeeded",
        error=None,
    )

    assert result["status"] == "succeeded"
    assert any("pg_advisory_xact_lock" in query for query in connection.queries)
    assert any("INSERT INTO serving.accepted_generation" in query for query in connection.queries)
    assert not any("warehouse." in query for query in connection.queries)
    assert not any("registry." in query for query in connection.queries)
    assert not any("serving.property_coverage" in query for query in connection.queries)


def test_activation_preparation_cannot_change_accepted_visible_address_fields() -> None:
    release_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            {
                "id": operation_id,
                "dataset_release_id": release_id,
                "dataset_id": "gnaf-nsw",
                "target_feature": "feature-1",
                "release_status": "awaiting_review",
                "release_version": 4,
                "expected_release_version": 4,
            },
            None,
            {"id": operation_id, "status": "running"},
        ]
    )

    ConnectedStore(connection).materialize_release_activation(
        operation_id,
        worker_id="loader-1",
        lease_token="token",
    )

    assert connection.committed is True
    assert any("SET materialized_at=%s" in query for query in connection.queries)
    assert not any("registry.property" in query for query in connection.queries)
    assert any("warehouse.gnaf_address SET published=TRUE" in query for query in connection.queries)
    warehouse_update = next(
        query
        for query in connection.queries
        if "warehouse.gnaf_address SET published=TRUE" in query
    )
    marker_update = next(query for query in connection.queries if "SET materialized_at=%s" in query)
    assert "ops.release_activation" not in warehouse_update
    assert "warehouse.gnaf_address" not in marker_update
    assert "published=FALSE" in warehouse_update
    assert connection.commit_count == 2
    assert not any("serving.property_coverage" in query for query in connection.queries)


def test_property_coverage_derives_only_from_an_accepted_identity_generation() -> None:
    property_ref = uuid.uuid4()

    class CoverageStore(PropertyScopeStore):
        def __init__(self) -> None:
            self.query = ""

        def _fetch_one(self, query: str, params: Sequence[Any]) -> dict[str, Any]:
            del query, params
            return {"present": 1}

        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            assert params == (property_ref, property_ref)
            self.query = " ".join(query.split())
            return []

    store = CoverageStore()

    assert store.property_coverage(property_ref) == []
    assert "JOIN serving.accepted_generation accepted" in store.query
    assert "accepted.dataset_release_id=address.dataset_release_id" in store.query
    assert "NOT EXISTS" in store.query


def test_consumer_import_identity_replays_across_delivery_keys_without_insert() -> None:
    release_id = uuid.uuid4()
    existing = {
        "id": uuid.uuid4(),
        "dataset_release_id": release_id,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": "a" * 64,
        "record_count": 3,
        "expected_release_version": 2,
        "review_comment": "Original review",
        "artifact_path": f"/api/data-platform/v1/dataset-releases/{release_id}/artifact",
        "status": "polling",
        "consumer_operation_id": "consumer-owned-42",
    }
    connection = ScriptedConnection(
        [
            None,
            {
                "id": release_id,
                "dataset_id": "bocsar-crime",
                "target_feature": "feature-3",
                "schema_version": "crime-series.v1",
                "content_sha256": "a" * 64,
                "record_count": 3,
                "status": "awaiting_review",
                "version": 2,
            },
            existing,
            {"consumer_import_operation_id": existing["id"]},
        ]
    )

    operation, created = ConnectedStore(connection).create_consumer_import(
        release_id,
        _consumer_import_values(
            release_id,
            idempotency_key="different-delivery-key",
            comment="Different retry comment",
        ),
    )

    assert created is False
    assert operation["id"] == str(existing["id"])
    assert not any(
        "INSERT INTO ops.consumer_import_operation" in query for query in connection.queries
    )
    assert "status NOT IN ('failed','rejected')" in connection.queries[2]


def test_consumer_import_resumes_accepted_receipt_without_consumer_callback() -> None:
    release_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    release = {
        "id": release_id,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": "a" * 64,
        "record_count": 3,
        "manifest_json": {"target_feature": "feature-3"},
        "status": "awaiting_review",
        "version": 2,
    }
    inserted = {
        "id": uuid.uuid4(),
        "dataset_release_id": release_id,
        "status": "activation_pending",
        "phase_key": "queue_activation",
        "consumer_operation_id": "consumer-owned-42",
        "publication_receipt_id": receipt_id,
    }
    connection = ScriptedConnection(
        [
            None,
            release,
            None,
            None,
            {
                "id": receipt_id,
                "consumer_operation_id": "consumer-owned-42",
                "status": "accepted",
            },
            inserted,
            {"consumer_import_operation_id": inserted["id"]},
        ]
    )

    operation, created = ConnectedStore(connection).create_consumer_import(
        release_id, _consumer_import_values(release_id)
    )

    assert created is True
    assert operation["phase_key"] == "queue_activation"
    insert_parameters = connection.parameters[5]
    assert insert_parameters is not None
    assert "consumer-owned-42" in insert_parameters
    assert receipt_id in insert_parameters
    assert "activation_pending" in insert_parameters


def test_failed_consumer_import_with_genuine_remote_id_resumes_without_redownload() -> None:
    release_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    release = {
        "id": release_id,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": "a" * 64,
        "record_count": 3,
        "manifest_json": {"target_feature": "feature-3"},
        "status": "awaiting_review",
        "version": 2,
    }
    failed = {
        "id": operation_id,
        "consumer_operation_id": "consumer-owned-42",
        "publication_receipt_id": None,
        "attached_receipt_status": None,
        "result_json": None,
        "status": "failed",
        "phase_key": "complete",
    }
    resumed = {**failed, "status": "polling", "phase_key": "poll", "error_json": None}
    connection = ScriptedConnection(
        [None, release, None, failed, resumed, {"consumer_import_operation_id": operation_id}]
    )

    operation, created = ConnectedStore(connection).create_consumer_import(
        release_id,
        _consumer_import_values(release_id, idempotency_key="operator-retry"),
    )

    assert created is False
    assert operation["id"] == str(operation_id)
    assert operation["phase_key"] == "poll"
    assert "attempt_number=1" in connection.queries[4]
    assert not any(
        "INSERT INTO ops.consumer_import_operation" in query for query in connection.queries
    )


def test_failed_activation_with_accepted_receipt_requeues_without_consumer_redownload() -> None:
    release_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    release = {
        "id": release_id,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": "a" * 64,
        "record_count": 3,
        "manifest_json": {"target_feature": "feature-3"},
        "status": "awaiting_review",
        "version": 3,
    }
    failed = {
        "id": operation_id,
        "consumer_operation_id": "consumer-owned-42",
        "publication_receipt_id": receipt_id,
        "release_activation_id": uuid.uuid4(),
        "attached_receipt_status": "accepted",
        "status": "failed",
        "phase_key": "complete",
        "activation_attempt": 1,
    }
    resumed = {
        **failed,
        "status": "activation_pending",
        "phase_key": "queue_activation",
        "release_activation_id": None,
        "activation_attempt": 2,
    }
    connection = ScriptedConnection(
        [None, release, None, failed, resumed, {"consumer_import_operation_id": operation_id}]
    )

    operation, created = ConnectedStore(connection).create_consumer_import(
        release_id,
        _consumer_import_values(
            release_id,
            idempotency_key="fresh-activation-retry",
            expected_release_version=3,
            comment="Approved after version-conflict reconciliation",
            request_id="request-version-three",
        ),
    )

    assert created is False
    assert operation["phase_key"] == "queue_activation"
    assert operation["activation_attempt"] == 2
    retry_query = connection.queries[4]
    assert "activation_attempt=activation_attempt+1" in retry_query
    assert "release_activation_id=NULL" in retry_query
    assert "expected_release_version=%s" in retry_query
    assert "review_comment=%s" in retry_query
    retry_parameters = connection.parameters[4]
    assert retry_parameters is not None
    assert 3 in retry_parameters
    assert "Approved after version-conflict reconciliation" in retry_parameters
    assert "request-version-three" in retry_parameters
    assert not any(
        "INSERT INTO ops.consumer_import_operation" in query for query in connection.queries
    )


@pytest.mark.parametrize("terminal_status", ["rejected", "failed"])
def test_nonaccepted_attached_receipt_remains_terminal_on_fresh_delivery_key(
    terminal_status: str,
) -> None:
    release_id = uuid.uuid4()
    operation_id = uuid.uuid4()
    release = {
        "id": release_id,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": "a" * 64,
        "record_count": 3,
        "manifest_json": {"target_feature": "feature-3"},
        "status": "awaiting_review",
        "version": 2,
    }
    terminal = {
        "id": operation_id,
        "consumer_operation_id": "consumer-owned-42",
        "publication_receipt_id": uuid.uuid4(),
        "attached_receipt_status": terminal_status,
        "status": terminal_status,
        "phase_key": "complete",
    }
    connection = ScriptedConnection(
        [None, release, None, terminal, {"consumer_import_operation_id": operation_id}]
    )

    operation, created = ConnectedStore(connection).create_consumer_import(
        release_id,
        _consumer_import_values(release_id, idempotency_key="fresh-terminal-replay"),
    )

    assert created is False
    assert operation["status"] == terminal_status
    assert not any(
        query.startswith("UPDATE ops.consumer_import_operation SET") for query in connection.queries
    )


def test_delivery_alias_reuse_with_different_release_evidence_conflicts() -> None:
    first_release_id = uuid.uuid4()
    second_release_id = uuid.uuid4()
    existing = {
        "id": uuid.uuid4(),
        "dataset_release_id": first_release_id,
        "dataset_id": "bocsar-crime",
        "target_feature": "feature-3",
        "schema_version": "crime-series.v1",
        "content_sha256": "a" * 64,
        "record_count": 3,
        "expected_release_version": 2,
        "review_comment": "Reviewed",
        "artifact_path": f"/api/data-platform/v1/dataset-releases/{first_release_id}/artifact",
        "alias_expected_release_version": 2,
        "alias_review_comment": "Reviewed",
        "alias_artifact_path": (
            f"/api/data-platform/v1/dataset-releases/{first_release_id}/artifact"
        ),
    }
    connection = ScriptedConnection([existing])

    with pytest.raises(ConflictError, match="idempotency key arguments do not match"):
        ConnectedStore(connection).create_consumer_import(
            second_release_id,
            _consumer_import_values(
                second_release_id,
                idempotency_key="already-bound-delivery-key",
            ),
        )


def test_consumer_import_receipt_attachment_requires_exact_operation_evidence() -> None:
    operation_id = uuid.uuid4()
    receipt_id = uuid.uuid4()
    connection = ScriptedConnection([{"id": operation_id, "status": "activation_pending"}])

    ConnectedStore(connection).attach_consumer_import_receipt(
        operation_id,
        worker_id="runner-1",
        lease_token="lease-one",
        receipt_id=receipt_id,
        receipt_status="accepted",
    )

    query = connection.queries[0]
    assert "receipt.dataset_release_id=operation.dataset_release_id" in query
    assert "receipt.target_feature=operation.target_feature" in query
    assert "receipt.consumer_operation_id=operation.consumer_operation_id" in query
    assert "receipt.schema_version=operation.schema_version" in query
    assert "receipt.content_sha256=operation.content_sha256" in query
    assert "receipt.rows_received=operation.record_count" in query


def test_consumer_import_activation_attachment_requires_release_and_receipt_match() -> None:
    operation_id = uuid.uuid4()
    activation_id = uuid.uuid4()
    connection = ScriptedConnection([{"id": operation_id, "status": "activation_queued"}])

    ConnectedStore(connection).attach_consumer_import_activation(
        operation_id,
        worker_id="runner-1",
        lease_token="lease-one",
        activation_id=activation_id,
    )

    query = connection.queries[0]
    assert "activation.dataset_release_id=operation.dataset_release_id" in query
    assert "activation.publication_receipt_id=operation.publication_receipt_id" in query
    assert "activation.expected_release_version=operation.expected_release_version" in query
    assert "activation.status IN ('queued','claimed','running','interrupted','succeeded')" in query


def test_consumer_import_activation_interruption_requeues_without_burning_attempt() -> None:
    operation_id = uuid.uuid4()
    operation = {
        "id": operation_id,
        "status": "activation_queued",
        "phase_key": "wait_activation",
        "attempt_number": 3,
        "lease_owner": None,
        "lease_token": None,
        "lease_expires_at": None,
    }
    connection = ScriptedConnection([operation])

    result = ConnectedStore(connection).record_consumer_import_activation_outcome(
        operation_id,
        worker_id="runner-1",
        lease_token="lease-one",
        activation_status="interrupted",
        error={"code": "activation_interrupted", "retryable": True},
        poll_seconds=2,
    )

    assert result["status"] == "activation_queued"
    assert result["attempt_number"] == 3
    assert result["lease_owner"] is None
    query = connection.queries[0]
    assert "ELSE 'activation_queued' END" in query
    assert "attempt_number" not in query


def test_consumer_import_terminal_retry_keeps_bounded_attempt_number() -> None:
    operation_id = uuid.uuid4()
    terminal = {
        "id": operation_id,
        "status": "failed",
        "phase_key": "complete",
        "attempt_number": 5,
    }
    connection = ScriptedConnection([terminal])

    result = ConnectedStore(connection).retry_consumer_import(
        operation_id,
        worker_id="runner-1",
        lease_token="lease-one",
        error={"code": "still_unavailable", "retryable": True},
        retry_seconds=2,
    )

    assert result["status"] == "failed"
    assert result["attempt_number"] == 5
    query = connection.queries[0]
    assert (
        "attempt_number=CASE WHEN %s AND attempt_number<%s THEN attempt_number+1 "
        "ELSE attempt_number END"
    ) in query
