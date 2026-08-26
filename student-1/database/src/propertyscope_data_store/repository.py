"""PostgreSQL repository and atomic state/lease operations."""

# SQL statements stay line-oriented so schema and transition policies remain reviewable.
# ruff: noqa: E501

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any

from psycopg import Connection, errors, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from propertyscope_data_store.errors import (
    ConflictError,
    LeaseConflictError,
    NotFoundError,
    ValidationError,
)
from propertyscope_data_store.import_profiles import (
    ImportResult,
    PreparedImport,
    execute_import,
    execute_stream_import,
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
from propertyscope_data_store.query_specs import (
    PREVIEW_SPECS,
    normalise_product_rows,
    release_product_query,
)

JsonObject = dict[str, Any]
PROPERTY_SEARCH_CANDIDATE_LIMIT = 500
PROPERTY_SEARCH_UNDERSPECIFIED_TERMS = frozenset(
    {
        "australia",
        "nsw",
        "street",
        "st",
        "road",
        "rd",
        "avenue",
        "ave",
        "drive",
        "dr",
        "lane",
        "ln",
        "court",
        "ct",
        "place",
        "pl",
        "highway",
        "hwy",
        "unit",
        "lot",
    }
)
TERMINAL_TASK_STATES = frozenset({"succeeded", "failed", "cancelled", "skipped"})
TERMINAL_IMPORT_STATES = frozenset({"succeeded", "failed", "cancelled"})
TERMINAL_ACTIVATION_STATES = frozenset({"succeeded", "failed"})


@dataclass(frozen=True)
class PropertySearchResults:
    """A bounded property-search page plus the number of matching properties."""

    items: list[JsonObject]
    total: int
    total_is_lower_bound: bool = False


def _normalise_property_query(query: str) -> str:
    """Align user input with the punctuation-neutral registry search documents."""

    return re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()


def _property_query_is_underspecified(normalised: str) -> bool:
    """Reject common address vocabulary that cannot selectively identify a property."""

    tokens = tuple(normalised.split())
    distinctive = tuple(
        token for token in tokens if token not in PROPERTY_SEARCH_UNDERSPECIFIED_TERMS
    )
    if not distinctive:
        return bool(tokens)
    return len(distinctive) == 1 and distinctive[0].isalpha() and len(distinctive[0]) < 8


def _activation_receipt_matches(evidence: Mapping[str, Any]) -> bool:
    return (
        evidence.get("receipt_status") == "accepted"
        and evidence.get("receipt_schema_version") == evidence.get("schema_version")
        and evidence.get("receipt_content_sha256") == evidence.get("content_sha256")
        and int(evidence.get("rows_received", -1)) == int(evidence.get("record_count", -2))
        and int(evidence.get("rows_accepted", -1)) == int(evidence.get("record_count", -2))
        and int(evidence.get("rows_rejected", -1)) == 0
    )


class PropertyScopeStore:
    """Exclusive persistence facade for Feature 1 PostgreSQL/PostGIS."""

    def __init__(self, database_url: str, *, open_pool: bool = True) -> None:
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
            yield connection

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
        columns = (
            "source_definition_id",
            "name",
            "profile_key",
            "profile_version",
            "adapter_key",
            "release_builder_key",
            "import_profile_key",
            "import_profile_version",
            "target_feature",
            "dataset_id",
            "refresh_strategy",
            "default_run_mode",
            "scope_json",
            "quality_policy_key",
            "quality_policy_version",
            "max_parallelism",
            "timeout_seconds",
            "max_objects",
            "max_bytes",
            "max_rows",
            "status",
            "schedule_text",
        )
        parameters = [values[name] for name in columns]
        parameters[12] = _json(parameters[12])
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
            "scope_json",
            "max_parallelism",
            "timeout_seconds",
            "max_objects",
            "max_bytes",
            "max_rows",
            "status",
            "schedule_text",
        )
        merged = {name: values.get(name, current[name]) for name in editable}
        with self.connection() as connection:
            row = connection.execute(
                """
                UPDATE ops.job_definition SET name=%s,scope_json=%s,max_parallelism=%s,
                    timeout_seconds=%s,max_objects=%s,max_bytes=%s,max_rows=%s,status=%s,
                    schedule_text=%s,updated_at=%s,version=version+1
                WHERE id=%s AND version=%s RETURNING *
                """,
                (
                    merged["name"],
                    _json(merged["scope_json"]),
                    merged["max_parallelism"],
                    merged["timeout_seconds"],
                    merged["max_objects"],
                    merged["max_bytes"],
                    merged["max_rows"],
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
                    ) VALUES (%s,%s,%s,'1.0.0','1.0.0',%s,'1.0.0',%s,%s,%s,%s,%s,%s,'queued',%s,%s,%s)
                    RETURNING *
                    """,
                    (
                        run_id,
                        job_id,
                        job["source_definition_id"],
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

    def request_cancel(self, run_id: uuid.UUID) -> JsonObject:
        now = datetime.now(UTC)
        with self.connection() as connection:
            run = connection.execute(
                "SELECT * FROM ops.ingestion_run WHERE id=%s FOR UPDATE", (run_id,)
            ).fetchone()
            if run is None:
                raise NotFoundError("record does not exist")
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
                """UPDATE ops.ingestion_run SET cancel_requested_at=COALESCE(cancel_requested_at,%s),
                status=CASE WHEN %s THEN 'cancelled' ELSE status END,
                finished_at=CASE WHEN %s THEN %s ELSE finished_at END,
                error_json=CASE WHEN %s THEN %s ELSE error_json END,
                lease_owner=CASE WHEN %s THEN NULL ELSE lease_owner END,
                lease_token=CASE WHEN %s THEN NULL ELSE lease_token END,
                lease_expires_at=CASE WHEN %s THEN NULL ELSE lease_expires_at END
                WHERE id=%s RETURNING *""",
                (
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
                    job.dataset_id,job.target_feature,job.source_definition_id,
                    job.max_bytes,job.max_rows,job.timeout_seconds
                    FROM ops.ingestion_run run JOIN ops.job_definition job
                    ON job.id=run.job_definition_id WHERE run.id=%s""",
                    (row["ingestion_run_id"],),
                ).fetchone()
                if context:
                    row.update(context)
            connection.commit()
        return _dict(row) if row else None

    def heartbeat_task(
        self, task_id: uuid.UUID, *, worker_id: str, lease_token: str, lease_seconds: int
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

    # Release lifecycle and evidence.
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
        query = """SELECT release.* FROM ops.dataset_release release
        JOIN ops.source_definition source ON source.id=release.source_definition_id"""
        params: list[Any] = []
        predicates: list[str] = ["source.status<>'retired'"]
        if status:
            predicates.append("release.status=%s")
            params.append(status)
        for column, value in (
            ("dataset_id", dataset_id),
            ("target_feature", target_feature),
            ("schema_version", schema_version),
            ("ingestion_run_id", ingestion_run_id),
        ):
            if value:
                predicates.append(f"release.{column}=%s")
                params.append(value)
        query += " WHERE " + " AND ".join(predicates)
        query += " ORDER BY release.created_at DESC LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        return self._fetch_all(query, params)

    def get_release(self, release_id: uuid.UUID) -> JsonObject:
        return self._required("SELECT * FROM ops.dataset_release WHERE id=%s", (release_id,))

    def release_artifact(self, release_id: uuid.UUID) -> JsonObject:
        return self._required(
            """SELECT artifact.*,
            release.manifest_json->>'redistribution_decision' AS redistribution_policy,
            release.status AS release_status
            FROM ops.dataset_release release
            JOIN ops.artifact_record artifact ON artifact.id=release.artifact_record_id
            WHERE release.id=%s""",
            (release_id,),
        )

    def create_release(self, values: Mapping[str, Any]) -> JsonObject:
        if values.get("status", "draft") != "draft":
            raise ConflictError("new releases must begin as drafts")
        now = datetime.now(UTC)
        try:
            with self.connection() as connection:
                row = connection.execute(
                    """INSERT INTO ops.dataset_release (
                    id,dataset_id,source_definition_id,ingestion_run_id,target_feature,
                    release_version,schema_version,coverage_json,record_count,content_sha256,
                    artifact_record_id,manifest_json,status,review_comment,created_at,updated_at,version
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1) RETURNING *""",
                    (
                        uuid.UUID(str(values.get("id", uuid.uuid4()))),
                        values["dataset_id"],
                        uuid.UUID(str(values["source_definition_id"])),
                        uuid.UUID(str(values["ingestion_run_id"])),
                        values["target_feature"],
                        values["release_version"],
                        values["schema_version"],
                        _json(values.get("coverage", {})),
                        int(values.get("record_count", 0)),
                        values["content_sha256"],
                        uuid.UUID(str(values["artifact_record_id"])),
                        _json(values.get("manifest", {})),
                        values.get("status", "draft"),
                        values.get("review_comment"),
                        now,
                        now,
                    ),
                ).fetchone()
                connection.commit()
        except errors.UniqueViolation as exc:
            raise ConflictError("release version already exists for this dataset") from exc
        except errors.ForeignKeyViolation as exc:
            raise NotFoundError("source, run, or artifact does not exist") from exc
        return _dict(row)

    def update_release(self, release_id: uuid.UUID, values: Mapping[str, Any]) -> JsonObject:
        current = self.get_release(release_id)
        if current["status"] != "draft":
            raise ConflictError("bound candidate and terminal release evidence is immutable")
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.dataset_release SET release_version=%s,schema_version=%s,
                coverage_json=%s,record_count=%s,content_sha256=%s,manifest_json=%s,
                review_comment=%s,updated_at=%s,version=version+1 WHERE id=%s AND version=%s
                AND status='draft' RETURNING *""",
                (
                    values.get("release_version", current["release_version"]),
                    values.get("schema_version", current["schema_version"]),
                    _json(values.get("coverage", current["coverage_json"])),
                    int(values.get("record_count", current["record_count"])),
                    values.get("content_sha256", current["content_sha256"]),
                    _json(values.get("manifest", current["manifest_json"])),
                    values.get("review_comment", current["review_comment"]),
                    datetime.now(UTC),
                    release_id,
                    int(values["version"]),
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise ConflictError("release version does not match")
        return _dict(row)

    def delete_release(self, release_id: uuid.UUID) -> None:
        release = self.get_release(release_id)
        if release["status"] not in {"draft", "rejected"}:
            raise ConflictError("only draft or rejected local releases can be deleted")
        try:
            self._delete("ops", "dataset_release", release_id)
        except errors.ForeignKeyViolation as exc:
            raise ConflictError(
                "release has retained quality, receipt, or registry evidence"
            ) from exc

    def release_receipts(self, release_id: uuid.UUID) -> list[JsonObject]:
        self.get_release(release_id)
        return self._fetch_all(
            "SELECT * FROM ops.publication_receipt WHERE dataset_release_id=%s ORDER BY created_at",
            (release_id,),
        )

    def preview_release_records(
        self, release_id: uuid.UUID, *, limit: int, offset: int
    ) -> JsonObject:
        """Return a bounded, allowlisted projection of one isolated release generation."""
        context = self._required(
            """SELECT release.id,release.dataset_id,release.release_version,release.status,
            release.record_count,release.coverage_json,job.import_profile_key
            FROM ops.dataset_release release
            JOIN ops.ingestion_run run ON run.id=release.ingestion_run_id
            JOIN ops.job_definition job ON job.id=run.job_definition_id
            WHERE release.id=%s""",
            (release_id,),
        )
        profile = str(context["import_profile_key"])
        spec = PREVIEW_SPECS.get(profile)
        if spec is None:
            raise ConflictError("release import profile does not support bounded preview")
        coverage = context.get("coverage_json")
        release_scope = (
            coverage.get("release_scope", coverage) if isinstance(coverage, Mapping) else None
        )
        has_registered_bound = (
            isinstance(release_scope, Mapping)
            and isinstance(release_scope.get("maximum_records"), int)
            and not isinstance(release_scope.get("maximum_records"), bool)
        )
        if profile != "bocsar-sparse" and has_registered_bound and isinstance(coverage, Mapping):
            query = release_product_query(profile, release_id, coverage, limit=limit, offset=offset)
            projected = self._fetch_all(query.select_sql, query.select_params)
            items = [
                {column: row[column] for column in spec.columns if column in row}
                for row in projected
            ]
            total_row = self._required(query.count_sql, query.count_params)
        else:
            # Historical seed releases predate explicit product scopes. BOCSAR's
            # preview intentionally remains observation-oriented while its export
            # aggregates those observations into coverage-aware series.
            items = self._fetch_all(spec.select_sql, (release_id, limit, offset))
            total_row = self._required(spec.count_sql, (release_id,))
        return {
            "release": {
                key: context[key]
                for key in ("id", "dataset_id", "release_version", "status", "record_count")
            },
            "profile": profile,
            "columns": list(spec.columns),
            "items": items,
            "count": len(items),
            "total": int(total_row["count"]),
            "limit": limit,
            "offset": offset,
            "next_offset": offset + len(items)
            if offset + len(items) < int(total_row["count"])
            else None,
        }

    def release_build_context(self, run_id: uuid.UUID) -> JsonObject:
        """Return one persistence-neutral build context bound to an imported generation."""
        return self._required(
            """SELECT release.id AS release_id,release.release_version,release.dataset_id,
            release.target_feature,release.id AS candidate_generation_id,release.coverage_json,
            COALESCE(release.supersedes_release_id,(
                SELECT prior.id FROM ops.dataset_release prior
                WHERE prior.dataset_id=release.dataset_id
                  AND prior.target_feature=release.target_feature
                  AND prior.status='accepted' ORDER BY prior.accepted_at DESC LIMIT 1
            )) AS supersedes_release_id,
            COALESCE(run.source_snapshot_json->>'source_release',run.profile_key) AS source_release,
            run.normalisation_version,run.release_builder_version,
            job.release_builder_key,job.import_profile_key,source.name AS source_name,
            source.publisher,source.licence_id,source.licence_url,
            source.redistribution_policy,source_artifact.created_at AS source_retrieved_at
            FROM ops.ingestion_run run JOIN ops.job_definition job
              ON job.id=run.job_definition_id
            JOIN ops.source_definition source ON source.id=run.source_definition_id
            JOIN ops.dataset_release release ON release.ingestion_run_id=run.id
            LEFT JOIN LATERAL (
                SELECT artifact.created_at FROM ops.artifact_record artifact
                WHERE artifact.ingestion_run_id=run.id
                  AND artifact.artifact_kind IN ('source_snapshot','source_raw')
                ORDER BY artifact.created_at DESC LIMIT 1
            ) source_artifact ON true
            WHERE run.id=%s AND release.status IN ('draft','candidate')""",
            (run_id,),
        )

    def release_product_records(
        self, release_id: uuid.UUID, *, limit: int, offset: int
    ) -> JsonObject:
        """Page the immutable candidate projection used only by registered builders."""
        context = self._required(
            """SELECT release.id,release.coverage_json,job.import_profile_key
            FROM ops.dataset_release release JOIN ops.ingestion_run run
              ON run.id=release.ingestion_run_id
            JOIN ops.job_definition job ON job.id=run.job_definition_id
            WHERE release.id=%s AND release.status IN ('draft','candidate')""",
            (release_id,),
        )
        profile = str(context["import_profile_key"])
        query = release_product_query(
            profile,
            release_id,
            context["coverage_json"],
            limit=limit,
            offset=offset,
        )
        rows = normalise_product_rows(
            profile, self._fetch_all(query.select_sql, query.select_params)
        )
        count = self._required(query.count_sql, query.count_params)
        total = int(count["count"])
        return {
            "release_id": str(release_id),
            "candidate_generation_id": str(release_id),
            "items": rows,
            "count": len(rows),
            "total": total,
            "limit": limit,
            "offset": offset,
            "next_offset": offset + len(rows) if offset + len(rows) < total else None,
        }

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
                raced = self._required(
                    "SELECT * FROM ops.release_activation WHERE idempotency_key=%s",
                    (idempotency_key,),
                )
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
        now = datetime.now(UTC)
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
                work = connection.execute(
                    """SELECT operation.*,release.dataset_id,release.target_feature,
                release.status AS release_status,release.version AS release_version
                FROM ops.release_activation operation JOIN ops.dataset_release release
                  ON release.id=operation.dataset_release_id
                WHERE operation.id=%s AND operation.lease_owner=%s
                  AND operation.lease_token=%s AND operation.lease_expires_at>%s
                  AND operation.status IN ('claimed','running')""",
                    (operation_id, worker_id, lease_token, now),
                ).fetchone()
                if work is None:
                    raise LeaseConflictError("activation lease is stale or owned by another loader")
                if work["release_status"] != "awaiting_review" or int(
                    work["release_version"]
                ) != int(work["expected_release_version"]):
                    raise ConflictError("release changed while publication was queued")
                # Canonical address reads resolve through accepted_generation directly to the
                # immutable warehouse generation. Candidate rows therefore need no pre-pointer
                # upsert into global registry tables, which would leak changed address fields.
                connection.execute(
                    """UPDATE ops.release_activation SET materialized_at=%s,version=version+1
                WHERE id=%s AND lease_owner=%s AND lease_token=%s""",
                    (now, operation_id, worker_id, lease_token),
                )
                connection.commit()
            finally:
                stopped.set()
                watcher.join(timeout=2)

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
    def search_properties(
        self, query: str, *, state: str, limit: int, offset: int = 0
    ) -> PropertySearchResults:
        normalised = _normalise_property_query(query)
        if not normalised:
            return PropertySearchResults(items=[], total=0)
        if _property_query_is_underspecified(normalised):
            raise ValidationError(
                "q must include a street number, postcode, locality, or distinctive address term"
            )
        numeric_value: int | str | None = None
        if normalised.isdigit() and len(normalised) == 4:
            warehouse_match = "address.postcode=%s"
            legacy_match = "property.postcode=%s"
            alias_match = "FALSE"
            numeric_value = normalised
        elif normalised.isdigit():
            warehouse_match = "address.street_number_first=%s"
            legacy_match = "property.street_number_first=%s"
            alias_match = "FALSE"
            numeric_value = int(normalised)
        else:
            warehouse_match = (
                "trim(regexp_replace(lower(address.address_display), "
                "'[^a-z0-9]+',' ','g')) LIKE '%%' || %s || '%%'"
            )
            legacy_match = "property.address_search LIKE '%%' || %s || '%%'"
            alias_match = "alias.alias_search LIKE '%%' || %s || '%%'"
        search_params: list[Any] = [
            numeric_value if numeric_value is not None else normalised,
            PROPERTY_SEARCH_CANDIDATE_LIMIT + 1,
            numeric_value if numeric_value is not None else normalised,
        ]
        if numeric_value is None:
            search_params.append(normalised)
        search_params.extend(
            [
                PROPERTY_SEARCH_CANDIDATE_LIMIT + 1,
                PROPERTY_SEARCH_CANDIDATE_LIMIT,
                normalised,
                normalised,
                normalised,
                normalised,
                normalised,
                state,
                PROPERTY_SEARCH_CANDIDATE_LIMIT,
                limit,
                offset,
            ]
        )
        rows = self._fetch_all(
            f"""
            WITH accepted_addresses AS MATERIALIZED (
                SELECT COALESCE(address.property_ref,
                           md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid) AS property_ref,
                       address.address_display,address.locality,address.postcode,'NSW' AS state,
                       CASE WHEN address.source_status='CURRENT' THEN 'verified'
                            ELSE 'retired' END AS resolution_status,address.geom,
                       trim(regexp_replace(lower(address.address_display),
                           '[^a-z0-9]+',' ','g')) AS search_text,
                       address.address_display AS matched_address,'canonical' AS match_kind
                FROM warehouse.gnaf_address address
                JOIN serving.accepted_generation accepted
                  ON accepted.dataset_release_id=address.dataset_release_id
                JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
                WHERE release.dataset_id IN ('gnaf-nsw','fixture-property')
                  AND {warehouse_match}
                LIMIT %s
            ), legacy_documents AS (
                SELECT property.property_ref,property.address_display,property.locality,
                       property.postcode,property.state,property.resolution_status,property.geom,
                       property.address_search AS search_text,
                       property.address_display AS matched_address,'canonical' AS match_kind
                FROM registry.property property
                WHERE {legacy_match} AND EXISTS (
                    SELECT 1 FROM registry.property_identifier identifier
                    JOIN serving.accepted_generation accepted
                      ON accepted.dataset_release_id=identifier.source_release_id
                    WHERE identifier.property_ref=property.property_ref AND identifier.is_current
                ) AND NOT EXISTS (
                    SELECT 1 FROM warehouse.gnaf_address accepted_address
                    JOIN serving.accepted_generation accepted
                      ON accepted.dataset_release_id=accepted_address.dataset_release_id
                    WHERE COALESCE(accepted_address.property_ref,
                        md5('propertyscope-gnaf:' || accepted_address.gnaf_pid)::uuid)
                        =property.property_ref
                )
                UNION ALL
                SELECT property.property_ref,property.address_display,property.locality,
                       property.postcode,property.state,property.resolution_status,property.geom,
                       alias.alias_search,alias.alias_display,'alias'
                FROM registry.address_alias alias
                JOIN registry.property property ON property.property_ref=alias.property_ref
                JOIN serving.accepted_generation accepted
                  ON accepted.dataset_release_id=alias.source_release_id
                WHERE alias.is_current
                  AND {alias_match}
                  AND NOT EXISTS (
                      SELECT 1 FROM warehouse.gnaf_address accepted_address
                      JOIN serving.accepted_generation accepted
                        ON accepted.dataset_release_id=accepted_address.dataset_release_id
                      WHERE COALESCE(accepted_address.property_ref,
                          md5('propertyscope-gnaf:' || accepted_address.gnaf_pid)::uuid)
                          =property.property_ref
                  )
            ), search_documents AS MATERIALIZED (
                SELECT * FROM accepted_addresses
                UNION ALL SELECT * FROM legacy_documents
                LIMIT %s
            ), candidate_documents AS (
                SELECT * FROM search_documents LIMIT %s
            ), candidates AS (
                SELECT document.property_ref,document.address_display,document.locality,
                       document.postcode,document.state,document.resolution_status,
                       ST_X(document.geom) AS longitude,ST_Y(document.geom) AS latitude,
                       document.matched_address,document.match_kind,
                       greatest(
                           similarity(document.search_text,%s),
                           word_similarity(%s,document.search_text),
                           CASE WHEN document.search_text=%s THEN 1 ELSE 0 END
                       ) AS score,
                       CASE
                           WHEN document.search_text=%s THEN 0
                           WHEN document.search_text LIKE %s || '%%' THEN 1
                           ELSE 2
                       END AS match_rank
                FROM candidate_documents document
                WHERE document.state=%s
            ), best_matches AS (
                SELECT DISTINCT ON (property_ref) * FROM candidates
                ORDER BY property_ref,match_rank,score DESC,
                         CASE WHEN match_kind='canonical' THEN 0 ELSE 1 END,matched_address
            ), summary AS (
                SELECT count(*)::bigint AS total_count,
                       (SELECT count(*)>%s FROM search_documents) AS total_is_lower_bound
                FROM best_matches
            )
            SELECT page.*,summary.total_count,summary.total_is_lower_bound
            FROM summary LEFT JOIN LATERAL (
                SELECT property_ref,address_display,locality,postcode,state,resolution_status,
                       longitude,latitude,score,matched_address,match_kind,
                       CASE match_rank
                           WHEN 0 THEN 'exact'
                           WHEN 1 THEN 'prefix'
                           ELSE 'contains'
                       END AS match_method
                FROM best_matches
                ORDER BY match_rank,score DESC,address_display LIMIT %s OFFSET %s
            ) page ON true
            """,
            search_params,
        )
        total = int(rows[0].get("total_count", 0)) if rows else 0
        total_is_lower_bound = bool(rows[0].get("total_is_lower_bound", False)) if rows else False
        page: list[JsonObject] = []
        for row in rows:
            row.pop("total_count", None)
            row.pop("total_is_lower_bound", None)
            if row.get("property_ref") is not None:
                page.append(row)
        return PropertySearchResults(
            items=page,
            total=total,
            total_is_lower_bound=total_is_lower_bound,
        )

    def property_snapshot(self, property_ref: uuid.UUID) -> JsonObject:
        accepted_address = self._fetch_one(
            """SELECT jsonb_build_object(
                'property_ref',COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid),
                'address_display',address.address_display,'flat_type',address.flat_type,
                'unit_number',address.unit_number,
                'street_number_first',address.street_number_first,
                'street_number_suffix',address.street_number_suffix,
                'street_number_last',address.street_number_last,
                'street_name',COALESCE(address.street_name,address.address_display),
                'street_type',address.street_type,'locality',address.locality,
                'postcode',address.postcode,'state','NSW',
                'address_search',trim(regexp_replace(lower(address.address_display),
                    '[^a-z0-9]+',' ','g')),
                'geometry',ST_AsGeoJSON(address.geom)::jsonb,
                'longitude',ST_X(address.geom),'latitude',ST_Y(address.geom),
                'resolution_status',CASE WHEN address.source_status='CURRENT'
                    THEN 'verified' ELSE 'retired' END,
                'created_at',address.created_at,'updated_at',address.created_at,'version',1
            ) AS property,jsonb_build_object(
                'id',md5('propertyscope-' ||
                    CASE WHEN release.dataset_id='gnaf-nsw' THEN 'gnaf_pid'
                         ELSE 'fixture_pid' END || '-identifier:' || release.id::text || ':' ||
                         address.gnaf_pid)::uuid,
                'property_ref',COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid),
                'scheme',CASE WHEN release.dataset_id='gnaf-nsw' THEN 'gnaf_pid'
                              ELSE 'fixture_pid' END,
                'identifier_value',address.gnaf_pid,'source_release_id',release.id,
                'is_current',true,'valid_from',NULL,'valid_to',NULL,
                'match_method','source-authoritative','match_confidence',1,
                'evidence_json',jsonb_build_object('geocode_type',address.geocode_type,
                    'source_crs',address.source_crs),'created_at',address.created_at
            ) AS identifier
            FROM warehouse.gnaf_address address
            JOIN serving.accepted_generation accepted
              ON accepted.dataset_release_id=address.dataset_release_id
            JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
            WHERE release.dataset_id IN ('gnaf-nsw','fixture-property')
              AND COALESCE(address.property_ref,
                  md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
            LIMIT 1""",
            (property_ref,),
        )
        if accepted_address is not None:
            return {
                "property": dict(accepted_address["property"]),
                "identifiers": [dict(accepted_address["identifier"])],
                "aliases": [],
                "coverage": self.property_coverage(property_ref),
            }
        property_row = self._required(
            """SELECT *,ST_X(geom) AS longitude,ST_Y(geom) AS latitude,
            ST_AsGeoJSON(geom)::jsonb AS geometry FROM registry.property WHERE property_ref=%s""",
            (property_ref,),
        )
        identifiers = self._fetch_all(
            "SELECT * FROM registry.property_identifier WHERE property_ref=%s ORDER BY created_at",
            (property_ref,),
        )
        aliases = self._fetch_all(
            "SELECT * FROM registry.address_alias WHERE property_ref=%s ORDER BY alias_display",
            (property_ref,),
        )
        coverage = self.property_coverage(property_ref)
        return {
            "property": property_row,
            "identifiers": identifiers,
            "aliases": aliases,
            "coverage": coverage,
        }

    def property_coverage(self, property_ref: uuid.UUID) -> list[JsonObject]:
        exists = self._fetch_one(
            """SELECT 1 AS present FROM warehouse.gnaf_address address
            JOIN serving.accepted_generation accepted
              ON accepted.dataset_release_id=address.dataset_release_id
            WHERE COALESCE(address.property_ref,
                md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
            UNION ALL SELECT 1 FROM registry.property WHERE property_ref=%s LIMIT 1""",
            (property_ref, property_ref),
        )
        if exists is None:
            raise NotFoundError("record does not exist")
        return self._fetch_all(
            """WITH accepted_identity AS (
                SELECT COALESCE(address.property_ref,
                           md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid) AS property_ref,
                       release.dataset_id,release.target_feature,
                       release.id AS dataset_release_id,'supported' AS coverage_status,
                       release.coverage_json AS coverage_scope,
                       accepted.activated_at AS checked_at,release.release_version,
                       release.schema_version,release.accepted_at
                FROM warehouse.gnaf_address address
                JOIN serving.accepted_generation accepted
                  ON accepted.dataset_release_id=address.dataset_release_id
                JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
                WHERE COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)=%s
            ), retained_coverage AS (
                SELECT coverage.*,release.release_version,release.schema_version,
                       release.accepted_at
                FROM serving.property_coverage coverage
                LEFT JOIN ops.dataset_release release ON release.id=coverage.dataset_release_id
                WHERE coverage.property_ref=%s AND NOT EXISTS (
                    SELECT 1 FROM accepted_identity identity
                    WHERE identity.dataset_id=coverage.dataset_id
                      AND identity.target_feature=coverage.target_feature
                )
            )
            SELECT * FROM accepted_identity UNION ALL SELECT * FROM retained_coverage
            ORDER BY target_feature,dataset_id""",
            (property_ref, property_ref),
        )

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
    def create_import(self, values: Mapping[str, Any]) -> tuple[JsonObject, bool]:
        existing = self._fetch_one(
            "SELECT * FROM ops.import_operation WHERE idempotency_key=%s",
            (str(values["idempotency_key"]),),
        )
        if existing:
            expected = (
                str(values["run_task_id"]),
                str(values["candidate_release_id"]),
                str(values["artifact_record_id"]),
                str(values["import_profile_key"]),
            )
            actual = (
                str(existing["run_task_id"]),
                str(existing["candidate_release_id"]),
                str(existing["artifact_record_id"]),
                str(existing["import_profile_key"]),
            )
            if expected != actual:
                raise ConflictError("idempotency key arguments do not match")
            return existing, False
        now = datetime.now(UTC)
        with self.connection() as connection:
            try:
                row = connection.execute(
                    """INSERT INTO ops.import_operation (
                        id,ingestion_run_id,run_task_id,candidate_release_id,import_profile_key,
                        import_profile_version,artifact_record_id,status,attempt_number,idempotency_key,
                        requested_at,rows_in,rows_staged,rows_accepted,rows_rejected,version
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,'planned',1,%s,%s,0,0,0,0,1) RETURNING *""",
                    (
                        uuid.uuid4(),
                        uuid.UUID(str(values["ingestion_run_id"])),
                        uuid.UUID(str(values["run_task_id"])),
                        uuid.UUID(str(values["candidate_release_id"])),
                        values["import_profile_key"],
                        values["import_profile_version"],
                        uuid.UUID(str(values["artifact_record_id"])),
                        values["idempotency_key"],
                        now,
                    ),
                ).fetchone()
                connection.commit()
            except errors.UniqueViolation as exc:
                raise ConflictError("run task already has an import operation") from exc
            except errors.ForeignKeyViolation as exc:
                raise NotFoundError("run, task, release, or artifact does not exist") from exc
        return _dict(row), True

    def get_import(self, operation_id: uuid.UUID) -> JsonObject:
        return self._required("SELECT * FROM ops.import_operation WHERE id=%s", (operation_id,))

    def import_work(self, operation_id: uuid.UUID) -> JsonObject:
        """Return the fixed registered operation plus verified artifact metadata for the loader."""
        return self._required(
            """SELECT operation.*,artifact.storage_key,artifact.content_sha256,
            artifact.bytes AS artifact_bytes,artifact.media_type,artifact.schema_version
            FROM ops.import_operation operation JOIN ops.artifact_record artifact
            ON artifact.id=operation.artifact_record_id WHERE operation.id=%s""",
            (operation_id,),
        )

    def execute_import_profile(
        self, work: Mapping[str, Any], prepared: PreparedImport
    ) -> ImportResult:
        """Execute one registered COPY/import profile inside the credential boundary."""
        operation_id = uuid.UUID(str(work["id"]))
        with self._cancellable_import_connection(operation_id) as connection:
            return execute_import(connection, work, prepared)

    def execute_stream_import_profile(
        self, work: Mapping[str, Any], *, profile: str, rows: Any
    ) -> ImportResult:
        """Execute a source-scale streaming COPY inside the credential boundary."""
        operation_id = uuid.UUID(str(work["id"]))
        with self._cancellable_import_connection(operation_id) as connection:
            return execute_stream_import(connection, work, profile=profile, rows=rows)

    @contextmanager
    def _cancellable_import_connection(self, operation_id: uuid.UUID) -> Iterator[Connection[Any]]:
        """Cancel an in-flight PostgreSQL statement when its owning run is cancelled."""
        with self.connection() as connection:
            stopped = Event()

            def monitor() -> None:
                while not stopped.wait(0.5):
                    if self.import_cancel_requested(operation_id):
                        connection.cancel()
                        return

            watcher = Thread(target=monitor, name=f"import-cancel-{operation_id}", daemon=True)
            watcher.start()
            try:
                yield connection
            finally:
                stopped.set()
                watcher.join(timeout=2)

    def import_cancel_requested(self, operation_id: uuid.UUID) -> bool:
        row = self._fetch_one(
            """SELECT run.cancel_requested_at FROM ops.import_operation operation
            JOIN ops.ingestion_run run ON run.id=operation.ingestion_run_id
            WHERE operation.id=%s""",
            (operation_id,),
        )
        return row is not None and row["cancel_requested_at"] is not None

    def enqueue_import(self, operation_id: uuid.UUID) -> JsonObject:
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.import_operation SET status='queued',version=version+1
                WHERE id=%s AND status IN ('planned','interrupted') RETURNING *""",
                (operation_id,),
            ).fetchone()
            connection.commit()
        if row is None:
            current = self.get_import(operation_id)
            if current["status"] == "queued":
                return current
            raise ConflictError("import cannot be enqueued from its current state")
        return _dict(row)

    def cancel_import(self, operation_id: uuid.UUID) -> JsonObject:
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.import_operation SET status='cancelled',finished_at=%s,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                version=version+1 WHERE id=%s AND status IN ('planned','queued','interrupted') RETURNING *""",
                (datetime.now(UTC), operation_id),
            ).fetchone()
            connection.commit()
        if row is None:
            raise ConflictError("running or terminal import cannot be cancelled immediately")
        return _dict(row)

    def claim_import(self, *, worker_id: str, lease_seconds: int) -> JsonObject | None:
        now = datetime.now(UTC)
        token = uuid.uuid4().hex
        with self.connection() as connection:
            row = connection.execute(
                """WITH candidate AS (
                    SELECT id FROM ops.import_operation WHERE status='queued'
                    ORDER BY requested_at FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE ops.import_operation operation SET status='claimed',lease_owner=%s,
                    lease_token=%s,lease_expires_at=%s,heartbeat_at=%s,
                    started_at=COALESCE(started_at,%s),version=version+1 FROM candidate
                WHERE operation.id=candidate.id RETURNING operation.*""",
                (worker_id, token, now + timedelta(seconds=lease_seconds), now, now),
            ).fetchone()
            connection.commit()
        return _dict(row) if row else None

    def heartbeat_import(
        self, operation_id: uuid.UUID, *, worker_id: str, lease_token: str, lease_seconds: int
    ) -> JsonObject:
        now = datetime.now(UTC)
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.import_operation SET status='running',heartbeat_at=%s,
                lease_expires_at=%s,version=version+1 WHERE id=%s AND lease_owner=%s
                AND lease_token=%s AND lease_expires_at>%s AND status IN ('claimed','running') RETURNING *""",
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
            raise LeaseConflictError("import lease is stale or owned by another loader")
        return _dict(row)

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
        if status not in {"succeeded", "failed", "cancelled"}:
            raise ConflictError("loader may finish only as succeeded, failed, or cancelled")
        now = datetime.now(UTC)
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.import_operation SET status=%s,finished_at=%s,rows_in=%s,
                rows_staged=%s,rows_accepted=%s,rows_rejected=%s,result_json=%s,error_json=%s,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                version=version+1 WHERE id=%s AND lease_owner=%s AND lease_token=%s
                AND lease_expires_at>%s AND status IN ('claimed','running') RETURNING *""",
                (
                    status,
                    now,
                    counts.get("rows_in", 0),
                    counts.get("rows_staged", 0),
                    counts.get("rows_accepted", 0),
                    counts.get("rows_rejected", 0),
                    _json(result) if result else None,
                    _json(error) if error else None,
                    operation_id,
                    worker_id,
                    lease_token,
                    now,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise LeaseConflictError("import lease is stale or owned by another loader")
        return _dict(row)

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
                    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE id=%s""",
                    (now, _json(_cancellation_error()), run_id),
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
                    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL WHERE id=%s
                    AND status NOT IN ('succeeded','failed','cancelled')""",
                    (now, _json(error) if error else _json({"code": "task_failed"}), run_id),
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
                        rows_discovered=(SELECT COALESCE(max(rows_out),0) FROM ops.run_task
                            WHERE ingestion_run_id=%s AND stage='acquire'),
                        rows_staged=(SELECT COALESCE(max(rows_in),0) FROM ops.run_task
                            WHERE ingestion_run_id=%s AND stage='import'),
                        rows_accepted=(SELECT COALESCE(max(rows_out),0) FROM ops.run_task
                            WHERE ingestion_run_id=%s AND stage='import')
                        WHERE id=%s AND status NOT IN ('failed','cancelled')""",
                        (now, run_id, run_id, run_id, run_id),
                    )
                else:
                    stage_status = run_status_for_stage(str(row["stage"]))
                    connection.execute(
                        "UPDATE ops.ingestion_run SET status=%s,heartbeat_at=%s WHERE id=%s",
                        (stage_status, now, run_id),
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
