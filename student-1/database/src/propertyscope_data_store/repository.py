"""PostgreSQL repository and atomic state/lease operations."""

# SQL statements stay line-oriented so schema and transition policies remain reviewable.
# ruff: noqa: E501

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any

from psycopg import Connection, errors, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from propertyscope_data_store._import_operations import _RegisteredImportOperations
from propertyscope_data_store._property_reads import (
    PROPERTY_SEARCH_CANDIDATE_LIMIT as PROPERTY_SEARCH_CANDIDATE_LIMIT,
)
from propertyscope_data_store._property_reads import (
    PropertySearchResults as PropertySearchResults,
)
from propertyscope_data_store._property_reads import (
    _CanonicalPropertyReads,
)
from propertyscope_data_store._property_reads import (
    _normalise_property_query as _normalise_property_query,
)
from propertyscope_data_store._release_records import _ReleaseRecords
from propertyscope_data_store.errors import (
    ConflictError,
    LeaseConflictError,
    NotFoundError,
)
from propertyscope_data_store.import_profiles import (
    ImportResult,
    PreparedImport,
)
from propertyscope_data_store.migrations import migrate, schema_fingerprint
from propertyscope_data_store.orchestration_policy import (
    TERMINAL_RUN_STATES,
    run_status_for_stage,
    task_plan,
    validate_retry_parent,
)
from propertyscope_data_store.persistence_support import cancellation_error as _cancellation_error
from propertyscope_data_store.persistence_support import json_document as _json
from propertyscope_data_store.persistence_support import lease_expired_error as _lease_expired_error
from propertyscope_data_store.persistence_support import normalise_row as _dict
from propertyscope_data_store.persistence_support import normalise_rows as _rows
from propertyscope_data_store.persistence_support import project_run as _run_projection
from propertyscope_data_store.persistence_support import (
    receipt_matches_values as _receipt_matches_values,
)
from propertyscope_data_store.persistence_support import require_source_snapshot as _source_snapshot
from propertyscope_data_store.persistence_support import (
    validate_artifact_replay as _validate_artifact_replay,
)
from propertyscope_data_store.runtime_registry import (
    RuntimeProfile,
    RuntimeRegistry,
    RuntimeRegistryError,
)

JsonObject = dict[str, Any]
TERMINAL_TASK_STATES = frozenset({"succeeded", "failed", "cancelled", "skipped"})
TERMINAL_ACTIVATION_STATES = frozenset({"succeeded", "failed"})


def _activation_receipt_matches(evidence: Mapping[str, Any]) -> bool:
    return (
        evidence.get("receipt_status") == "accepted"
        and evidence.get("receipt_schema_version") == evidence.get("schema_version")
        and evidence.get("receipt_content_sha256") == evidence.get("content_sha256")
        and int(evidence.get("rows_received", -1)) == int(evidence.get("record_count", -2))
        and int(evidence.get("rows_accepted", -1)) == int(evidence.get("record_count", -2))
        and int(evidence.get("rows_rejected", -1)) == 0
    )


def _validate_runtime_profile_values(values: Mapping[str, Any], profile: RuntimeProfile) -> None:
    """Reject a request that contradicts its selected registered profile.

    Runtime fields may be omitted because the registry supplies them.  Keeping the
    compatibility fields on the HTTP contract lets existing clients send their
    snapshot, but a stale or manipulated value can no longer be silently ignored.
    """
    expected = {
        "profile_version": profile.version,
        "adapter_key": profile.adapter.key,
        "adapter_version": profile.adapter.version,
        "release_builder_key": profile.release_builder.key,
        "release_builder_version": profile.release_builder.version,
        "import_profile_key": profile.import_profile.key,
        "import_profile_version": profile.import_profile.version,
        "quality_policy_key": profile.quality_policy.key,
        "quality_policy_version": profile.quality_policy.version,
    }
    for field, registered in expected.items():
        supplied = values.get(field)
        if supplied is not None and str(supplied) != registered:
            raise RuntimeRegistryError(
                f"{field} conflicts with profile {profile.key}: "
                f"expected {registered}, received {supplied}"
            )


