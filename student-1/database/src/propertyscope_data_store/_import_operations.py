"""Registered import-operation persistence owned behind the repository facade."""

# SQL statements stay line-oriented so schema and transition policies remain reviewable.
# ruff: noqa: E501

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event, Thread
from typing import Any, Protocol

from psycopg import Connection, errors, sql

from propertyscope_data_store.errors import ConflictError, LeaseConflictError, NotFoundError
from propertyscope_data_store.import_profiles import (
    ImportResult,
    PreparedImport,
    execute_import,
    execute_stream_import,
)
from propertyscope_data_store.persistence_support import cancellation_error as _cancellation_error
from propertyscope_data_store.persistence_support import (
    import_lease_expired_error as _import_lease_expired_error,
)
from propertyscope_data_store.persistence_support import json_document as _json
from propertyscope_data_store.persistence_support import normalise_row as _dict

JsonObject = dict[str, Any]
_IMPORT_TARGET_RELATIONS: Mapping[str, tuple[str, ...]] = {
    "property-fixture": ("warehouse.gnaf_address",),
    "gnaf-nsw": ("warehouse.gnaf_address",),
    "psi-sales": (
        "warehouse.psi_sale",
        "registry.property",
        "registry.property_identifier",
    ),
    "bocsar-sparse": (
        "warehouse.bocsar_observation",
        "warehouse.bocsar_coverage",
    ),
    "schools-master": ("warehouse.school",),
    "seifa-2021-sal-nsw": ("warehouse.seifa_sal",),
}
SPACE_RECOVERY_STATEMENT_TIMEOUT_SECONDS = 10 * 60
SPACE_RECOVERY_REINDEX_TIMEOUT_SECONDS = 10 * 60
SPACE_RECOVERY_REINDEX_MIN_DEAD_TUPLES = 100_000
SPACE_RECOVERY_REINDEX_MIN_INDEX_BYTES = 64 * 1024 * 1024


class _ImportOperationOwner(Protocol):
    """The narrow repository services required by registered import operations."""

    def connection(self) -> AbstractContextManager[Connection[Any]]: ...

    def _fetch_one(self, query: str, params: Sequence[Any]) -> JsonObject | None: ...

    def _required(self, query: str, params: Sequence[Any]) -> JsonObject: ...

    def get_import(self, operation_id: uuid.UUID) -> JsonObject: ...

    def import_cancel_requested(self, operation_id: uuid.UUID) -> bool: ...


