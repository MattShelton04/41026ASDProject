"""PostgreSQL repository and atomic state/lease operations."""

# SQL statements stay line-oriented so schema and transition policies remain reviewable.
# ruff: noqa: E501

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg import Connection, errors, sql
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from propertyscope_data_store.errors import ConflictError, LeaseConflictError, NotFoundError
from propertyscope_data_store.import_profiles import ImportResult, PreparedImport, execute_import
from propertyscope_data_store.migrations import migrate, schema_fingerprint

JsonObject = dict[str, Any]
TERMINAL_RUN_STATES = frozenset({"succeeded", "failed", "cancelled"})
TERMINAL_TASK_STATES = frozenset({"succeeded", "failed", "cancelled", "skipped"})
TERMINAL_IMPORT_STATES = frozenset({"succeeded", "failed", "cancelled"})


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

    def initialize(self, *, seed: bool = True) -> str:
        """Migrate from empty; seed migration remains idempotent and profile-safe."""
        del seed  # The checked showcase seed is an idempotent migration in Release 0.
        with self.connection() as connection:
            migrate(connection)
            return schema_fingerprint(connection)

    def ready(self) -> bool:
        try:
            with self.connection() as connection:
                row = connection.execute("SELECT postgis_version() AS version").fetchone()
            return row is not None and bool(row["version"])
        except Exception:
            return False

    def counts(self) -> JsonObject:
        tables = (
            "ops.source_definition",
            "ops.job_definition",
            "ops.ingestion_run",
            "ops.run_task",
            "ops.import_operation",
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

    # Sources and jobs are the two complete operator CRUD aggregates.
    def list_sources(self, *, status: str | None, limit: int, offset: int) -> list[JsonObject]:
        query = "SELECT * FROM ops.source_definition"
        params: list[Any] = []
        if status:
            query += " WHERE status = %s"
            params.append(status)
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

    def list_jobs(self, *, status: str | None, limit: int, offset: int) -> list[JsonObject]:
        query = """
            SELECT job.*, source.name AS source_name FROM ops.job_definition job
            JOIN ops.source_definition source ON source.id = job.source_definition_id
        """
        params: list[Any] = []
        if status:
            query += " WHERE job.status = %s"
            params.append(status)
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
            return existing, False
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
                    ) VALUES (%s,%s,%s,'1.0.0','1.0.0',%s,'1.0.0',%s,%s,%s,1,%s,%s,'queued',%s,%s,%s)
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
                        parent_run_id,
                        now,
                        request_id,
                        idempotency_key,
                        now,
                    ),
                ).fetchone()
                for stage_index, stage in enumerate(
                    (
                        "discover",
                        "acquire",
                        "validate_artifact",
                        "import",
                        "normalise",
                        "quality",
                        "build_release",
                    )
                ):
                    connection.execute(
                        """
                        INSERT INTO ops.run_task (
                            id,ingestion_run_id,logical_key,partition_json,stage,status,
                            attempt_number,rows_in,rows_out,created_at,updated_at,version
                        ) VALUES (%s,%s,%s,%s,%s,'pending',1,0,0,%s,%s,1)
                        """,
                        (
                            uuid.uuid4(),
                            run_id,
                            f"{stage_index:02d}/{stage}",
                            _json(scope),
                            stage,
                            now,
                            now,
                        ),
                    )
                connection.commit()
            except errors.UniqueViolation:
                connection.rollback()
                existing = self._required(
                    "SELECT * FROM ops.ingestion_run WHERE job_definition_id=%s AND idempotency_key=%s",
                    (job_id, idempotency_key),
                )
                return existing, False
        return _dict(row), True

    def list_runs(self, *, status: str | None, limit: int, offset: int) -> list[JsonObject]:
        query = """
            SELECT run.*, job.name AS job_name, source.name AS source_name
            FROM ops.ingestion_run run
            JOIN ops.job_definition job ON job.id=run.job_definition_id
            JOIN ops.source_definition source ON source.id=run.source_definition_id
        """
        params: list[Any] = []
        if status:
            query += " WHERE run.status=%s"
            params.append(status)
        query += " ORDER BY run.requested_at DESC LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        return self._fetch_all(query, params)

    def get_run(self, run_id: uuid.UUID) -> JsonObject:
        return self._required("SELECT * FROM ops.ingestion_run WHERE id=%s", (run_id,))

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
        run = self.get_run(run_id)
        if run["status"] in TERMINAL_RUN_STATES:
            raise ConflictError("terminal run cannot be cancelled")
        with self.connection() as connection:
            row = connection.execute(
                "UPDATE ops.ingestion_run SET cancel_requested_at=COALESCE(cancel_requested_at,%s) WHERE id=%s RETURNING *",
                (datetime.now(UTC), run_id),
            ).fetchone()
            connection.commit()
        return _dict(row)

    def resume_run(self, run_id: uuid.UUID) -> JsonObject:
        run = self.get_run(run_id)
        if run["status"] != "interrupted":
            raise ConflictError("only interrupted runs can resume")
        now = datetime.now(UTC)
        with self.connection() as connection:
            connection.execute(
                """UPDATE ops.run_task SET status='pending',lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,heartbeat_at=NULL,version=version+1,updated_at=%s
                WHERE ingestion_run_id=%s AND status IN ('claimed','running','retry_wait')""",
                (now, run_id),
            )
            row = connection.execute(
                """UPDATE ops.ingestion_run SET status='queued',lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,heartbeat_at=NULL,finished_at=NULL WHERE id=%s RETURNING *""",
                (run_id,),
            ).fetchone()
            connection.commit()
        return _dict(row)

    def claim_task(self, *, worker_id: str, lease_seconds: int) -> JsonObject | None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        token = uuid.uuid4().hex
        with self.connection() as connection:
            row = connection.execute(
                """
                WITH candidate AS (
                    SELECT task.id FROM ops.run_task task
                    JOIN ops.ingestion_run run ON run.id=task.ingestion_run_id
                    WHERE task.status='pending' AND run.status NOT IN ('succeeded','failed','cancelled')
                      AND run.cancel_requested_at IS NULL
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
                    """UPDATE ops.ingestion_run SET status=CASE WHEN status='queued' THEN 'planning' ELSE status END,
                    started_at=COALESCE(started_at,%s),heartbeat_at=%s WHERE id=%s""",
                    (now, now, row["ingestion_run_id"]),
                )
                context = connection.execute(
                    """SELECT run.profile_key,run.run_mode,run.requested_scope_json,
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
                """UPDATE ops.run_task SET status='running',heartbeat_at=%s,lease_expires_at=%s,
                updated_at=%s,version=version+1 WHERE id=%s AND lease_owner=%s AND lease_token=%s
                AND lease_expires_at>%s AND status IN ('claimed','running') RETURNING *""",
                (
                    now,
                    now + timedelta(seconds=lease_seconds),
                    now,
                    task_id,
                    worker_id,
                    lease_token,
                    now,
                ),
            ).fetchone()
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
    def list_releases(self, *, status: str | None, limit: int, offset: int) -> list[JsonObject]:
        query = "SELECT * FROM ops.dataset_release"
        params: list[Any] = []
        if status:
            query += " WHERE status=%s"
            params.append(status)
        query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend((limit, offset))
        return self._fetch_all(query, params)

    def get_release(self, release_id: uuid.UUID) -> JsonObject:
        return self._required("SELECT * FROM ops.dataset_release WHERE id=%s", (release_id,))

    def release_artifact(self, release_id: uuid.UUID) -> JsonObject:
        return self._required(
            """SELECT artifact.*,source.redistribution_policy,release.status AS release_status
            FROM ops.dataset_release release
            JOIN ops.artifact_record artifact ON artifact.id=release.artifact_record_id
            JOIN ops.source_definition source ON source.id=release.source_definition_id
            WHERE release.id=%s""",
            (release_id,),
        )

    def create_release(self, values: Mapping[str, Any]) -> JsonObject:
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
        if current["status"] not in {"draft", "candidate"}:
            raise ConflictError("accepted or terminal release evidence cannot be edited")
        with self.connection() as connection:
            row = connection.execute(
                """UPDATE ops.dataset_release SET release_version=%s,schema_version=%s,
                coverage_json=%s,record_count=%s,content_sha256=%s,manifest_json=%s,
                review_comment=%s,updated_at=%s,version=version+1 WHERE id=%s AND version=%s
                AND status IN ('draft','candidate') RETURNING *""",
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
            expected = (
                str(release_id),
                values["status"],
                values["schema_version"],
                values["content_sha256"],
                int(values["rows_received"]),
                int(values["rows_accepted"]),
                int(values["rows_rejected"]),
            )
            actual = (
                str(existing["dataset_release_id"]),
                existing["status"],
                existing["schema_version"],
                existing["content_sha256"],
                int(existing["rows_received"]),
                int(existing["rows_accepted"]),
                int(existing["rows_rejected"]),
            )
            if expected != actual:
                raise ConflictError("publication idempotency key arguments do not match")
            return existing, False
        now = datetime.now(UTC)
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
        return _dict(row), True

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
            row = connection.execute(
                """UPDATE ops.dataset_release SET status=%s,review_comment=%s,
                accepted_at=CASE WHEN %s='accepted' THEN %s ELSE accepted_at END,
                updated_at=%s,version=version+1 WHERE id=%s AND version=%s RETURNING *""",
                (target, comment, target, now, now, release_id, expected_version),
            ).fetchone()
            if row is None:
                raise ConflictError("release version does not match")
            if target == "accepted":
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

    # Property discovery reads only accepted serving evidence.
    def search_properties(self, query: str, *, state: str, limit: int) -> list[JsonObject]:
        normalised = " ".join(query.lower().split())
        return self._fetch_all(
            """
            SELECT property_ref,address_display,locality,postcode,state,resolution_status,
                   ST_X(geom) AS longitude,ST_Y(geom) AS latitude,
                   greatest(similarity(address_search,%s), CASE WHEN address_search=%s THEN 1 ELSE 0 END) AS score
            FROM registry.property
            WHERE state=%s AND (address_search ILIKE '%%' || %s || '%%' OR address_search %% %s)
            ORDER BY CASE WHEN address_search=%s THEN 0 WHEN address_search LIKE %s || '%%' THEN 1 ELSE 2 END,
                     score DESC,address_display LIMIT %s
            """,
            (normalised, normalised, state, normalised, normalised, normalised, normalised, limit),
        )

    def property_snapshot(self, property_ref: uuid.UUID) -> JsonObject:
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
        self._required(
            "SELECT property_ref FROM registry.property WHERE property_ref=%s", (property_ref,)
        )
        return self._fetch_all(
            """SELECT coverage.*,release.release_version,release.schema_version,release.accepted_at
            FROM serving.property_coverage coverage LEFT JOIN ops.dataset_release release
            ON release.id=coverage.dataset_release_id WHERE coverage.property_ref=%s
            ORDER BY coverage.target_feature,coverage.dataset_id""",
            (property_ref,),
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
                "SELECT count(*) AS count FROM registry.property"
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
        with self.connection() as connection:
            return execute_import(connection, work, prepared)

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
        if status not in {"succeeded", "failed"}:
            raise ConflictError("loader may finish only as succeeded or failed")
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
        existing = self._fetch_one(
            "SELECT * FROM ops.artifact_record WHERE content_sha256=%s AND artifact_kind=%s",
            (values["content_sha256"], values["artifact_kind"]),
        )
        if existing:
            return existing, False
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
                    uuid.UUID(str(values["run_task_id"])) if values.get("run_task_id") else None,
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
            connection.commit()
        return _dict(row), True

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
            if status == "failed":
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
                        rows_accepted=(SELECT COALESCE(sum(rows_out),0) FROM ops.run_task WHERE ingestion_run_id=%s)
                        WHERE id=%s AND status NOT IN ('failed','cancelled')""",
                        (now, run_id, run_id),
                    )
                else:
                    stage_status = {
                        "discover": "discovering",
                        "acquire": "acquiring",
                        "validate_artifact": "acquiring",
                        "import": "staging",
                        "normalise": "normalising",
                        "quality": "validating",
                        "build_release": "building_release",
                    }.get(str(row["stage"]), "planning")
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


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _dict(row: Mapping[str, Any] | None) -> JsonObject:
    if row is None:
        raise RuntimeError("expected database row")
    return {key: _normalise(value) for key, value in row.items()}


def _rows(rows: Sequence[Mapping[str, Any]]) -> list[JsonObject]:
    return [_dict(row) for row in rows]


def _normalise(value: Any) -> Any:
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    return value
