from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from typing import Any, cast

import pytest
from flask import Flask

from propertyscope_data_store.api import create_blueprint, register_error_handlers
from propertyscope_data_store.errors import ConflictError
from propertyscope_data_store.repository import PropertyScopeStore, _run_projection


class ScriptedConnection:
    def __init__(self, responses: Sequence[Mapping[str, Any] | None]) -> None:
        self.responses = list(responses)
        self.queries: list[str] = []
        self.parameters: list[Sequence[object] | None] = []
        self.current: Mapping[str, Any] | None = None
        self.committed = False

    def execute(self, query: str, parameters: Sequence[object] | None = None) -> ScriptedConnection:
        self.queries.append(" ".join(query.split()))
        self.parameters.append(parameters)
        self.current = self.responses.pop(0)
        return self

    def fetchone(self) -> Mapping[str, Any] | None:
        return self.current

    def commit(self) -> None:
        self.committed = True


class ConnectedStore(PropertyScopeStore):
    def __init__(self, connection: ScriptedConnection) -> None:
        self.test_connection = connection

    @contextmanager
    def connection(self) -> Iterator[Any]:
        yield self.test_connection


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
    candidate = next(query for query in connection.queries if "WITH candidate AS" in query)
    assert "predecessor.logical_key<task.logical_key" in candidate
    assert "predecessor.status NOT IN ('succeeded','skipped')" in candidate
    assert "run.status IN ('queued','planning','discovering','acquiring','staging'" in candidate
    interruption = next(
        query for query in connection.queries if "SET status='interrupted'" in query
    )
    assert "task.lease_expires_at<=%s" in interruption
    assert "run.cancel_requested_at IS NULL" in interruption
    assert connection.committed is True


def test_queued_cancellation_is_immediately_terminal_and_cancels_pending_tasks() -> None:
    run_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            {"id": run_id, "status": "queued"},
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
    task_update = connection.queries[1]
    assert "status IN ('pending','retry_wait')" in task_update
    assert "SET status='cancelled'" in task_update
    run_update_parameters = connection.parameters[3]
    assert run_update_parameters is not None
    assert run_update_parameters[1] is True


def test_active_cancellation_remains_cooperative_until_the_lease_finishes() -> None:
    run_id = uuid.uuid4()
    connection = ScriptedConnection(
        [
            {"id": run_id, "status": "acquiring"},
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
    run_update_parameters = connection.parameters[3]
    assert run_update_parameters is not None
    assert run_update_parameters[1] is False


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
    }

    run = store.resume_run(run_id)

    assert run["status"] == "queued"
    assert "'cancelled'" in connection.queries[0]


def test_run_projection_truthfully_describes_retry_execution() -> None:
    assert (
        _run_projection({"parent_run_id": None, "run_mode": "full_refresh"})["execution_semantics"]
        == "new_pipeline_run"
    )
    assert (
        _run_projection({"parent_run_id": uuid.uuid4(), "run_mode": "full_refresh"})[
            "execution_semantics"
        ]
        == "full_pipeline_retry"
    )
    assert (
        _run_projection({"parent_run_id": uuid.uuid4(), "run_mode": "reprocess_cached"})[
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

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
        del params
        self.query = " ".join(query.split())
        return []


def test_property_search_requires_an_accepted_identity_generation() -> None:
    store = PropertyQueryStore()

    store.search_properties("11 example street", state="NSW", limit=25)

    assert "JOIN serving.accepted_generation accepted" in store.query
    assert "accepted.dataset_release_id=identifier.source_release_id" in store.query
    assert "identifier.is_current" in store.query


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
            {"count": 0},
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


def test_candidate_export_replay_rejects_a_changed_manifest() -> None:
    release_id = uuid.uuid4()
    artifact_id = uuid.uuid4()
    digest = "b" * 64
    connection = ScriptedConnection(
        [
            {
                "id": release_id,
                "status": "candidate",
                "schema_version": "propertyscope.property-sales.v1",
                "content_sha256": digest,
                "record_count": 1,
                "artifact_record_id": artifact_id,
                "manifest_json": {"created_at": "2026-08-16T00:00:00Z"},
            },
            {"id": artifact_id},
        ]
    )

    with pytest.raises(ConflictError, match="immutable evidence"):
        ConnectedStore(connection).bind_release_export(
            release_id,
            {
                "artifact_record_id": artifact_id,
                "schema_version": "propertyscope.property-sales.v1",
                "content_sha256": digest,
                "record_count": 1,
                "manifest": {"created_at": "2026-08-17T00:00:00Z"},
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
                    "coverage_json": {"years": [2025]},
                    "import_profile_key": "psi-sales",
                }
            return {"count": 1}

        def _fetch_all(self, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
            connection.queries.append(" ".join(query.split()))
            connection.parameters.append(params)
            return [{"source_business_key": "sale-1", "source_revision": 1}]

    page = ProjectionStore(connection).release_product_records(release_id, limit=25, offset=0)

    assert page["release_id"] == str(release_id)
    assert page["candidate_generation_id"] == str(release_id)
    assert page["total"] == 1
    assert all(
        release_id in parameters for parameters in connection.parameters if parameters is not None
    )
    projection = next(query for query in connection.queries if "warehouse.psi_sale" in query)
    assert "dataset_release_id=%s" in projection
    assert "ORDER BY source_business_key,source_revision" in projection


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
                "schema_version": "propertyscope.property-sales.v1",
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
                "schema_version": "propertyscope.property-sales.v1",
                "content_sha256": "f" * 64,
                "rows_received": 1,
                "rows_accepted": 1,
                "rows_rejected": 0,
                "request_id": "request-1",
            },
        )