class _RegisteredImportOperations:
    """Atomic persistence operations for the registered loader lifecycle."""

    def __init__(self, owner: _ImportOperationOwner) -> None:
        self._owner = owner

    def create_import(self, values: Mapping[str, Any]) -> tuple[JsonObject, bool]:
        existing = self._owner._fetch_one(
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
        with self._owner.connection() as connection:
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
        return self._owner._required(
            "SELECT * FROM ops.import_operation WHERE id=%s", (operation_id,)
        )

    def import_work(self, operation_id: uuid.UUID) -> JsonObject:
        """Return the fixed registered operation plus verified artifact metadata for the loader."""
        return self._owner._required(
            """SELECT operation.*,artifact.storage_key,artifact.content_sha256,
            artifact.bytes AS artifact_bytes,artifact.media_type,artifact.schema_version
            FROM ops.import_operation operation JOIN ops.artifact_record artifact
            ON artifact.id=operation.artifact_record_id WHERE operation.id=%s""",
            (operation_id,),
        )

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
        operation_id = uuid.UUID(str(work["id"]))
        with self.cancellable_connection(
            operation_id,
            lease_failed_event=lease_failed_event,
            stop_event=stop_event,
        ) as connection:
            return execute_import(
                connection,
                work,
                prepared,
                phase_callback=phase_callback,
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
        operation_id = uuid.UUID(str(work["id"]))
        with self.cancellable_connection(
            operation_id,
            lease_failed_event=lease_failed_event,
            stop_event=stop_event,
        ) as connection:
            result = execute_stream_import(
                connection, work, profile=profile, rows=rows, phase_callback=phase_callback
            )
            if verify_complete is not None:
                verify_complete()
            return result

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
        now = datetime.now(UTC)
        with self._owner.connection() as connection:
            row = connection.execute(
                """UPDATE ops.import_operation SET progress_phase_key=%s,progress_phase=%s,
                progress_rows=%s,
                progress_bytes=%s,progress_total_rows=%s,progress_total_bytes=%s,
                progress_updated_at=%s,heartbeat_at=%s,version=version+1
                WHERE id=%s AND status IN ('claimed','running') RETURNING ingestion_run_id,run_task_id""",
                (
                    phase_key[:100],
                    phase[:100],
                    max(0, rows_processed),
                    max(0, bytes_processed),
                    total_rows,
                    total_bytes,
                    now,
                    now,
                    operation_id,
                ),
            ).fetchone()
            if row is not None:
                connection.execute(
                    """UPDATE ops.run_task SET progress_phase_key=%s,progress_phase=%s,
                    progress_rows=%s,
                    progress_bytes=%s,progress_total_rows=%s,progress_total_bytes=%s,
                    progress_updated_at=%s,heartbeat_at=%s WHERE id=%s""",
                    (
                        phase_key[:100],
                        phase[:100],
                        max(0, rows_processed),
                        max(0, bytes_processed),
                        total_rows,
                        total_bytes,
                        now,
                        now,
                        row["run_task_id"],
                    ),
                )
                connection.execute(
                    """UPDATE ops.ingestion_run SET heartbeat_at=%s,
                    rows_discovered=CASE WHEN run_mode='reprocess_cached'
                        THEN GREATEST(rows_discovered,%s) ELSE rows_discovered END,
                    rows_staged=GREATEST(rows_staged,%s) WHERE id=%s""",
                    (
                        now,
                        max(0, rows_processed),
                        max(0, rows_processed),
                        row["ingestion_run_id"],
                    ),
                )
            connection.commit()

    @contextmanager
    def cancellable_connection(
        self,
        operation_id: uuid.UUID,
        *,
        lease_failed_event: Event | None = None,
        stop_event: Event | None = None,
    ) -> Iterator[Connection[Any]]:
        """Cancel an in-flight PostgreSQL statement when its owning run is cancelled."""
        with self._owner.connection() as connection:
            stopped = Event()

            def monitor() -> None:
                while not stopped.wait(0.5):
                    if (
                        (lease_failed_event is not None and lease_failed_event.is_set())
                        or (stop_event is not None and stop_event.is_set())
                        or self._owner.import_cancel_requested(operation_id)
                    ):
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
        row = self._owner._fetch_one(
            """SELECT run.cancel_requested_at FROM ops.import_operation operation
            JOIN ops.ingestion_run run ON run.id=operation.ingestion_run_id
            WHERE operation.id=%s""",
            (operation_id,),
        )
        return row is not None and row["cancel_requested_at"] is not None

    def enqueue_import(self, operation_id: uuid.UUID) -> JsonObject:
        with self._owner.connection() as connection:
            row = connection.execute(
                """UPDATE ops.import_operation SET status='queued',
                attempt_number=CASE WHEN status='interrupted'
                    THEN attempt_number+1 ELSE attempt_number END,version=version+1
                WHERE id=%s AND status IN ('planned','interrupted') RETURNING *""",
                (operation_id,),
            ).fetchone()
            connection.commit()
        if row is None:
            current = self._owner.get_import(operation_id)
            if current["status"] == "queued":
                return current
            raise ConflictError("import cannot be enqueued from its current state")
        return _dict(row)

    def cancel_import(self, operation_id: uuid.UUID) -> JsonObject:
        with self._owner.connection() as connection:
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
        with self._owner.connection() as connection:
            connection.execute(
                """UPDATE ops.import_operation operation SET status='cancelled',finished_at=%s,
                error_json=%s,lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                heartbeat_at=NULL,space_recovery_status='needed',
                space_recovery_policy_json=jsonb_build_object(
                    'policy','measure_then_target_exact_relations',
                    'trigger','cancelled_import_lease_expired_after_possible_rollback',
                    'relations',to_jsonb(CASE operation.import_profile_key
                        WHEN 'psi-sales' THEN ARRAY[
                            'warehouse.psi_sale','registry.property',
                            'registry.property_identifier']::text[]
                        WHEN 'bocsar-sparse' THEN ARRAY[
                            'warehouse.bocsar_observation','warehouse.bocsar_coverage']::text[]
                        WHEN 'schools-master' THEN ARRAY['warehouse.school']::text[]
                        WHEN 'seifa-2021-sal-nsw' THEN ARRAY['warehouse.seifa_sal']::text[]
                        ELSE ARRAY['warehouse.gnaf_address']::text[] END),
                    'destination_may_have_been_touched',COALESCE(
                        operation.progress_phase_key IN ('target_materialisation','verification'),
                        false),
                    'automatic_destructive_maintenance',false,
                    'next_step','measure dead tuples and allocated bytes before bounded maintenance'
                ),version=operation.version+1 FROM ops.ingestion_run run
                WHERE run.id=operation.ingestion_run_id AND run.cancel_requested_at IS NOT NULL
                AND operation.status IN ('claimed','running')
                AND operation.lease_expires_at<=%s""",
                (now, _json(_cancellation_error()), now),
            )
            # Import work follows the same explicit-resume policy as acquisition tasks.
            # A replacement loader records the expired boundary but never steals work.
            connection.execute(
                """UPDATE ops.import_operation operation SET status='interrupted',error_json=%s,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                version=operation.version+1 FROM ops.ingestion_run run
                WHERE run.id=operation.ingestion_run_id AND run.cancel_requested_at IS NULL
                AND operation.status IN ('claimed','running')
                AND operation.lease_expires_at<=%s""",
                (_json(_import_lease_expired_error()), now),
            )
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
        with self._owner.connection() as connection:
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
        recovery_status = "needed" if status in {"failed", "cancelled"} else "not_required"
        recovery_policy: JsonObject = {}
        if recovery_status == "needed":
            current = self._owner.get_import(operation_id)
            profile = str(current["import_profile_key"])
            destination_may_have_been_touched = str(current.get("progress_phase_key")) in {
                "target_materialisation",
                "verification",
            }
            recovery_policy = {
                "policy": "measure_then_target_exact_relations",
                "trigger": f"import_{status}_after_transaction_rollback",
                "relations": list(_IMPORT_TARGET_RELATIONS.get(profile, ())),
                "destination_may_have_been_touched": destination_may_have_been_touched,
                "automatic_destructive_maintenance": False,
                "next_step": "measure dead tuples and allocated bytes before bounded maintenance",
            }
        with self._owner.connection() as connection:
            row = connection.execute(
                """UPDATE ops.import_operation SET status=%s,finished_at=%s,rows_in=%s,
                rows_staged=%s,rows_accepted=%s,rows_rejected=%s,result_json=%s,error_json=%s,
                space_recovery_status=%s,space_recovery_policy_json=%s,
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
                    recovery_status,
                    _json(recovery_policy),
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

    def recover_import_space(self, operation_id: uuid.UUID) -> JsonObject:
        """Run bounded reusable-space maintenance on the import profile's exact relations."""
        current = self._owner.get_import(operation_id)
        if current["status"] not in {"failed", "cancelled"}:
            raise ConflictError("space recovery requires a failed or cancelled import")
        if current["space_recovery_status"] == "completed":
            return current
        if current["space_recovery_status"] != "needed":
            raise ConflictError("space recovery is not required for this import")
        relations = _IMPORT_TARGET_RELATIONS.get(str(current["import_profile_key"]), ())
        if not relations:
            raise ConflictError("import profile has no registered recovery relations")
        measured_before = self._measure_relations(relations)
        policy = dict(current.get("space_recovery_policy_json") or {})
        destination_may_have_been_touched = policy.get("destination_may_have_been_touched", True)
        recovery_relations = relations if destination_may_have_been_touched is not False else ()
        pre_vacuum_reindex_relations = tuple(
            str(measurement["relation"])
            for measurement in measured_before
            if str(measurement["relation"]) in recovery_relations
            and _requires_atomic_reindex(measurement, measurement)
        )
        if pre_vacuum_reindex_relations:
            policy.update(
                {
                    "relations_pending_reindex": list(pre_vacuum_reindex_relations),
                    "reindex_evidence_phase": "before_vacuum",
                    "measured_before": measured_before,
                }
            )
            self._record_recovery_policy(operation_id, policy)
        if recovery_relations:
            with self._owner.connection() as connection:
                # Loader connections begin with transaction-local safety settings. VACUUM must run
                # outside a transaction, so end that empty transaction and use bounded autocommit.
                connection.commit()
                connection.autocommit = True
                try:
                    connection.execute(
                        "SELECT set_config('statement_timeout',%s,false)",
                        (f"{SPACE_RECOVERY_STATEMENT_TIMEOUT_SECONDS}s",),
                    )
                    for relation in recovery_relations:
                        schema_name, table_name = relation.split(".", maxsplit=1)
                        connection.execute(
                            sql.SQL("VACUUM (ANALYZE, INDEX_CLEANUP ON) {}").format(
                                sql.Identifier(schema_name, table_name)
                            )
                        )
                finally:
                    connection.execute("RESET statement_timeout")
                    connection.autocommit = False
        measured_after_vacuum = self._measure_relations(relations)
        before_by_relation = {
            str(measurement["relation"]): measurement for measurement in measured_before
        }
        measured_reindex_relations = tuple(
            str(measurement["relation"])
            for measurement in measured_after_vacuum
            if str(measurement["relation"]) in recovery_relations
            and _requires_atomic_reindex(
                before_by_relation[str(measurement["relation"])], measurement
            )
        )
        pending_reindex_relations = tuple(
            relation
            for relation in policy.get("relations_pending_reindex", [])
            if isinstance(relation, str) and relation in relations
        )
        reindex_relations = tuple(
            dict.fromkeys((*pending_reindex_relations, *measured_reindex_relations))
        )
        if reindex_relations:
            policy.update(
                {
                    "relations_pending_reindex": list(reindex_relations),
                    "reindex_attempted_at": datetime.now(UTC).isoformat(),
                    "measured_before": measured_before,
                    "measured_after_vacuum": measured_after_vacuum,
                }
            )
            self._record_recovery_policy(operation_id, policy)
            try:
                with self._owner.connection() as connection:
                    connection.commit()
                    connection.autocommit = True
                    try:
                        connection.execute(
                            "SELECT set_config('statement_timeout',%s,false)",
                            (f"{SPACE_RECOVERY_REINDEX_TIMEOUT_SECONDS}s",),
                        )
                        for relation in reindex_relations:
                            schema_name, table_name = relation.split(".", maxsplit=1)
                            connection.execute(
                                sql.SQL("REINDEX TABLE {}").format(
                                    sql.Identifier(schema_name, table_name)
                                )
                            )
                    finally:
                        connection.execute("RESET statement_timeout")
                        connection.autocommit = False
            except Exception as exc:
                policy["last_recovery_error"] = {
                    "code": "atomic_reindex_incomplete",
                    "sqlstate": getattr(exc, "sqlstate", None),
                    "message": "bounded atomic reindex did not complete",
                    "recorded_at": datetime.now(UTC).isoformat(),
                }
                self._record_recovery_policy(operation_id, policy)
                raise
        measured_after = self._measure_relations(relations)
        policy.pop("last_recovery_error", None)
        policy.update(
            {
                "operation": (
                    "vacuum_and_atomic_reindex"
                    if reindex_relations
                    else (
                        "vacuum_analyze_index_cleanup"
                        if recovery_relations
                        else "not_required_before_target_materialisation"
                    )
                ),
                "relations_recovered": list(recovery_relations),
                "relations_reindexed": list(reindex_relations),
                "relations_pending_reindex": [],
                "statement_timeout_seconds": SPACE_RECOVERY_STATEMENT_TIMEOUT_SECONDS,
                "reindex_timeout_seconds": SPACE_RECOVERY_REINDEX_TIMEOUT_SECONDS,
                "measured_before": measured_before,
                "measured_after_vacuum": measured_after_vacuum,
                "measured_after": measured_after,
                "completed_at": datetime.now(UTC).isoformat(),
                "automatic_destructive_maintenance": False,
                "next_step": "none",
            }
        )
        with self._owner.connection() as connection:
            row = connection.execute(
                """UPDATE ops.import_operation SET space_recovery_status='completed',
                space_recovery_policy_json=%s,version=version+1 WHERE id=%s
                AND status IN ('failed','cancelled') AND space_recovery_status='needed'
                RETURNING *""",
                (_json(policy), operation_id),
            ).fetchone()
            connection.commit()
        if row is None:
            latest = self._owner.get_import(operation_id)
            if latest["space_recovery_status"] == "completed":
                return latest
            raise ConflictError("space recovery state changed before completion was recorded")
        return _dict(row)

    def _record_recovery_policy(self, operation_id: uuid.UUID, policy: JsonObject) -> None:
        with self._owner.connection() as connection:
            connection.execute(
                """UPDATE ops.import_operation SET space_recovery_policy_json=%s,
                version=version+1 WHERE id=%s AND status IN ('failed','cancelled')
                AND space_recovery_status='needed'""",
                (_json(policy), operation_id),
            )
            connection.commit()

    def _measure_relations(self, relations: Sequence[str]) -> list[JsonObject]:
        measurements: list[JsonObject] = []
        with self._owner.connection() as connection:
            for relation in relations:
                schema_name, table_name = relation.split(".", maxsplit=1)
                row = connection.execute(
                    """SELECT %s AS relation,n_live_tup::bigint,n_dead_tup::bigint,
                    pg_relation_size(relid)::bigint AS heap_bytes,
                    pg_indexes_size(relid)::bigint AS index_bytes
                    FROM pg_stat_user_tables WHERE schemaname=%s AND relname=%s""",
                    (relation, schema_name, table_name),
                ).fetchone()
                if row is None:
                    raise ConflictError(f"registered recovery relation is unavailable: {relation}")
                measurements.append(_dict(row))
            connection.commit()
        return measurements


def _requires_atomic_reindex(before: JsonObject, after_vacuum: JsonObject) -> bool:
    dead_tuples = int(before["n_dead_tup"])
    live_tuples = int(before["n_live_tup"])
    index_bytes = int(after_vacuum["index_bytes"])
    return (
        dead_tuples >= SPACE_RECOVERY_REINDEX_MIN_DEAD_TUPLES
        and dead_tuples * 4 >= max(1, live_tuples)
        and index_bytes >= SPACE_RECOVERY_REINDEX_MIN_INDEX_BYTES
    )