class PropertyScopeStore:
    """Exclusive persistence facade for Feature 1 PostgreSQL/PostGIS."""

    def __init__(
        self,
        database_url: str,
        *,
        runtime_registry: RuntimeRegistry,
        open_pool: bool = True,
        loader_temp_file_limit_kib: int | None = None,
    ) -> None:
        if loader_temp_file_limit_kib is not None and not (
            64 * 1024 <= loader_temp_file_limit_kib <= 64 * 1024 * 1024
        ):
            raise ValueError("loader temp-file limit is outside the supported bound")
        self._runtime_registry = runtime_registry
        self._loader_temp_file_limit_kib = loader_temp_file_limit_kib
        self._pool = ConnectionPool(
            database_url,
            min_size=1,
            max_size=8,
            open=open_pool,
            kwargs={"row_factory": dict_row, "autocommit": False},
        )

    def open(self) -> None:
        self._pool.open(wait=True)

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def connection(self) -> Iterator[Connection[Any]]:
        with self._pool.connection() as connection:
            self._apply_loader_transaction_limits(connection)
            yield connection

    def _apply_loader_transaction_limits(self, connection: Connection[Any]) -> None:
        """Apply loader-only limits to the current transaction, never globally."""
        if self._loader_temp_file_limit_kib is not None:
            connection.execute(
                f"SET LOCAL temp_file_limit = '{self._loader_temp_file_limit_kib}kB'"
            )

    def initialize(self) -> str:
        """Migrate from empty, including the idempotent Release 0 showcase baseline."""
        with self.connection() as connection:
            migrate(connection)
            return schema_fingerprint(connection)

    def ready(self) -> bool:
        try:
            with self.connection() as connection:
                row = connection.execute(
                    """SELECT postgis_version() AS version,
                    to_regclass('ops.run_task') AS run_task,
                    to_regclass('ops.import_operation') AS import_operation,
                    to_regclass('ops.release_activation') AS release_activation,
                    to_regclass('warehouse.gnaf_address') AS gnaf_address"""
                ).fetchone()
            return row is not None and all(
                bool(row[field])
                for field in (
                    "version",
                    "run_task",
                    "import_operation",
                    "release_activation",
                    "gnaf_address",
                )
            )
        except Exception:
            return False

    def counts(self) -> JsonObject:
        tables = (
            "ops.source_definition",
            "ops.job_definition",
            "ops.ingestion_run",
            "ops.run_task",
            "ops.import_operation",
            "ops.release_activation",
            "ops.artifact_record",
            "ops.quality_result",
            "ops.dataset_release",
            "ops.publication_receipt",
            "registry.property",
            "registry.property_identifier",
            "registry.address_alias",
            "registry.unresolved_match",
            "warehouse.gnaf_address",
            "warehouse.psi_sale",
            "warehouse.bocsar_observation",
            "warehouse.bocsar_coverage",
            "warehouse.school",
            "warehouse.spatial_feature",
            "serving.accepted_generation",
            "serving.property_coverage",
            "ops.idempotency_record",
        )
        result: JsonObject = {}
        with self.connection() as connection:
            for table in tables:
                schema_name, table_name = table.split(".", 1)
                row = connection.execute(
                    sql.SQL("SELECT count(*) AS count FROM {}.{}").format(
                        sql.Identifier(schema_name), sql.Identifier(table_name)
                    )
                ).fetchone()
                result[table] = int(row["count"]) if row else 0
        return result

    def fingerprint(self) -> str:
        """Expose the deterministic migrated schema fingerprint for release evidence."""
        with self.connection() as connection:
            return schema_fingerprint(connection)

    # Sources and jobs are the two complete operator CRUD aggregates.
    def list_sources(
        self, *, status: str | None, query_text: str | None, limit: int, offset: int
    ) -> list[JsonObject]:
        query = "SELECT * FROM ops.source_definition"
        params: list[Any] = []
        predicates: list[str] = []
        if status:
            predicates.append("status = %s")
            params.append(status)
        if query_text:
            predicates.append(
                "POSITION(lower(%s) IN lower(concat_ws(' ',name,publisher,adapter_key,cadence,notes))) > 0"
            )
            params.append(query_text)
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        query += " ORDER BY name LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        return self._fetch_all(query, params)

    def get_source(self, source_id: uuid.UUID) -> JsonObject:
        return self._required("SELECT * FROM ops.source_definition WHERE id = %s", (source_id,))

    def create_source(self, values: Mapping[str, Any]) -> JsonObject:
        source_id = uuid.UUID(str(values.get("id", uuid.uuid4())))
        now = datetime.now(UTC)
        try:
            with self.connection() as connection:
                row = connection.execute(
                    """
                    INSERT INTO ops.source_definition (
                        id,name,publisher,source_url,adapter_key,cadence,licence_id,licence_url,
                        redistribution_policy,target_features_json,status,notes,created_at,updated_at,version
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1) RETURNING *
                    """,
                    (
                        source_id,
                        values["name"],
                        values["publisher"],
                        values["source_url"],
                        values["adapter_key"],
                        values["cadence"],
                        values["licence_id"],
                        values["licence_url"],
                        values["redistribution_policy"],
                        _json(values.get("target_features", [])),
                        values.get("status", "draft"),
                        values.get("notes", ""),
                        now,
                        now,
                    ),
                ).fetchone()
                connection.commit()
        except errors.UniqueViolation as exc:
            raise ConflictError("source name already exists") from exc
        return _dict(row)

    def update_source(self, source_id: uuid.UUID, values: Mapping[str, Any]) -> JsonObject:
        current = self.get_source(source_id)
        expected = int(values["version"])
        if current["status"] == "retired" and values.get("status") != "retired":
            raise ConflictError("retired source definitions cannot be reactivated")
        fields = (
            "name",
            "publisher",
            "source_url",
            "adapter_key",
            "cadence",
            "licence_id",
            "licence_url",
            "redistribution_policy",
            "status",
            "notes",
        )
        merged = {name: values.get(name, current[name]) for name in fields}
        targets = values.get("target_features", current["target_features_json"])
        with self.connection() as connection:
            connection.execute(
                "SELECT id FROM ops.source_definition WHERE id=%s FOR UPDATE", (source_id,)
            )
            policy_changed = any(
                merged[name] != current[name]
                for name in ("licence_id", "licence_url", "redistribution_policy")
            )
            if policy_changed:
                release = connection.execute(
                    "SELECT id FROM ops.dataset_release WHERE source_definition_id=%s LIMIT 1",
                    (source_id,),
                ).fetchone()
                if release is not None:
                    raise ConflictError(
                        "licence and redistribution evidence is immutable after a release exists"
                    )
            row = connection.execute(
                """
                UPDATE ops.source_definition SET name=%s,publisher=%s,source_url=%s,adapter_key=%s,
                    cadence=%s,licence_id=%s,licence_url=%s,redistribution_policy=%s,
                    target_features_json=%s,status=%s,notes=%s,updated_at=%s,version=version+1
                WHERE id=%s AND version=%s RETURNING *
                """,
                (
                    merged["name"],
                    merged["publisher"],
                    merged["source_url"],
                    merged["adapter_key"],
                    merged["cadence"],
                    merged["licence_id"],
                    merged["licence_url"],
                    merged["redistribution_policy"],
                    _json(targets),
                    merged["status"],
                    merged["notes"],
                    datetime.now(UTC),
                    source_id,
                    expected,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise ConflictError("source version does not match")
        return _dict(row)

    def delete_source(self, source_id: uuid.UUID) -> None:
        source = self.get_source(source_id)
        if source["status"] != "draft":
            raise ConflictError("only unused draft sources can be deleted")
        try:
            self._delete("ops", "source_definition", source_id)
        except errors.ForeignKeyViolation as exc:
            raise ConflictError("source has retained job or release evidence") from exc

    def list_jobs(
        self, *, status: str | None, query_text: str | None, limit: int, offset: int
    ) -> list[JsonObject]:
        query = """
            SELECT job.*, source.name AS source_name FROM ops.job_definition job
            JOIN ops.source_definition source ON source.id = job.source_definition_id
        """
        params: list[Any] = []
        predicates: list[str] = []
        if status:
            predicates.append("job.status = %s")
            params.append(status)
        if query_text:
            predicates.append(
                "POSITION(lower(%s) IN lower(concat_ws(' ',job.name,source.name,job.dataset_id,job.profile_key,job.adapter_key))) > 0"
            )
            params.append(query_text)
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        query += " ORDER BY job.name LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        return self._fetch_all(query, params)

    def get_job(self, job_id: uuid.UUID) -> JsonObject:
        return self._required("SELECT * FROM ops.job_definition WHERE id = %s", (job_id,))

    def create_job(self, values: Mapping[str, Any]) -> JsonObject:
        job_id = uuid.UUID(str(values.get("id", uuid.uuid4())))
        now = datetime.now(UTC)
        try:
            registry = self._runtime_registry
            if registry is None:
                raise RuntimeRegistryError("runtime registry was not configured")
            runtime = registry.profile(str(values["profile_key"]))
            _validate_runtime_profile_values(values, runtime)
        except (KeyError, RuntimeRegistryError) as exc:
            raise ConflictError(f"job runtime configuration is invalid: {exc}") from exc
        columns = (
            "source_definition_id",
            "name",
            "profile_key",
            "profile_version",
            "adapter_key",
            "adapter_version",
            "release_builder_key",
            "release_builder_version",
            "import_profile_key",
            "import_profile_version",
            "target_feature",
            "dataset_id",
            "refresh_strategy",
            "default_run_mode",
            "quality_policy_key",
            "quality_policy_version",
            "status",
            "schedule_text",
        )
        runtime_versions = {
            "profile_version": runtime.version,
            "adapter_key": runtime.adapter.key,
            "adapter_version": runtime.adapter.version,
            "release_builder_key": runtime.release_builder.key,
            "release_builder_version": runtime.release_builder.version,
            "import_profile_key": runtime.import_profile.key,
            "import_profile_version": runtime.import_profile.version,
            "quality_policy_key": runtime.quality_policy.key,
            "quality_policy_version": runtime.quality_policy.version,
        }
        parameters = [
            runtime_versions[name] if name in runtime_versions else values[name] for name in columns
        ]
        try:
            with self.connection() as connection:
                row = connection.execute(
                    f"""INSERT INTO ops.job_definition
                    (id,{",".join(columns)},created_at,updated_at,version)
                    VALUES (%s,{",".join(["%s"] * len(columns))},%s,%s,1) RETURNING *""",
                    (job_id, *parameters, now, now),
                ).fetchone()
                connection.commit()
        except errors.UniqueViolation as exc:
            raise ConflictError("job name or profile version already exists") from exc
        except errors.ForeignKeyViolation as exc:
            raise NotFoundError("source definition does not exist") from exc
        return _dict(row)

    def update_job(self, job_id: uuid.UUID, values: Mapping[str, Any]) -> JsonObject:
        current = self.get_job(job_id)
        expected = int(values["version"])
        if current["status"] == "retired" and values.get("status") != "retired":
            raise ConflictError("retired jobs cannot be reactivated")
        editable = (
            "name",
            "status",
            "schedule_text",
        )
        merged = {name: values.get(name, current[name]) for name in editable}
        with self.connection() as connection:
            row = connection.execute(
                """
                UPDATE ops.job_definition SET name=%s,status=%s,
                    schedule_text=%s,updated_at=%s,version=version+1
                WHERE id=%s AND version=%s RETURNING *
                """,
                (
                    merged["name"],
                    merged["status"],
                    merged["schedule_text"],
                    datetime.now(UTC),
                    job_id,
                    expected,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise ConflictError("job version does not match")
        return _dict(row)

    def delete_job(self, job_id: uuid.UUID) -> None:
        job = self.get_job(job_id)
        if job["status"] != "draft":
            raise ConflictError("only unused draft jobs can be deleted")
        try:
            self._delete("ops", "job_definition", job_id)
        except errors.ForeignKeyViolation as exc:
            raise ConflictError("job has retained run evidence") from exc

    # Durable runs/tasks.
    def create_run(
        self,
        job_id: uuid.UUID,
        *,
        mode: str,
        scope: Mapping[str, Any],
        idempotency_key: str,
        request_id: str,
        parent_run_id: uuid.UUID | None = None,
    ) -> tuple[JsonObject, bool]:
        job = self.get_job(job_id)
        if job["status"] != "active":
            raise ConflictError("job is not active")
        if not _is_complete_acquisition_scope(scope):
            raise ConflictError("runs must request the complete registered source")
        existing = self._fetch_one(
            "SELECT * FROM ops.ingestion_run WHERE job_definition_id=%s AND idempotency_key=%s",
            (job_id, idempotency_key),
        )
        if existing:
            return _run_projection(existing), False
        attempt_number = 1
        parent: JsonObject | None = None
        if parent_run_id is not None:
            parent = self.get_run(parent_run_id)
            attempt_number = validate_retry_parent(job_id, mode, parent)
            if mode == "reprocess_cached" and parent["requested_scope_json"] != dict(scope):
                raise ConflictError("cached reprocessing requires the same complete source scope")
            if (
                mode == "reprocess_cached"
                and self._fetch_one(
                    """SELECT id FROM ops.artifact_record WHERE ingestion_run_id=%s
                AND artifact_kind='canonical_import' ORDER BY created_at DESC LIMIT 1""",
                    (parent_run_id,),
                )
                is None
            ):
                raise ConflictError("cached reprocessing requires a verified canonical artifact")
        now = datetime.now(UTC)
        run_id = uuid.uuid4()
        with self.connection() as connection:
            try:
                row = connection.execute(
                    """
                    INSERT INTO ops.ingestion_run (
                        id,job_definition_id,source_definition_id,adapter_version,
                        release_builder_version,import_profile_version,normalisation_version,
                        profile_key,run_mode,requested_scope_json,attempt_number,parent_run_id,
                        requested_at,status,request_id,idempotency_key,created_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,'1.0.0',%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s)
                    RETURNING *
                    """,
                    (
                        run_id,
                        job_id,
                        job["source_definition_id"],
                        job["adapter_version"],
                        job["release_builder_version"],
                        job["import_profile_version"],
                        job["profile_key"],
                        mode,
                        _json(scope),
                        attempt_number,
                        parent_run_id,
                        now,
                        request_id,
                        idempotency_key,
                        now,
                    ),
                ).fetchone()
                task_ids: dict[str, uuid.UUID] = {}
                for planned_task in task_plan(mode):
                    task_id = uuid.uuid4()
                    task_ids[planned_task.stage] = task_id
                    connection.execute(
                        """
                        INSERT INTO ops.run_task (
                            id,ingestion_run_id,logical_key,partition_json,stage,status,
                            attempt_number,finished_at,rows_in,rows_out,created_at,updated_at,version
                        ) VALUES (%s,%s,%s,%s,%s,%s,1,%s,0,0,%s,%s,1)
                        """,
                        (
                            task_id,
                            run_id,
                            planned_task.logical_key,
                            _json(scope),
                            planned_task.stage,
                            "skipped" if planned_task.skipped else "pending",
                            now if planned_task.skipped else None,
                            now,
                            now,
                        ),
                    )
                if mode == "reprocess_cached" and parent_run_id is not None:
                    for kind, stage, logical_key in (
                        ("source_snapshot", "discover", "00/discover"),
                        ("canonical_import", "acquire", "01/acquire"),
                    ):
                        connection.execute(
                            """INSERT INTO ops.artifact_record (
                            id,ingestion_run_id,run_task_id,logical_key,artifact_kind,storage_key,
                            source_uri_redacted,content_sha256,media_type,bytes,etag,
                            source_last_modified,schema_version,retention_class,created_at
                            ) SELECT %s,%s,%s,%s,artifact_kind,storage_key,source_uri_redacted,
                            content_sha256,media_type,bytes,etag,source_last_modified,schema_version,
                            retention_class,%s FROM ops.artifact_record WHERE ingestion_run_id=%s
                            AND artifact_kind=%s ORDER BY created_at DESC LIMIT 1""",
                            (
                                uuid.uuid4(),
                                run_id,
                                task_ids[stage],
                                logical_key,
                                now,
                                parent_run_id,
                                kind,
                            ),
                        )
                    connection.execute(
                        """UPDATE ops.ingestion_run child SET source_snapshot_json=
                        (SELECT parent.source_snapshot_json FROM ops.ingestion_run parent
                         WHERE parent.id=%s) WHERE child.id=%s""",
                        (parent_run_id, run_id),
                    )
                connection.commit()
            except errors.UniqueViolation:
                connection.rollback()
                existing = self._required(
                    "SELECT * FROM ops.ingestion_run WHERE job_definition_id=%s AND idempotency_key=%s",
                    (job_id, idempotency_key),
                )
                return _run_projection(existing), False
        return _run_projection(_dict(row)), True

    def list_runs(
        self, *, status: str | None, query_text: str | None, limit: int, offset: int
    ) -> list[JsonObject]:
        query = """
            SELECT run.*, job.name AS job_name, source.name AS source_name
            FROM ops.ingestion_run run
            JOIN ops.job_definition job ON job.id=run.job_definition_id
            JOIN ops.source_definition source ON source.id=run.source_definition_id
        """
        params: list[Any] = []
        predicates: list[str] = []
        if status:
            predicates.append("run.status=%s")
            params.append(status)
        if query_text:
            predicates.append(
                "POSITION(lower(%s) IN lower(concat_ws(' ',run.id::text,run.request_id,run.profile_key,run.status,job.name,source.name))) > 0"
            )
            params.append(query_text)
        if predicates:
            query += " WHERE " + " AND ".join(predicates)
        query += " ORDER BY run.requested_at DESC LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        return [_run_projection(item) for item in self._fetch_all(query, params)]

    def get_run(self, run_id: uuid.UUID) -> JsonObject:
        return _run_projection(
            self._required("SELECT * FROM ops.ingestion_run WHERE id=%s", (run_id,))
        )

    def run_tasks(self, run_id: uuid.UUID, *, limit: int, offset: int) -> list[JsonObject]:
        self.get_run(run_id)
        return self._fetch_all(
            "SELECT * FROM ops.run_task WHERE ingestion_run_id=%s ORDER BY created_at,logical_key LIMIT %s OFFSET %s",
            (run_id, limit, offset),
        )

    def run_artifacts(self, run_id: uuid.UUID, *, limit: int, offset: int) -> list[JsonObject]:
        self.get_run(run_id)
        return self._fetch_all(
            "SELECT * FROM ops.artifact_record WHERE ingestion_run_id=%s ORDER BY created_at LIMIT %s OFFSET %s",
            (run_id, limit, offset),
        )

    def run_quality(self, run_id: uuid.UUID, *, limit: int, offset: int) -> list[JsonObject]:
        self.get_run(run_id)
        return self._fetch_all(
            "SELECT * FROM ops.quality_result WHERE ingestion_run_id=%s ORDER BY created_at,rule_key LIMIT %s OFFSET %s",
            (run_id, limit, offset),
        )

    def artifact_retention_inventory(self) -> list[JsonObject]:
        """Expose physical references, retained size, and the strongest retention reason."""
        return self._fetch_all(
            """SELECT artifact.storage_key,artifact.content_sha256,
            max(artifact.bytes) AS bytes,count(*) AS reference_count,
            array_agg(DISTINCT artifact.retention_class ORDER BY artifact.retention_class)
                AS retention_classes,
            array_agg(DISTINCT run.status ORDER BY run.status) AS run_statuses,
            bool_or(release.id IS NOT NULL) AS referenced_by_release,
            CASE
              WHEN bool_or(release.status IN ('accepted','superseded')) THEN 'published_release_evidence'
              WHEN bool_or(release.id IS NOT NULL) THEN 'candidate_release_evidence'
              WHEN bool_or(run.status IN ('failed','cancelled')) THEN 'terminal_run_audit_evidence'
              WHEN bool_or(artifact.retention_class='source-cache') THEN 'reusable_source_cache'
              ELSE 'active_run_lineage'
            END AS retention_reason
            FROM ops.artifact_record artifact
            JOIN ops.ingestion_run run ON run.id=artifact.ingestion_run_id
            LEFT JOIN ops.dataset_release release ON release.artifact_record_id=artifact.id
            GROUP BY artifact.storage_key,artifact.content_sha256
            ORDER BY max(artifact.bytes) DESC,artifact.storage_key""",
            (),
        )

    def request_cancel(self, run_id: uuid.UUID) -> JsonObject:
        now = datetime.now(UTC)
        with self.connection() as connection:
            run = connection.execute(
                "SELECT * FROM ops.ingestion_run WHERE id=%s FOR UPDATE", (run_id,)
            ).fetchone()
            if run is None:
                raise NotFoundError("record does not exist")
            if run["status"] == "cancelled" and run["cancel_requested_at"] is not None:
                # A client may lose the first response after this database committed. Returning
                # the same durable outcome makes retry/reconciliation truthful and idempotent.
                return _run_projection(_dict(run))
            if run["status"] in TERMINAL_RUN_STATES:
                raise ConflictError("terminal run cannot be cancelled")
            connection.execute(
                """UPDATE ops.run_task SET status='cancelled',finished_at=%s,updated_at=%s,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                error_json=COALESCE(error_json,%s),version=version+1
                WHERE ingestion_run_id=%s AND status IN ('pending','retry_wait')""",
                (now, now, _json(_cancellation_error()), run_id),
            )
            connection.execute(
                """UPDATE ops.import_operation SET status='cancelled',finished_at=%s,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                error_json=COALESCE(error_json,%s),version=version+1
                WHERE ingestion_run_id=%s AND status IN ('planned','queued','interrupted')""",
                (now, _json(_cancellation_error()), run_id),
            )
            active = connection.execute(
                """SELECT count(*) AS count FROM ops.run_task
                WHERE ingestion_run_id=%s AND status IN ('claimed','running')""",
                (run_id,),
            ).fetchone()
            terminal = active is None or int(active["count"]) == 0
            row = connection.execute(
                """WITH abandoned AS (
                    UPDATE ops.dataset_release SET status='abandoned',terminal_reason_json=%s,
                    review_comment='System-terminalized cancelled ingestion candidate; retained for audit.',
                    updated_at=%s,version=version+1
                    WHERE ingestion_run_id=%s AND status IN ('draft','candidate') RETURNING id
                ) UPDATE ops.ingestion_run SET cancel_requested_at=COALESCE(cancel_requested_at,%s),
                status=CASE WHEN %s THEN 'cancelled' ELSE status END,
                finished_at=CASE WHEN %s THEN %s ELSE finished_at END,
                error_json=CASE WHEN %s THEN %s ELSE error_json END,
                lease_owner=CASE WHEN %s THEN NULL ELSE lease_owner END,
                lease_token=CASE WHEN %s THEN NULL ELSE lease_token END,
                lease_expires_at=CASE WHEN %s THEN NULL ELSE lease_expires_at END
                WHERE id=%s RETURNING *""",
                (
                    _json(
                        {
                            "code": "ingestion_cancelled",
                            "message": "Candidate release abandoned after operator cancellation",
                            "ingestion_run_id": str(run_id),
                            "bounded_error": _cancellation_error(),
                        }
                    ),
                    now,
                    run_id,
                    now,
                    terminal,
                    terminal,
                    now,
                    terminal,
                    _json(_cancellation_error()),
                    terminal,
                    terminal,
                    terminal,
                    run_id,
                ),
            ).fetchone()
            connection.commit()
        return _run_projection(_dict(row))

    def resume_run(self, run_id: uuid.UUID) -> JsonObject:
        run = self.get_run(run_id)
        if run["status"] != "interrupted":
            raise ConflictError("only interrupted runs can resume")
        if not _is_complete_acquisition_scope(run["requested_scope_json"]):
            raise ConflictError("historical partial runs cannot resume")
        now = datetime.now(UTC)
        with self.connection() as connection:
            connection.execute(
                """UPDATE ops.run_task SET status='pending',lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,heartbeat_at=NULL,attempt_number=attempt_number+1,
                version=version+1,updated_at=%s
                WHERE ingestion_run_id=%s
                AND status IN ('claimed','running','retry_wait','cancelled')""",
                (now, run_id),
            )
            row = connection.execute(
                """UPDATE ops.ingestion_run SET status='queued',lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,heartbeat_at=NULL,finished_at=NULL,error_json=NULL,
                cancel_requested_at=NULL WHERE id=%s RETURNING *""",
                (run_id,),
            ).fetchone()
            connection.commit()
        return _run_projection(_dict(row))

    def claim_task(self, *, worker_id: str, lease_seconds: int) -> JsonObject | None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        token = uuid.uuid4().hex
        with self.connection() as connection:
            # A cancelled worker may disappear before acknowledging the request. Expired
            # work is terminally cancelled; a live lease remains cooperatively cancellable.
            connection.execute(
                """UPDATE ops.run_task task SET status='cancelled',finished_at=%s,updated_at=%s,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                error_json=COALESCE(task.error_json,%s),version=task.version+1
                FROM ops.ingestion_run run WHERE run.id=task.ingestion_run_id
                AND run.cancel_requested_at IS NOT NULL AND task.status IN ('claimed','running')
                AND task.lease_expires_at<=%s""",
                (now, now, _json(_cancellation_error()), now),
            )
            connection.execute(
                """UPDATE ops.run_task task SET status='cancelled',finished_at=%s,updated_at=%s,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                error_json=COALESCE(task.error_json,%s),version=task.version+1
                FROM ops.ingestion_run run WHERE run.id=task.ingestion_run_id
                AND run.cancel_requested_at IS NOT NULL AND task.status IN ('pending','retry_wait')""",
                (now, now, _json(_cancellation_error())),
            )
            connection.execute(
                """UPDATE ops.ingestion_run run SET status='cancelled',finished_at=%s,
                error_json=%s,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                WHERE run.cancel_requested_at IS NOT NULL
                AND run.status NOT IN ('succeeded','failed','cancelled')
                AND NOT EXISTS (SELECT 1 FROM ops.run_task task WHERE task.ingestion_run_id=run.id
                    AND task.status IN ('claimed','running'))""",
                (now, _json(_cancellation_error())),
            )
            # Lease expiry is a durable interruption, never implicit work stealing. The
            # operator must explicitly resume so retained checkpoints remain inspectable.
            connection.execute(
                """UPDATE ops.ingestion_run run SET status='interrupted',finished_at=NULL,
                error_json=%s,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                FROM ops.run_task task WHERE task.ingestion_run_id=run.id
                AND task.status IN ('claimed','running') AND task.lease_expires_at<=%s
                AND run.cancel_requested_at IS NULL
                AND run.status NOT IN ('succeeded','failed','cancelled','interrupted')""",
                (_json(_lease_expired_error()), now),
            )
            row = connection.execute(
                """
                WITH candidate AS (
                    SELECT task.id FROM ops.run_task task
                    JOIN ops.ingestion_run run ON run.id=task.ingestion_run_id
                    WHERE task.status='pending'
                      AND run.status IN ('queued','planning','discovering','acquiring','staging',
                        'normalising','validating','building_release')
                      AND run.cancel_requested_at IS NULL
                      AND NOT EXISTS (
                        SELECT 1 FROM ops.run_task predecessor
                        WHERE predecessor.ingestion_run_id=task.ingestion_run_id
                          AND predecessor.logical_key<task.logical_key
                          AND predecessor.status NOT IN ('succeeded','skipped')
                      )
                    ORDER BY task.created_at,task.logical_key FOR UPDATE SKIP LOCKED LIMIT 1
                )
                UPDATE ops.run_task task SET status='claimed',lease_owner=%s,lease_token=%s,
                    lease_expires_at=%s,heartbeat_at=%s,started_at=COALESCE(started_at,%s),
                    updated_at=%s,version=version+1 FROM candidate
                WHERE task.id=candidate.id RETURNING task.*
                """,
                (worker_id, token, expires, now, now, now),
            ).fetchone()
            if row is not None:
                connection.execute(
                    """UPDATE ops.ingestion_run SET status=%s,
                    started_at=COALESCE(started_at,%s),heartbeat_at=%s WHERE id=%s""",
                    (
                        run_status_for_stage(str(row["stage"])),
                        now,
                        now,
                        row["ingestion_run_id"],
                    ),
                )
                context = connection.execute(
                    """SELECT run.profile_key,run.run_mode,run.requested_scope_json,
                    run.source_snapshot_json,
                    job.adapter_key,job.import_profile_key,job.import_profile_version,
                    job.dataset_id,job.target_feature,job.source_definition_id
                    FROM ops.ingestion_run run JOIN ops.job_definition job
                    ON job.id=run.job_definition_id WHERE run.id=%s""",
                    (row["ingestion_run_id"],),
                ).fetchone()
                if context:
                    row.update(context)
            connection.commit()
        return _dict(row) if row else None

    def heartbeat_task(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
        progress: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        now = datetime.now(UTC)
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.run_task task SET
                status=CASE WHEN run.cancel_requested_at IS NOT NULL THEN 'cancelled'
                    ELSE 'running' END,
                heartbeat_at=CASE WHEN run.cancel_requested_at IS NOT NULL THEN NULL ELSE %s END,
                lease_expires_at=CASE WHEN run.cancel_requested_at IS NOT NULL THEN NULL ELSE %s END,
                lease_owner=CASE WHEN run.cancel_requested_at IS NOT NULL THEN NULL
                    ELSE task.lease_owner END,
                lease_token=CASE WHEN run.cancel_requested_at IS NOT NULL THEN NULL
                    ELSE task.lease_token END,
                finished_at=CASE WHEN run.cancel_requested_at IS NOT NULL THEN %s
                    ELSE task.finished_at END,
                error_json=CASE WHEN run.cancel_requested_at IS NOT NULL
                    THEN COALESCE(task.error_json,%s) ELSE task.error_json END,
                updated_at=%s,version=task.version+1
                FROM ops.ingestion_run run WHERE task.id=%s
                AND run.id=task.ingestion_run_id AND task.lease_owner=%s
                AND task.lease_token=%s AND task.lease_expires_at>%s
                AND task.status IN ('claimed','running') RETURNING task.*""",
                (
                    now,
                    now + timedelta(seconds=lease_seconds),
                    now,
                    _json(_cancellation_error()),
                    now,
                    task_id,
                    worker_id,
                    lease_token,
                    now,
                ),
            ).fetchone()
            if row is not None and row["status"] == "cancelled":
                run_id = row["ingestion_run_id"]
                connection.execute(
                    """UPDATE ops.run_task SET status='cancelled',finished_at=%s,updated_at=%s,
                    error_json=COALESCE(error_json,%s),version=version+1
                    WHERE ingestion_run_id=%s AND status IN ('pending','retry_wait')""",
                    (now, now, _json(_cancellation_error()), run_id),
                )
                connection.execute(
                    """UPDATE ops.ingestion_run SET status='cancelled',finished_at=%s,
                    error_json=%s,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                    WHERE id=%s AND cancel_requested_at IS NOT NULL""",
                    (now, _json(_cancellation_error()), run_id),
                )
            elif row is not None:
                run_id = row["ingestion_run_id"]
                task_stage = row["stage"]
                if progress:
                    phase = str(progress.get("phase") or row["stage"])[:100]
                    progress_rows = max(0, int(progress.get("rows_processed", 0)))
                    progress_bytes = max(0, int(progress.get("bytes_processed", 0)))
                    total_rows = progress.get("total_rows")
                    total_bytes = progress.get("total_bytes")
                    row = connection.execute(
                        """UPDATE ops.run_task SET progress_phase=%s,progress_rows=%s,
                        progress_bytes=%s,progress_total_rows=%s,progress_total_bytes=%s,
                        progress_updated_at=%s WHERE id=%s RETURNING *""",
                        (
                            phase,
                            progress_rows,
                            progress_bytes,
                            int(total_rows) if total_rows is not None else None,
                            int(total_bytes) if total_bytes is not None else None,
                            now,
                            task_id,
                        ),
                    ).fetchone()
                connection.execute(
                    """UPDATE ops.ingestion_run SET heartbeat_at=%s,
                    rows_discovered=CASE WHEN %s='acquire' THEN GREATEST(rows_discovered,%s)
                        ELSE rows_discovered END
                    WHERE id=%s""",
                    (
                        now,
                        task_stage,
                        int(progress.get("rows_processed", 0)) if progress else 0,
                        run_id,
                    ),
                )
            connection.commit()
        if row is None:
            raise LeaseConflictError("task lease is stale or owned by another worker")
        return _dict(row)

    def complete_task(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        rows_in: int,
        rows_out: int,
    ) -> JsonObject:
        return self._finish_task(
            task_id,
            worker_id=worker_id,
            lease_token=lease_token,
            status="succeeded",
            rows_in=rows_in,
            rows_out=rows_out,
            error=None,
        )

    def fail_task(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        error: Mapping[str, Any],
        retryable: bool,
    ) -> JsonObject:
        return self._finish_task(
            task_id,
            worker_id=worker_id,
            lease_token=lease_token,
            status="retry_wait" if retryable else "failed",
            rows_in=0,
            rows_out=0,
            error=error,
        )

    # Release metadata and bounded projections; publication transitions remain below.
    def _releases(self) -> _ReleaseRecords:
        records = getattr(self, "_release_records", None)
        if records is None:
            records = _ReleaseRecords(self)
            self._release_records = records
        return records

    def list_releases(
        self,
        *,
        status: str | None,
        dataset_id: str | None = None,
        target_feature: str | None = None,
        schema_version: str | None = None,
        ingestion_run_id: str | None = None,
        limit: int,
        offset: int,
    ) -> list[JsonObject]:
        return self._releases().list_releases(
            status=status,
            dataset_id=dataset_id,
            target_feature=target_feature,
            schema_version=schema_version,
            ingestion_run_id=ingestion_run_id,
            limit=limit,
            offset=offset,
        )

    def get_release(self, release_id: uuid.UUID) -> JsonObject:
        return self._releases().get_release(release_id)

    def release_artifact(self, release_id: uuid.UUID) -> JsonObject:
        return self._releases().release_artifact(release_id)

    def create_release(self, values: Mapping[str, Any]) -> JsonObject:
        return self._releases().create_release(values)

    def update_release(self, release_id: uuid.UUID, values: Mapping[str, Any]) -> JsonObject:
        return self._releases().update_release(release_id, values)

    def delete_release(self, release_id: uuid.UUID) -> None:
        self._releases().delete_release(release_id)

    def release_receipts(self, release_id: uuid.UUID) -> list[JsonObject]:
        return self._releases().release_receipts(release_id)

    def preview_release_records(
        self, release_id: uuid.UUID, *, limit: int, offset: int
    ) -> JsonObject:
        return self._releases().preview_release_records(release_id, limit=limit, offset=offset)

    def release_build_context(self, run_id: uuid.UUID) -> JsonObject:
        return self._releases().release_build_context(run_id)

    def release_product_records(
        self, release_id: uuid.UUID, *, limit: int, cursor: str | None
    ) -> JsonObject:
        return self._releases().release_product_records(release_id, limit=limit, cursor=cursor)

    def release_sales_source_records(
        self, release_id: uuid.UUID, *, year: int, limit: int, offset: int
    ) -> JsonObject:
        return self._releases().release_sales_source_records(
            release_id, year=year, limit=limit, offset=offset
        )

    def bind_release_export(self, release_id: uuid.UUID, values: Mapping[str, Any]) -> JsonObject:
        """Atomically bind the verified export and complete the candidate transition."""
        artifact_id = uuid.UUID(str(values["artifact_record_id"]))
        now = datetime.now(UTC)
        with self.connection() as connection:
            release = connection.execute(
                "SELECT * FROM ops.dataset_release WHERE id=%s FOR UPDATE", (release_id,)
            ).fetchone()
            if release is None:
                raise NotFoundError("record does not exist")
            artifact = connection.execute(
                "SELECT * FROM ops.artifact_record WHERE id=%s", (artifact_id,)
            ).fetchone()
            if artifact is None:
                raise NotFoundError("release export artifact does not exist")
            manifest = values.get("manifest")
            if not isinstance(manifest, dict):
                raise ConflictError("release export manifest is invalid")
            expected = (
                str(values["schema_version"]),
                str(values["content_sha256"]),
                int(values["record_count"]),
            )
            if release["status"] == "candidate":
                actual = (
                    str(release["schema_version"]),
                    str(release["content_sha256"]),
                    int(release["record_count"]),
                )
                persisted_manifest = dict(release["manifest_json"])
                replay_manifest = dict(manifest)
                persisted_manifest.pop("created_at", None)
                replay_manifest.pop("created_at", None)
                if (
                    actual != expected
                    or release["artifact_record_id"] != artifact_id
                    or persisted_manifest != replay_manifest
                ):
                    raise ConflictError(
                        "candidate release export replay conflicts with immutable evidence"
                    )
                return _dict(release)
            if release["status"] != "draft":
                raise ConflictError("only a draft release can bind an export")
            if artifact["ingestion_run_id"] != release["ingestion_run_id"]:
                raise ConflictError("release export belongs to another candidate generation")
            if artifact["artifact_kind"] != "release_export":
                raise ConflictError("release artifact is not a release export")
            if (
                artifact["schema_version"] != expected[0]
                or artifact["content_sha256"] != expected[1]
                or int(artifact["bytes"]) != int(manifest.get("byte_count", -1))
                or manifest.get("content_sha256") != expected[1]
                or int(manifest.get("record_count", -1)) != expected[2]
                or manifest.get("product_schema_version") != expected[0]
                or str(manifest.get("release_id")) != str(release_id)
            ):
                raise ConflictError(
                    "release export artifact, manifest, and requested binding disagree"
                )
            blocking = connection.execute(
                """SELECT count(*) FILTER (WHERE severity='blocking') AS total,
                count(*) FILTER (WHERE severity='blocking' AND status='pass') AS passed
                FROM ops.quality_result WHERE dataset_release_id=%s""",
                (release_id,),
            ).fetchone()
            if (
                blocking is None
                or int(blocking["total"]) == 0
                or int(blocking["passed"]) != int(blocking["total"])
            ):
                raise ConflictError(
                    "release cannot become candidate until every registered blocking gate passes"
                )
            row = connection.execute(
                """UPDATE ops.dataset_release SET schema_version=%s,record_count=%s,
                content_sha256=%s,artifact_record_id=%s,manifest_json=%s,status='candidate',
                updated_at=%s,version=version+1 WHERE id=%s AND status='draft' RETURNING *""",
                (
                    expected[0],
                    expected[2],
                    expected[1],
                    artifact_id,
                    _json(manifest),
                    now,
                    release_id,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise ConflictError("release export binding lost its version race")
        return _dict(row)

    def record_publication_receipt(
        self, release_id: uuid.UUID, values: Mapping[str, Any]
    ) -> tuple[JsonObject, bool]:
        """Persist one immutable consumer result before any accepted-pointer change."""
        self.get_release(release_id)
        existing = self._fetch_one(
            """SELECT * FROM ops.publication_receipt
            WHERE target_feature=%s AND consumer_operation_id=%s""",
            (values["target_feature"], values["consumer_operation_id"]),
        )
        if existing:
            if not _receipt_matches_values(existing, release_id, values):
                raise ConflictError("publication idempotency key arguments do not match")
            return existing, False
        now = datetime.now(UTC)
        try:
            with self.connection() as connection:
                row = connection.execute(
                    """INSERT INTO ops.publication_receipt (
                        id,dataset_release_id,target_feature,consumer_operation_id,status,
                        schema_version,content_sha256,rows_received,rows_accepted,rows_rejected,
                        error_json,request_id,created_at,completed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        uuid.uuid4(),
                        release_id,
                        values["target_feature"],
                        values["consumer_operation_id"],
                        values["status"],
                        values["schema_version"],
                        values["content_sha256"],
                        int(values["rows_received"]),
                        int(values["rows_accepted"]),
                        int(values["rows_rejected"]),
                        _json(values["error"]) if values.get("error") else None,
                        values["request_id"],
                        now,
                        None if values["status"] == "pending" else now,
                    ),
                ).fetchone()
                connection.commit()
        except errors.UniqueViolation:
            raced = self._fetch_one(
                """SELECT * FROM ops.publication_receipt
                WHERE target_feature=%s AND consumer_operation_id=%s""",
                (values["target_feature"], values["consumer_operation_id"]),
            )
            if raced is None or not _receipt_matches_values(raced, release_id, values):
                raise ConflictError("publication idempotency key arguments do not match") from None
            return raced, False
        return _dict(row), True

    def release_activations(self, release_id: uuid.UUID) -> list[JsonObject]:
        return self._fetch_all(
            """SELECT * FROM ops.release_activation WHERE dataset_release_id=%s
            ORDER BY requested_at""",
            (release_id,),
        )

    def create_release_activation(
        self, release_id: uuid.UUID, values: Mapping[str, Any]
    ) -> tuple[JsonObject, bool]:
        """Durably queue source-scale materialisation without changing the live pointer."""
        receipt_id = uuid.UUID(str(values["publication_receipt_id"]))
        expected_version = int(values["expected_release_version"])
        comment = str(values["comment"]).strip()
        idempotency_key = str(values["idempotency_key"]).strip()
        if not comment or not idempotency_key:
            raise ConflictError("activation comment and idempotency key are required")
        existing = self._fetch_one(
            "SELECT * FROM ops.release_activation WHERE idempotency_key=%s",
            (idempotency_key,),
        )
        if existing is not None:
            expected = (release_id, receipt_id, expected_version, comment)
            actual = (
                uuid.UUID(str(existing["dataset_release_id"])),
                uuid.UUID(str(existing["publication_receipt_id"])),
                int(existing["expected_release_version"]),
                str(existing["review_comment"]),
            )
            if actual != expected:
                raise ConflictError("activation idempotency key arguments do not match")
            return existing, False
        with self.connection() as connection:
            evidence = connection.execute(
                """SELECT release.*,receipt.id AS receipt_id,
                receipt.status AS receipt_status,receipt.schema_version AS receipt_schema_version,
                receipt.content_sha256 AS receipt_content_sha256,
                receipt.rows_received,receipt.rows_accepted,receipt.rows_rejected
                FROM ops.dataset_release release JOIN ops.publication_receipt receipt
                  ON receipt.dataset_release_id=release.id
                WHERE release.id=%s AND receipt.id=%s""",
                (release_id, receipt_id),
            ).fetchone()
            if evidence is None:
                raise NotFoundError("release or publication receipt does not exist")
            if evidence["status"] != "awaiting_review":
                raise ConflictError("only a release awaiting review can be activated")
            if int(evidence["version"]) != expected_version:
                raise ConflictError("release version does not match")
            if not _activation_receipt_matches(evidence):
                raise ConflictError("matching accepted consumer receipt is required")
            blocking = connection.execute(
                """SELECT count(*) AS count FROM ops.quality_result
                WHERE dataset_release_id=%s AND severity='blocking' AND status='fail'""",
                (release_id,),
            ).fetchone()
            if blocking and int(blocking["count"]):
                raise ConflictError("release has blocking quality failures")
            pending = connection.execute(
                """SELECT * FROM ops.release_activation
                WHERE dataset_release_id=%s AND expected_release_version=%s
                  AND status IN ('queued','claimed','running','interrupted')
                ORDER BY requested_at LIMIT 1 FOR UPDATE""",
                (release_id, expected_version),
            ).fetchone()
            if pending is not None:
                return _dict(pending), False
            now = datetime.now(UTC)
            try:
                row = connection.execute(
                    """INSERT INTO ops.release_activation (
                        id,dataset_release_id,publication_receipt_id,expected_release_version,
                        review_comment,status,attempt_number,idempotency_key,requested_at,version
                    ) VALUES (%s,%s,%s,%s,%s,'queued',1,%s,%s,1) RETURNING *""",
                    (
                        uuid.uuid4(),
                        release_id,
                        receipt_id,
                        expected_version,
                        comment,
                        idempotency_key,
                        now,
                    ),
                ).fetchone()
                connection.commit()
            except errors.UniqueViolation:
                connection.rollback()
                raced = self._fetch_one(
                    "SELECT * FROM ops.release_activation WHERE idempotency_key=%s",
                    (idempotency_key,),
                )
                if raced is None:
                    raced = self._required(
                        """SELECT * FROM ops.release_activation
                        WHERE dataset_release_id=%s AND expected_release_version=%s
                        ORDER BY requested_at DESC LIMIT 1""",
                        (release_id, expected_version),
                    )
                    return raced, False
                actual = (
                    uuid.UUID(str(raced["dataset_release_id"])),
                    uuid.UUID(str(raced["publication_receipt_id"])),
                    int(raced["expected_release_version"]),
                    str(raced["review_comment"]),
                )
                if actual != (release_id, receipt_id, expected_version, comment):
                    raise ConflictError(
                        "activation idempotency key arguments do not match"
                    ) from None
                return raced, False
        return _dict(row), True

    def get_release_activation(self, operation_id: uuid.UUID) -> JsonObject:
        return self._required("SELECT * FROM ops.release_activation WHERE id=%s", (operation_id,))

    def claim_release_activation(self, *, worker_id: str, lease_seconds: int) -> JsonObject | None:
        """Claim one activation, recovering an expired worker up to a bounded attempt limit."""
        now = datetime.now(UTC)
        token = uuid.uuid4().hex
        with self.connection() as connection:
            connection.execute(
                """UPDATE ops.release_activation SET status='failed',finished_at=%s,
                error_json=%s,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,version=version+1
                WHERE status IN ('claimed','running','interrupted')
                  AND (lease_expires_at IS NULL OR lease_expires_at<=%s)
                  AND attempt_number>=3""",
                (
                    now,
                    _json(
                        {
                            "code": "activation_retry_limit",
                            "message": "Publication activation exceeded its recovery limit",
                            "retryable": False,
                        }
                    ),
                    now,
                ),
            )
            row = connection.execute(
                """WITH candidate AS (
                    SELECT id,status FROM ops.release_activation
                    WHERE status='queued' OR (
                        status IN ('claimed','running','interrupted')
                        AND (lease_expires_at IS NULL OR lease_expires_at<=%s)
                        AND attempt_number<3
                    ) ORDER BY requested_at FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE ops.release_activation operation SET status='claimed',
                    attempt_number=CASE WHEN candidate.status='queued'
                        THEN operation.attempt_number ELSE operation.attempt_number+1 END,
                    lease_owner=%s,lease_token=%s,lease_expires_at=%s,heartbeat_at=%s,
                    started_at=COALESCE(operation.started_at,%s),version=operation.version+1
                FROM candidate WHERE operation.id=candidate.id RETURNING operation.*""",
                (
                    now,
                    worker_id,
                    token,
                    now + timedelta(seconds=lease_seconds),
                    now,
                    now,
                ),
            ).fetchone()
            connection.commit()
        return _dict(row) if row else None

    def heartbeat_release_activation(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> JsonObject:
        now = datetime.now(UTC)
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.release_activation SET status='running',heartbeat_at=%s,
                lease_expires_at=%s,version=version+1 WHERE id=%s AND lease_owner=%s
                AND lease_token=%s AND lease_expires_at>%s
                AND status IN ('claimed','running') RETURNING *""",
                (
                    now,
                    now + timedelta(seconds=lease_seconds),
                    operation_id,
                    worker_id,
                    lease_token,
                    now,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise LeaseConflictError("activation lease is stale or owned by another loader")
        return _dict(row)

    def update_release_activation_progress(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        phase_key: str,
        phase: str,
    ) -> JsonObject:
        """Persist the current indeterminate publication phase under the active lease."""
        now = datetime.now(UTC)
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.release_activation SET progress_phase_key=%s,progress_phase=%s,
                progress_updated_at=%s,heartbeat_at=%s,version=version+1
                WHERE id=%s AND lease_owner=%s AND lease_token=%s AND lease_expires_at>%s
                AND status IN ('claimed','running') RETURNING *""",
                (
                    phase_key[:100],
                    phase[:100],
                    now,
                    now,
                    operation_id,
                    worker_id,
                    lease_token,
                    now,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise LeaseConflictError("activation is not running")
        return _dict(row)

    def materialize_release_activation(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        stop_event: Event | None = None,
        lease_failed_event: Event | None = None,
    ) -> None:
        """Validate a queued activation while all release-scoped records remain isolated."""
        checked_at = datetime.now(UTC)
        with self.connection() as connection:
            work = connection.execute(
                """SELECT operation.*,release.dataset_id,release.target_feature,
            release.status AS release_status,release.version AS release_version
            FROM ops.release_activation operation JOIN ops.dataset_release release
              ON release.id=operation.dataset_release_id
            WHERE operation.id=%s AND operation.lease_owner=%s
              AND operation.lease_token=%s AND operation.lease_expires_at>%s
              AND operation.status IN ('claimed','running')""",
                (operation_id, worker_id, lease_token, checked_at),
            ).fetchone()
        if work is None:
            raise LeaseConflictError("activation lease is stale or owned by another loader")
        if work["release_status"] != "awaiting_review" or int(work["release_version"]) != int(
            work["expected_release_version"]
        ):
            raise ConflictError("release changed while publication was queued")

        # Keep the source-scale transaction independent from the activation row. The heartbeat
        # connection can therefore renew the lease while PostgreSQL populates accepted-only
        # indexes. If the process stops after this commit but before the marker below, recovery
        # safely repeats the published=FALSE update and then records materialisation.
        if work["dataset_id"] in {"gnaf-nsw", "fixture-property"}:
            with self.connection() as connection:
                stopped = Event()

                def monitor_stop() -> None:
                    if stop_event is None and lease_failed_event is None:
                        return
                    while not stopped.wait(0.5):
                        if (stop_event is not None and stop_event.is_set()) or (
                            lease_failed_event is not None and lease_failed_event.is_set()
                        ):
                            connection.cancel()
                            return

                watcher = Thread(
                    target=monitor_stop, name=f"activation-cancel-{operation_id}", daemon=True
                )
                watcher.start()
                try:
                    connection.execute(
                        """UPDATE warehouse.gnaf_address SET published=TRUE
                        WHERE dataset_release_id=%s AND published=FALSE""",
                        (work["dataset_release_id"],),
                    )
                    connection.commit()
                finally:
                    stopped.set()
                    watcher.join(timeout=2)

        materialized_at = datetime.now(UTC)
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.release_activation SET materialized_at=%s,version=version+1
                WHERE id=%s AND lease_owner=%s AND lease_token=%s
                  AND lease_expires_at>%s AND status IN ('claimed','running')
                RETURNING *""",
                (
                    materialized_at,
                    operation_id,
                    worker_id,
                    lease_token,
                    materialized_at,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise LeaseConflictError("activation lease is stale or owned by another loader")

    def finish_release_activation(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        status: str,
        error: Mapping[str, Any] | None,
    ) -> JsonObject:
        if status not in {*TERMINAL_ACTIVATION_STATES, "interrupted"}:
            raise ConflictError(
                "loader may finish activation only as succeeded, failed, or interrupted"
            )
        now = datetime.now(UTC)
        with self.connection() as connection:
            operation = connection.execute(
                """SELECT operation.*,release.dataset_id,release.target_feature,
                release.status AS release_status,release.version AS release_version,
                receipt.status AS receipt_status,receipt.schema_version AS receipt_schema_version,
                receipt.content_sha256 AS receipt_content_sha256,receipt.rows_received,
                receipt.rows_accepted,receipt.rows_rejected,release.schema_version,
                release.content_sha256,release.record_count
                FROM ops.release_activation operation JOIN ops.dataset_release release
                  ON release.id=operation.dataset_release_id
                JOIN ops.publication_receipt receipt
                  ON receipt.id=operation.publication_receipt_id
                WHERE operation.id=%s FOR UPDATE OF operation,release""",
                (operation_id,),
            ).fetchone()
            if operation is None:
                raise NotFoundError("activation does not exist")
            if operation["status"] == "succeeded" and status == "succeeded":
                return _dict(operation)
            if (
                operation["lease_owner"] != worker_id
                or operation["lease_token"] != lease_token
                or operation["lease_expires_at"] is None
                or operation["lease_expires_at"] <= now
            ):
                raise LeaseConflictError("activation lease is stale or owned by another loader")
            if status in {"failed", "interrupted"}:
                row = connection.execute(
                    """UPDATE ops.release_activation SET status=%s,finished_at=%s,
                    error_json=%s,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                    heartbeat_at=NULL,version=version+1 WHERE id=%s RETURNING *""",
                    (status, now, _json(error) if error else None, operation_id),
                ).fetchone()
                connection.commit()
                return _dict(row)
            if operation["materialized_at"] is None:
                raise ConflictError("activation materialisation has not completed")
            if operation["release_status"] != "awaiting_review" or int(
                operation["release_version"]
            ) != int(operation["expected_release_version"]):
                raise ConflictError("release changed while publication was queued")
            if not _activation_receipt_matches(operation):
                raise ConflictError("matching accepted consumer receipt is required")

            # Serialize only the final pointer switch. No source-scale DML runs while this
            # dataset-scoped lock or the accepted release row lock is held.
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"{operation['target_feature']}:{operation['dataset_id']}",),
            )
            predecessor = connection.execute(
                """SELECT id FROM ops.dataset_release WHERE dataset_id=%s AND target_feature=%s
                AND status='accepted' FOR UPDATE""",
                (operation["dataset_id"], operation["target_feature"]),
            ).fetchone()
            if predecessor:
                connection.execute(
                    """UPDATE ops.dataset_release SET status='superseded',updated_at=%s,
                    version=version+1 WHERE id=%s""",
                    (now, predecessor["id"]),
                )
            release = connection.execute(
                """UPDATE ops.dataset_release SET status='accepted',review_comment=%s,
                accepted_at=%s,supersedes_release_id=%s,updated_at=%s,version=version+1
                WHERE id=%s AND status='awaiting_review' AND version=%s RETURNING *""",
                (
                    operation["review_comment"],
                    now,
                    predecessor["id"] if predecessor else None,
                    now,
                    operation["dataset_release_id"],
                    operation["expected_release_version"],
                ),
            ).fetchone()
            if release is None:
                raise ConflictError("release version does not match")
            connection.execute(
                """INSERT INTO serving.accepted_generation
                (dataset_id,target_feature,dataset_release_id,activated_at,activated_by,version)
                VALUES (%s,%s,%s,%s,'reviewed-publication',1)
                ON CONFLICT (dataset_id,target_feature) DO UPDATE SET
                dataset_release_id=excluded.dataset_release_id,activated_at=excluded.activated_at,
                activated_by=excluded.activated_by,version=serving.accepted_generation.version+1""",
                (
                    operation["dataset_id"],
                    operation["target_feature"],
                    operation["dataset_release_id"],
                    now,
                ),
            )
            row = connection.execute(
                """UPDATE ops.release_activation SET status='succeeded',finished_at=%s,
                error_json=NULL,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,version=version+1 WHERE id=%s RETURNING *""",
                (now, operation_id),
            ).fetchone()
            connection.commit()
        return _dict(row)

    def transition_release(
        self, release_id: uuid.UUID, *, expected_version: int, target: str, comment: str
    ) -> JsonObject:
        allowed = {
            "draft": {"candidate"},
            "candidate": {"awaiting_review", "rejected"},
            "awaiting_review": {"accepted", "rejected"},
            "accepted": {"superseded"},
            "rejected": set(),
            "superseded": set(),
            "abandoned": set(),
        }
        current = self.get_release(release_id)
        if target not in allowed[str(current["status"])]:
            raise ConflictError(f"release cannot transition from {current['status']} to {target}")
        if target == "accepted":
            raise ConflictError("accepted publication must use the asynchronous activation queue")
        now = datetime.now(UTC)
        with self.connection() as connection:
            if target == "accepted":
                blocking = connection.execute(
                    """SELECT count(*) AS count FROM ops.quality_result
                    WHERE dataset_release_id=%s AND severity='blocking' AND status='fail'""",
                    (release_id,),
                ).fetchone()
                if blocking and blocking["count"]:
                    raise ConflictError("release has blocking quality failures")
                receipt = connection.execute(
                    """SELECT id FROM ops.publication_receipt WHERE dataset_release_id=%s
                    AND status='accepted' AND schema_version=%s AND content_sha256=%s
                    AND rows_received=%s AND rows_accepted=%s AND rows_rejected=0
                    ORDER BY completed_at DESC LIMIT 1""",
                    (
                        release_id,
                        current["schema_version"],
                        current["content_sha256"],
                        current["record_count"],
                        current["record_count"],
                    ),
                ).fetchone()
                if receipt is None:
                    raise ConflictError("matching accepted consumer receipt is required")
                predecessor = connection.execute(
                    """SELECT id FROM ops.dataset_release WHERE dataset_id=%s AND target_feature=%s
                    AND status='accepted' FOR UPDATE""",
                    (current["dataset_id"], current["target_feature"]),
                ).fetchone()
                if predecessor:
                    connection.execute(
                        "UPDATE ops.dataset_release SET status='superseded',updated_at=%s,version=version+1 WHERE id=%s",
                        (now, predecessor["id"]),
                    )
                    connection.execute(
                        """UPDATE serving.property_coverage SET coverage_status='stale',
                        checked_at=%s WHERE dataset_release_id=%s""",
                        (now, predecessor["id"]),
                    )
            row = connection.execute(
                """UPDATE ops.dataset_release SET status=%s,review_comment=%s,
                accepted_at=CASE WHEN %s='accepted' THEN %s ELSE accepted_at END,
                supersedes_release_id=CASE WHEN %s='accepted' THEN %s ELSE supersedes_release_id END,
                updated_at=%s,version=version+1 WHERE id=%s AND version=%s RETURNING *""",
                (
                    target,
                    comment,
                    target,
                    now,
                    target,
                    predecessor["id"] if target == "accepted" and predecessor else None,
                    now,
                    release_id,
                    expected_version,
                ),
            ).fetchone()
            if row is None:
                raise ConflictError("release version does not match")
            if target == "accepted":
                self._publish_address_property_spine(
                    connection,
                    release_id,
                    now,
                    identifier_scheme=(
                        "gnaf_pid" if current["dataset_id"] == "gnaf-nsw" else "fixture_pid"
                    ),
                )
                connection.execute(
                    """INSERT INTO serving.accepted_generation
                    (dataset_id,target_feature,dataset_release_id,activated_at,activated_by,version)
                    VALUES (%s,%s,%s,%s,'reviewed-publication',1)
                    ON CONFLICT (dataset_id,target_feature) DO UPDATE SET
                    dataset_release_id=excluded.dataset_release_id,activated_at=excluded.activated_at,
                    activated_by=excluded.activated_by,version=serving.accepted_generation.version+1""",
                    (current["dataset_id"], current["target_feature"], release_id, now),
                )
            connection.commit()
        return _dict(row)

    def _publish_address_property_spine(
        self,
        connection: Connection[Any],
        release_id: uuid.UUID,
        now: datetime,
        *,
        identifier_scheme: str,
        include_coverage: bool = True,
    ) -> None:
        """Materialise only an accepted address generation into stable property identities."""
        connection.execute(
            """INSERT INTO registry.property (
                property_ref,address_display,flat_type,unit_number,street_number_first,
                street_number_suffix,street_number_last,street_name,street_type,locality,
                postcode,state,address_search,geom,resolution_status,created_at,updated_at,version
            ) SELECT COALESCE(property_ref,md5('propertyscope-gnaf:' || gnaf_pid)::uuid),
                address_display,flat_type,
                unit_number,street_number_first,street_number_suffix,street_number_last,
                COALESCE(street_name,address_display),street_type,locality,postcode,'NSW',
                trim(regexp_replace(lower(address_display),'[^a-z0-9]+',' ','g')),geom,
                CASE WHEN source_status='CURRENT' THEN 'verified' ELSE 'retired' END,
                %s,%s,1
            FROM warehouse.gnaf_address WHERE dataset_release_id=%s
            ON CONFLICT (property_ref) DO UPDATE SET
                address_display=excluded.address_display,flat_type=excluded.flat_type,
                unit_number=excluded.unit_number,street_number_first=excluded.street_number_first,
                street_number_suffix=excluded.street_number_suffix,
                street_number_last=excluded.street_number_last,street_name=excluded.street_name,
                street_type=excluded.street_type,locality=excluded.locality,
                postcode=excluded.postcode,address_search=excluded.address_search,geom=excluded.geom,
                resolution_status=excluded.resolution_status,updated_at=excluded.updated_at,
                version=registry.property.version+1
            WHERE (registry.property.address_display,registry.property.flat_type,
                   registry.property.unit_number,registry.property.street_number_first,
                   registry.property.street_number_suffix,registry.property.street_number_last,
                   registry.property.street_name,registry.property.street_type,
                   registry.property.locality,registry.property.postcode,
                   registry.property.address_search,registry.property.geom,
                   registry.property.resolution_status)
              IS DISTINCT FROM
                  (excluded.address_display,excluded.flat_type,excluded.unit_number,
                   excluded.street_number_first,excluded.street_number_suffix,
                   excluded.street_number_last,excluded.street_name,excluded.street_type,
                   excluded.locality,excluded.postcode,excluded.address_search,excluded.geom,
                   excluded.resolution_status)""",
            (now, now, release_id),
        )
        connection.execute(
            """UPDATE registry.property_identifier identifier SET is_current=false,valid_to=%s::date
            FROM warehouse.gnaf_address address
            WHERE address.dataset_release_id=%s AND identifier.scheme=%s
              AND identifier.identifier_value=address.gnaf_pid AND identifier.is_current
              AND identifier.source_release_id<>%s""",
            (now, release_id, identifier_scheme, release_id),
        )
        connection.execute(
            """INSERT INTO registry.property_identifier (
                id,property_ref,scheme,identifier_value,source_release_id,is_current,
                valid_from,valid_to,match_method,match_confidence,evidence_json,created_at
            ) SELECT md5('propertyscope-' || %s || '-identifier:' || %s::text || ':' || gnaf_pid)::uuid,
                COALESCE(property_ref,md5('propertyscope-gnaf:' || gnaf_pid)::uuid),
                %s,gnaf_pid,%s,true,
                %s::date,NULL,'source-authoritative',1,
                jsonb_build_object('geocode_type',geocode_type,'source_crs',source_crs),%s
            FROM warehouse.gnaf_address WHERE dataset_release_id=%s
            ON CONFLICT (scheme,identifier_value,source_release_id) DO UPDATE SET is_current=true
            WHERE NOT registry.property_identifier.is_current""",
            (
                identifier_scheme,
                release_id,
                identifier_scheme,
                release_id,
                now,
                now,
                release_id,
            ),
        )
        # The stable UUID is deterministic and every downstream statement already derives it
        # with COALESCE. Persisting the same value back into a source-scale immutable warehouse
        # generation rewrote millions of tuples and all related indexes during publication.
        # Keep the warehouse generation immutable and derive the registry key at this boundary.
        if include_coverage:
            connection.execute(
                """INSERT INTO serving.property_coverage (
                property_ref,dataset_id,target_feature,dataset_release_id,coverage_status,
                coverage_scope,checked_at
            ) SELECT COALESCE(address.property_ref,
                md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid),
                release.dataset_id,release.target_feature,release.id,'supported',
                release.coverage_json,%s
            FROM warehouse.gnaf_address address JOIN ops.dataset_release release
              ON release.id=address.dataset_release_id
            WHERE address.dataset_release_id=%s
            ON CONFLICT (property_ref,dataset_id,target_feature) DO UPDATE SET
                dataset_release_id=excluded.dataset_release_id,
                coverage_status=excluded.coverage_status,
                coverage_scope=excluded.coverage_scope,checked_at=excluded.checked_at
            WHERE (serving.property_coverage.dataset_release_id,
                   serving.property_coverage.coverage_status,
                   serving.property_coverage.coverage_scope)
              IS DISTINCT FROM
                  (excluded.dataset_release_id,excluded.coverage_status,
                   excluded.coverage_scope)""",
                (now, release_id),
            )

    # Property discovery reads only accepted serving evidence.
    def _properties(self) -> _CanonicalPropertyReads:
        reads = getattr(self, "_property_reads", None)
        if reads is None:
            reads = _CanonicalPropertyReads(self)
            self._property_reads = reads
        return reads

    def search_properties(
        self, query: str, *, state: str, limit: int, offset: int = 0
    ) -> PropertySearchResults:
        return self._properties().search_properties(query, state=state, limit=limit, offset=offset)

    def property_snapshot(self, property_ref: uuid.UUID) -> JsonObject:
        return self._properties().property_snapshot(property_ref)

    def property_coverage(self, property_ref: uuid.UUID) -> list[JsonObject]:
        return self._properties().property_coverage(property_ref)

    def overview(self) -> JsonObject:
        with self.connection() as connection:
            runs = connection.execute(
                "SELECT status,count(*) AS count FROM ops.ingestion_run GROUP BY status ORDER BY status"
            ).fetchall()
            releases = connection.execute(
                "SELECT status,count(*) AS count FROM ops.dataset_release GROUP BY status ORDER BY status"
            ).fetchall()
            failed_checks = connection.execute(
                "SELECT count(*) AS count FROM ops.quality_result WHERE status='fail'"
            ).fetchone()
            properties = connection.execute(
                """SELECT COALESCE(max(CASE
                    WHEN release.dataset_id IN ('gnaf-nsw','fixture-property')
                    THEN COALESCE(NULLIF(release.coverage_json->>'source_record_count','')::bigint,
                                  release.record_count)
                    END),0) AS count
                FROM serving.accepted_generation accepted
                JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id"""
            ).fetchone()
        return {
            "runs": _rows(runs),
            "releases": _rows(releases),
            "failed_quality_checks": int(failed_checks["count"]) if failed_checks else 0,
            "properties": int(properties["count"]) if properties else 0,
        }

    # Registered asynchronous imports; callers provide IDs and registry keys, never SQL or paths.
    def _imports(self) -> _RegisteredImportOperations:
        operations = getattr(self, "_import_operations", None)
        if operations is None:
            operations = _RegisteredImportOperations(self)
            self._import_operations = operations
        return operations

    def create_import(self, values: Mapping[str, Any]) -> tuple[JsonObject, bool]:
        return self._imports().create_import(values)

    def get_import(self, operation_id: uuid.UUID) -> JsonObject:
        return self._imports().get_import(operation_id)

    def import_work(self, operation_id: uuid.UUID) -> JsonObject:
        """Return the fixed registered operation plus verified artifact metadata for the loader."""
        return self._imports().import_work(operation_id)

    def execute_import_profile(
        self,
        work: Mapping[str, Any],
        prepared: PreparedImport,
        *,
        phase_callback: Any | None = None,
        lease_failed_event: Event | None = None,
        stop_event: Event | None = None,
    ) -> ImportResult:
        """Execute one registered COPY/import profile inside the credential boundary."""
        return self._imports().execute_import_profile(
            work,
            prepared,
            phase_callback=phase_callback,
            lease_failed_event=lease_failed_event,
            stop_event=stop_event,
        )

    def execute_stream_import_profile(
        self,
        work: Mapping[str, Any],
        *,
        profile: str,
        rows: Any,
        verify_complete: Any | None = None,
        phase_callback: Any | None = None,
        lease_failed_event: Event | None = None,
        stop_event: Event | None = None,
    ) -> ImportResult:
        """Execute a source-scale streaming COPY inside the credential boundary."""
        return self._imports().execute_stream_import_profile(
            work,
            profile=profile,
            rows=rows,
            verify_complete=verify_complete,
            phase_callback=phase_callback,
            lease_failed_event=lease_failed_event,
            stop_event=stop_event,
        )

    def update_import_progress(
        self,
        operation_id: uuid.UUID,
        *,
        phase_key: str,
        phase: str,
        rows_processed: int,
        bytes_processed: int,
        total_rows: int | None = None,
        total_bytes: int | None = None,
    ) -> None:
        """Persist throttled loader progress and make it effective run activity."""
        self._imports().update_import_progress(
            operation_id,
            phase_key=phase_key,
            phase=phase,
            rows_processed=rows_processed,
            bytes_processed=bytes_processed,
            total_rows=total_rows,
            total_bytes=total_bytes,
        )

    def recover_import_space(self, operation_id: uuid.UUID) -> JsonObject:
        """Reclaim reusable space on the exact relations owned by a failed import profile."""
        return self._imports().recover_import_space(operation_id)

    @contextmanager
    def _cancellable_import_connection(
        self,
        operation_id: uuid.UUID,
        *,
        lease_failed_event: Event | None = None,
        stop_event: Event | None = None,
    ) -> Iterator[Connection[Any]]:
        """Cancel an in-flight PostgreSQL statement when its owning run is cancelled."""
        with self._imports().cancellable_connection(
            operation_id,
            lease_failed_event=lease_failed_event,
            stop_event=stop_event,
        ) as connection:
            yield connection

    def import_cancel_requested(self, operation_id: uuid.UUID) -> bool:
        return self._imports().import_cancel_requested(operation_id)

    def enqueue_import(self, operation_id: uuid.UUID) -> JsonObject:
        return self._imports().enqueue_import(operation_id)

    def cancel_import(self, operation_id: uuid.UUID) -> JsonObject:
        return self._imports().cancel_import(operation_id)

    def claim_import(self, *, worker_id: str, lease_seconds: int) -> JsonObject | None:
        return self._imports().claim_import(worker_id=worker_id, lease_seconds=lease_seconds)

    def heartbeat_import(
        self, operation_id: uuid.UUID, *, worker_id: str, lease_token: str, lease_seconds: int
    ) -> JsonObject:
        return self._imports().heartbeat_import(
            operation_id,
            worker_id=worker_id,
            lease_token=lease_token,
            lease_seconds=lease_seconds,
        )

    def finish_import(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        status: str,
        counts: Mapping[str, int],
        result: Mapping[str, Any] | None,
        error: Mapping[str, Any] | None,
    ) -> JsonObject:
        return self._imports().finish_import(
            operation_id,
            worker_id=worker_id,
            lease_token=lease_token,
            status=status,
            counts=counts,
            result=result,
            error=error,
        )

    def register_artifact(self, values: Mapping[str, Any]) -> tuple[JsonObject, bool]:
        lineage_query = """SELECT * FROM ops.artifact_record WHERE ingestion_run_id=%s
            AND logical_key=%s AND artifact_kind=%s"""
        lineage_params = (
            uuid.UUID(str(values["ingestion_run_id"])),
            values["logical_key"],
            values["artifact_kind"],
        )
        existing = self._fetch_one(
            lineage_query,
            lineage_params,
        )
        if existing:
            _validate_artifact_replay(existing, values)
            self._persist_source_snapshot(values)
            return existing, False
        try:
            with self.connection() as connection:
                row = connection.execute(
                    """INSERT INTO ops.artifact_record (
                        id,ingestion_run_id,run_task_id,logical_key,artifact_kind,storage_key,
                        source_uri_redacted,content_sha256,media_type,bytes,etag,source_last_modified,
                        schema_version,retention_class,created_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                    (
                        uuid.uuid4(),
                        uuid.UUID(str(values["ingestion_run_id"])),
                        uuid.UUID(str(values["run_task_id"]))
                        if values.get("run_task_id")
                        else None,
                        values["logical_key"],
                        values["artifact_kind"],
                        values["storage_key"],
                        values.get("source_uri_redacted"),
                        values["content_sha256"],
                        values["media_type"],
                        int(values["bytes"]),
                        values.get("etag"),
                        values.get("source_last_modified"),
                        values.get("schema_version"),
                        values["retention_class"],
                        datetime.now(UTC),
                    ),
                ).fetchone()
                if values["artifact_kind"] == "source_snapshot":
                    snapshot = _source_snapshot(values)
                    connection.execute(
                        "UPDATE ops.ingestion_run SET source_snapshot_json=%s WHERE id=%s",
                        (_json(snapshot), lineage_params[0]),
                    )
                connection.commit()
        except errors.UniqueViolation:
            # A concurrent delivery can win the lineage key between the optimistic
            # read and insert. Return it only when the replay arguments are identical.
            existing = self._required(lineage_query, lineage_params)
            _validate_artifact_replay(existing, values)
            self._persist_source_snapshot(values)
            return existing, False
        return _dict(row), True

    def _persist_source_snapshot(self, values: Mapping[str, Any]) -> None:
        if values["artifact_kind"] != "source_snapshot":
            return
        snapshot = _source_snapshot(values)
        run_id = uuid.UUID(str(values["ingestion_run_id"]))
        current = self._required(
            "SELECT source_snapshot_json FROM ops.ingestion_run WHERE id=%s", (run_id,)
        )
        if current.get("source_snapshot_json") is not None:
            if current["source_snapshot_json"] != snapshot:
                raise ConflictError("source snapshot replay evidence does not match")
            return
        with self.connection() as connection:
            connection.execute(
                "UPDATE ops.ingestion_run SET source_snapshot_json=%s WHERE id=%s",
                (_json(snapshot), run_id),
            )
            connection.commit()

    def _finish_task(
        self,
        task_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        status: str,
        rows_in: int,
        rows_out: int,
        error: Mapping[str, Any] | None,
    ) -> JsonObject:
        now = datetime.now(UTC)
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.run_task SET status=%s,rows_in=%s,rows_out=%s,error_json=%s,
                progress_rows=CASE WHEN %s='succeeded' THEN %s ELSE progress_rows END,
                progress_total_rows=CASE WHEN %s='succeeded'
                    THEN COALESCE(progress_total_rows,%s) ELSE progress_total_rows END,
                progress_updated_at=CASE WHEN %s='succeeded' THEN %s ELSE progress_updated_at END,
                finished_at=CASE WHEN %s IN ('succeeded','failed','cancelled','skipped') THEN %s ELSE NULL END,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                updated_at=%s,version=version+1 WHERE id=%s AND lease_owner=%s AND lease_token=%s
                AND lease_expires_at>%s AND status IN ('claimed','running') RETURNING *""",
                (
                    status,
                    rows_in,
                    rows_out,
                    _json(error) if error else None,
                    status,
                    rows_out,
                    status,
                    rows_out,
                    status,
                    now,
                    status,
                    now,
                    now,
                    task_id,
                    worker_id,
                    lease_token,
                    now,
                ),
            ).fetchone()
            if row is None:
                raise LeaseConflictError("task lease is stale or owned by another worker")
            run_id = row["ingestion_run_id"]
            cancellation = connection.execute(
                "SELECT cancel_requested_at FROM ops.ingestion_run WHERE id=%s FOR UPDATE",
                (run_id,),
            ).fetchone()
            if cancellation and cancellation["cancel_requested_at"] is not None:
                connection.execute(
                    """UPDATE ops.run_task SET status='cancelled',finished_at=%s,updated_at=%s,
                    error_json=COALESCE(error_json,%s),version=version+1
                    WHERE ingestion_run_id=%s AND status IN ('pending','retry_wait')""",
                    (now, now, _json(_cancellation_error()), run_id),
                )
                connection.execute(
                    """UPDATE ops.ingestion_run SET status='cancelled',finished_at=%s,error_json=%s,
                    rows_discovered=COALESCE((SELECT max(rows_out) FROM ops.run_task
                        WHERE ingestion_run_id=%s AND stage='acquire' AND status='succeeded'),
                        rows_discovered),lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL
                    WHERE id=%s""",
                    (now, _json(_cancellation_error()), run_id, run_id),
                )
            elif status == "retry_wait":
                connection.execute(
                    """UPDATE ops.ingestion_run SET status='interrupted',finished_at=NULL,error_json=%s,
                    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE id=%s
                    AND status NOT IN ('succeeded','failed','cancelled')""",
                    (
                        _json(
                            {
                                "code": "task_retry_wait",
                                "message": "Retryable task failed; explicit resume is required",
                                "retryable": True,
                            }
                        ),
                        run_id,
                    ),
                )
            elif status == "failed":
                connection.execute(
                    """UPDATE ops.ingestion_run SET status='failed',finished_at=%s,error_json=%s,
                    rows_discovered=COALESCE((SELECT max(rows_out) FROM ops.run_task
                        WHERE ingestion_run_id=%s AND stage='acquire' AND status='succeeded'),
                        rows_discovered),lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE id=%s
                    AND status NOT IN ('succeeded','failed','cancelled')""",
                    (
                        now,
                        _json(error) if error else _json({"code": "task_failed"}),
                        run_id,
                        run_id,
                    ),
                )
                connection.execute(
                    """UPDATE ops.dataset_release SET status='abandoned',terminal_reason_json=%s,
                    review_comment='System-terminalized failed ingestion candidate; retained for audit.',
                    updated_at=%s,version=version+1
                    WHERE ingestion_run_id=%s AND status IN ('draft','candidate')""",
                    (
                        _json(
                            {
                                "code": "ingestion_failed",
                                "message": "Candidate release abandoned after ingestion failure",
                                "ingestion_run_id": str(run_id),
                                "bounded_error": dict(error or {"code": "task_failed"}),
                            }
                        ),
                        now,
                        run_id,
                    ),
                )
            elif status == "succeeded":
                remaining = connection.execute(
                    """SELECT count(*) AS count FROM ops.run_task
                    WHERE ingestion_run_id=%s AND status NOT IN ('succeeded','skipped')""",
                    (run_id,),
                ).fetchone()
                if remaining is not None and int(remaining["count"]) == 0:
                    connection.execute(
                        """UPDATE ops.ingestion_run SET status='succeeded',finished_at=%s,
                        rows_discovered=COALESCE(
                            (SELECT max(rows_out) FROM ops.run_task
                                WHERE ingestion_run_id=%s AND stage='acquire'
                                  AND status='succeeded'),
                            (SELECT max(rows_in) FROM ops.run_task
                                WHERE ingestion_run_id=%s AND stage='import'
                                  AND status='succeeded'),0),
                        rows_staged=(SELECT COALESCE(max(rows_in),0) FROM ops.run_task
                            WHERE ingestion_run_id=%s AND stage='import'),
                        rows_accepted=(SELECT COALESCE(max(rows_out),0) FROM ops.run_task
                            WHERE ingestion_run_id=%s AND stage='import')
                        WHERE id=%s AND status NOT IN ('failed','cancelled')""",
                        (now, run_id, run_id, run_id, run_id, run_id),
                    )
                else:
                    stage_status = run_status_for_stage(str(row["stage"]))
                    connection.execute(
                        """UPDATE ops.ingestion_run SET status=%s,heartbeat_at=%s,
                        rows_discovered=CASE WHEN %s='acquire' THEN GREATEST(rows_discovered,%s)
                            ELSE rows_discovered END,
                        rows_staged=CASE WHEN %s='import' THEN GREATEST(rows_staged,%s)
                            ELSE rows_staged END,
                        rows_accepted=CASE WHEN %s='import' THEN GREATEST(rows_accepted,%s)
                            ELSE rows_accepted END WHERE id=%s""",
                        (
                            stage_status,
                            now,
                            row["stage"],
                            rows_out,
                            row["stage"],
                            rows_in,
                            row["stage"],
                            rows_out,
                            run_id,
                        ),
                    )
            connection.commit()
        return _dict(row)

    def _delete(self, schema_name: str, table_name: str, aggregate_id: uuid.UUID) -> None:
        with self.connection() as connection:
            row = connection.execute(
                sql.SQL("DELETE FROM {}.{} WHERE id=%s RETURNING id").format(
                    sql.Identifier(schema_name), sql.Identifier(table_name)
                ),
                (aggregate_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError("record does not exist")
            connection.commit()

    def _fetch_one(self, query: str, params: Sequence[Any]) -> JsonObject | None:
        with self.connection() as connection:
            row = connection.execute(query, params).fetchone()
        return _dict(row) if row else None

    def _required(self, query: str, params: Sequence[Any]) -> JsonObject:
        result = self._fetch_one(query, params)
        if result is None:
            raise NotFoundError("record does not exist")
        return result

    def _fetch_all(self, query: str, params: Sequence[Any]) -> list[JsonObject]:
        with self.connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return _rows(rows)


def _is_complete_acquisition_scope(scope: Mapping[str, Any]) -> bool:
    subset_fields = {
        "geography_kind",
        "geography_values",
        "localities",
        "maximum_records",
        "scenario",
        "source_year",
        "start_month",
        "end_month",
        "years",
        "weeks",
    }
    return (
        scope.get("profile") == "full-data"
        and scope.get("all_records") is True
        and not subset_fields.intersection(scope)
    )
