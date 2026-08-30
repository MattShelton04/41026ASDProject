"""Durable outbound consumer-import operations for reviewed release publication."""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from psycopg import Connection, errors

from propertyscope_data_store.errors import ConflictError, LeaseConflictError, NotFoundError
from propertyscope_data_store.persistence_support import json_document as _json
from propertyscope_data_store.persistence_support import normalise_row as _dict

JsonObject = dict[str, Any]
MAX_DELIVERY_ATTEMPTS = 5


class _ConsumerImportOwner(Protocol):
    def connection(self) -> AbstractContextManager[Connection[Any]]: ...

    def _fetch_one(self, query: str, params: Sequence[Any]) -> JsonObject | None: ...

    def _required(self, query: str, params: Sequence[Any]) -> JsonObject: ...


class _ConsumerImportOperations:
    """Persist short consumer callbacks and every subsequent replay boundary."""

    def __init__(self, owner: _ConsumerImportOwner) -> None:
        self._owner = owner

    def create(self, release_id: uuid.UUID, values: Mapping[str, Any]) -> tuple[JsonObject, bool]:
        key = str(values["idempotency_key"]).strip()
        comment = str(values["comment"]).strip()
        expected_version = int(values["expected_release_version"])
        if not key or not comment:
            raise ConflictError("publication idempotency key and comment are required")
        existing = self._owner._fetch_one(
            """SELECT operation.*,alias.artifact_path AS alias_artifact_path,
            alias.expected_release_version AS alias_expected_release_version,
            alias.review_comment AS alias_review_comment
            FROM ops.consumer_import_delivery_alias alias
            JOIN ops.consumer_import_operation operation
              ON operation.id=alias.consumer_import_operation_id
            WHERE alias.target_feature=%s AND alias.idempotency_key=%s""",
            (str(values["target_feature"]), key),
        )
        if existing is not None:
            self._assert_alias_replay(existing, release_id, values)
            return existing, False
        now = datetime.now(UTC)
        with self._owner.connection() as connection:
            release = connection.execute(
                "SELECT * FROM ops.dataset_release WHERE id=%s FOR SHARE", (release_id,)
            ).fetchone()
            if release is None:
                raise NotFoundError("release does not exist")
            if release["status"] != "awaiting_review":
                raise ConflictError("only a release awaiting review can be delivered")
            if int(release["version"]) != expected_version:
                raise ConflictError("release version does not match")
            expected_identity = self._identity_from_values(release_id, values)
            actual_identity = self._identity_from_release(release)
            if expected_identity != actual_identity:
                raise ConflictError("consumer import release evidence does not match")
            identity_operation = connection.execute(
                """SELECT * FROM ops.consumer_import_operation WHERE dataset_release_id=%s
                AND dataset_id=%s AND target_feature=%s AND schema_version=%s
                AND content_sha256=%s AND record_count=%s
                AND status NOT IN ('failed','rejected') ORDER BY requested_at LIMIT 1 FOR UPDATE""",
                expected_identity,
            ).fetchone()
            if identity_operation is not None:
                self._attach_alias(connection, identity_operation, release_id, values, now)
                connection.commit()
                return _dict(identity_operation), False
            failed_operation = connection.execute(
                """SELECT operation.*,receipt.status AS attached_receipt_status
                FROM ops.consumer_import_operation operation
                LEFT JOIN ops.publication_receipt receipt
                  ON receipt.id=operation.publication_receipt_id
                WHERE operation.dataset_release_id=%s AND operation.dataset_id=%s
                AND operation.target_feature=%s AND operation.schema_version=%s
                AND operation.content_sha256=%s AND operation.record_count=%s
                AND operation.status IN ('failed','rejected')
                AND operation.consumer_operation_id IS NOT NULL
                ORDER BY operation.requested_at,operation.id LIMIT 1 FOR UPDATE OF operation""",
                expected_identity,
            ).fetchone()
            if failed_operation is not None:
                attached_status = failed_operation.get("attached_receipt_status")
                if attached_status == "accepted" and failed_operation["status"] == "failed":
                    resumed = connection.execute(
                        """UPDATE ops.consumer_import_operation SET status='activation_pending',
                        phase_key='queue_activation',activation_attempt=activation_attempt+1,
                        release_activation_id=NULL,attempt_number=1,next_attempt_at=%s,
                        expected_release_version=%s,review_comment=%s,request_id=%s,
                        error_json=NULL,finished_at=NULL,lease_owner=NULL,lease_token=NULL,
                        lease_expires_at=NULL,heartbeat_at=NULL,version=version+1
                        WHERE id=%s RETURNING *""",
                        (
                            now,
                            expected_version,
                            comment,
                            str(values["request_id"]),
                            failed_operation["id"],
                        ),
                    ).fetchone()
                    if resumed is None:
                        raise ConflictError("consumer activation retry could not be persisted")
                    self._attach_alias(connection, resumed, release_id, values, now)
                    connection.commit()
                    return _dict(resumed), False
                if attached_status in {"accepted", "rejected", "failed"}:
                    self._attach_alias(connection, failed_operation, release_id, values, now)
                    connection.commit()
                    return _dict(failed_operation), False
                resumed_phase = (
                    "record_receipt" if failed_operation.get("result_json") is not None else "poll"
                )
                resumed_status = (
                    "receipt_pending" if resumed_phase == "record_receipt" else "polling"
                )
                resumed = connection.execute(
                    """UPDATE ops.consumer_import_operation SET status=%s,phase_key=%s,
                    attempt_number=1,next_attempt_at=%s,error_json=NULL,finished_at=NULL,
                    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                    version=version+1 WHERE id=%s RETURNING *""",
                    (resumed_status, resumed_phase, now, failed_operation["id"]),
                ).fetchone()
                if resumed is None:
                    raise ConflictError("consumer import retry could not be persisted")
                self._attach_alias(connection, resumed, release_id, values, now)
                connection.commit()
                return _dict(resumed), False
            accepted_receipt = connection.execute(
                """SELECT * FROM ops.publication_receipt WHERE dataset_release_id=%s
                AND target_feature=%s AND schema_version=%s AND content_sha256=%s
                AND status='accepted' AND rows_received=%s AND rows_accepted=%s
                AND rows_rejected=0 ORDER BY completed_at DESC LIMIT 1 FOR SHARE""",
                (
                    release_id,
                    release["target_feature"],
                    release["schema_version"],
                    release["content_sha256"],
                    int(release["record_count"]),
                    int(release["record_count"]),
                ),
            ).fetchone()
            resumed_receipt = accepted_receipt is not None
            try:
                row = connection.execute(
                    """INSERT INTO ops.consumer_import_operation (
                    id,dataset_release_id,dataset_id,target_feature,schema_version,content_sha256,
                    record_count,manifest_json,artifact_path,expected_release_version,review_comment,
                    idempotency_key,consumer_operation_id,publication_receipt_id,status,phase_key,
                    attempt_number,next_attempt_at,request_id,requested_at,version
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,%s,%s,%s,1)
                    RETURNING *""",
                    (
                        uuid.uuid4(),
                        release_id,
                        release["dataset_id"],
                        release["target_feature"],
                        release["schema_version"],
                        release["content_sha256"],
                        int(release["record_count"]),
                        _json(release["manifest_json"]),
                        str(values["artifact_path"]),
                        expected_version,
                        comment,
                        key,
                        (
                            accepted_receipt["consumer_operation_id"]
                            if accepted_receipt is not None
                            else None
                        ),
                        accepted_receipt["id"] if accepted_receipt is not None else None,
                        "activation_pending" if resumed_receipt else "queued",
                        "queue_activation" if resumed_receipt else "connect",
                        now,
                        str(values["request_id"]),
                        now,
                    ),
                ).fetchone()
                if row is None:
                    raise ConflictError("consumer import operation could not be persisted")
                self._attach_alias(connection, row, release_id, values, now)
                connection.commit()
            except errors.UniqueViolation:
                connection.rollback()
                raced = self._owner._fetch_one(
                    """SELECT operation.*,alias.artifact_path AS alias_artifact_path,
                    alias.expected_release_version AS alias_expected_release_version,
                    alias.review_comment AS alias_review_comment
                    FROM ops.consumer_import_delivery_alias alias
                    JOIN ops.consumer_import_operation operation
                      ON operation.id=alias.consumer_import_operation_id
                    WHERE alias.target_feature=%s AND alias.idempotency_key=%s""",
                    (str(values["target_feature"]), key),
                )
                if raced is not None:
                    self._assert_alias_replay(raced, release_id, values)
                    return raced, False
                return self.create(release_id, values)
        return _dict(row), True

    def get(self, operation_id: uuid.UUID) -> JsonObject:
        return self._owner._required(
            "SELECT * FROM ops.consumer_import_operation WHERE id=%s", (operation_id,)
        )

    def list_for_release(self, release_id: uuid.UUID) -> list[JsonObject]:
        with self._owner.connection() as connection:
            rows = connection.execute(
                """SELECT * FROM ops.consumer_import_operation
                WHERE dataset_release_id=%s ORDER BY requested_at""",
                (release_id,),
            ).fetchall()
        return [_dict(row) for row in rows]

    def claim(self, *, worker_id: str, lease_seconds: int) -> JsonObject | None:
        now = datetime.now(UTC)
        expires = now + timedelta(seconds=lease_seconds)
        token = uuid.uuid4().hex
        with self._owner.connection() as connection:
            connection.execute(
                """UPDATE ops.consumer_import_operation SET status='failed',phase_key='complete',
                finished_at=%s,error_json=%s,lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,heartbeat_at=NULL,version=version+1
                WHERE status='claimed' AND lease_expires_at<=%s AND attempt_number>=%s""",
                (
                    now,
                    _json(
                        {
                            "code": "consumer_import_retry_limit",
                            "message": "Consumer import exceeded its bounded retry limit",
                            "retryable": False,
                        }
                    ),
                    now,
                    MAX_DELIVERY_ATTEMPTS,
                ),
            )
            connection.execute(
                """UPDATE ops.consumer_import_operation SET status='interrupted',
                attempt_number=attempt_number+1,next_attempt_at=%s,error_json=%s,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                version=version+1 WHERE status='claimed' AND lease_expires_at<=%s
                AND attempt_number<%s""",
                (
                    now,
                    _json(
                        {
                            "code": "consumer_import_lease_expired",
                            "message": (
                                "Consumer import worker lease expired; durable phase will retry"
                            ),
                            "retryable": True,
                        }
                    ),
                    now,
                    MAX_DELIVERY_ATTEMPTS,
                ),
            )
            row = connection.execute(
                """WITH candidate AS (
                    SELECT id FROM ops.consumer_import_operation
                    WHERE status IN (
                        'queued','polling','receipt_pending','activation_pending',
                        'activation_queued','interrupted'
                    )
                      AND next_attempt_at<=%s
                    ORDER BY next_attempt_at,requested_at FOR UPDATE SKIP LOCKED LIMIT 1
                ) UPDATE ops.consumer_import_operation operation SET status='claimed',
                lease_owner=%s,lease_token=%s,lease_expires_at=%s,heartbeat_at=%s,
                started_at=COALESCE(started_at,%s),error_json=NULL,version=version+1
                FROM candidate WHERE operation.id=candidate.id RETURNING operation.*""",
                (now, worker_id, token, expires, now, now),
            ).fetchone()
            connection.commit()
        return _dict(row) if row is not None else None

    def acknowledge(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        consumer_operation_id: str,
        remote_status: str,
        result: Mapping[str, Any] | None,
        poll_seconds: int,
    ) -> JsonObject:
        if not consumer_operation_id.strip():
            raise ConflictError("consumer acknowledgement must contain its genuine operation id")
        if remote_status not in {"queued", "running", "accepted", "rejected", "failed"}:
            raise ConflictError("consumer acknowledgement status is invalid")
        terminal = remote_status in {"accepted", "rejected", "failed"}
        if terminal != (result is not None):
            raise ConflictError("terminal consumer acknowledgement requires one closed result")
        now = datetime.now(UTC)
        with self._owner.connection() as connection:
            try:
                row = connection.execute(
                    """UPDATE ops.consumer_import_operation SET consumer_operation_id=%s,
                    remote_status=%s,result_json=%s,status=%s,phase_key=%s,next_attempt_at=%s,
                    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                    version=version+1 WHERE id=%s AND status='claimed' AND lease_owner=%s
                    AND lease_token=%s AND lease_expires_at>%s RETURNING *""",
                    (
                        consumer_operation_id,
                        remote_status,
                        _json(result) if result is not None else None,
                        "receipt_pending" if terminal else "polling",
                        "record_receipt" if terminal else "poll",
                        now if terminal else now + timedelta(seconds=poll_seconds),
                        operation_id,
                        worker_id,
                        lease_token,
                        now,
                    ),
                ).fetchone()
                connection.commit()
            except errors.UniqueViolation as exc:
                raise ConflictError("consumer operation id belongs to another delivery") from exc
        if row is None:
            raise LeaseConflictError("consumer import lease is stale or owned by another worker")
        return _dict(row)

    def retry(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        error: Mapping[str, Any],
        retry_seconds: int,
    ) -> JsonObject:
        now = datetime.now(UTC)
        retryable = error.get("retryable") is True
        with self._owner.connection() as connection:
            row = connection.execute(
                """UPDATE ops.consumer_import_operation SET
                status=CASE WHEN %s AND attempt_number<%s THEN 'interrupted' ELSE 'failed' END,
                phase_key=CASE WHEN %s AND attempt_number<%s THEN phase_key ELSE 'complete' END,
                next_attempt_at=%s,error_json=%s,
                attempt_number=CASE WHEN %s AND attempt_number<%s
                    THEN attempt_number+1 ELSE attempt_number END,
                finished_at=CASE WHEN %s AND attempt_number<%s THEN NULL ELSE %s END,
                lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,heartbeat_at=NULL,version=version+1
                WHERE id=%s AND status='claimed' AND lease_owner=%s AND lease_token=%s
                AND lease_expires_at>%s RETURNING *""",
                (
                    retryable,
                    MAX_DELIVERY_ATTEMPTS,
                    retryable,
                    MAX_DELIVERY_ATTEMPTS,
                    now + timedelta(seconds=retry_seconds),
                    _json(error),
                    retryable,
                    MAX_DELIVERY_ATTEMPTS,
                    retryable,
                    MAX_DELIVERY_ATTEMPTS,
                    now,
                    operation_id,
                    worker_id,
                    lease_token,
                    now,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise LeaseConflictError("consumer import lease is stale or owned by another worker")
        return _dict(row)

    def attach_receipt(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        receipt_id: uuid.UUID,
        receipt_status: str,
    ) -> JsonObject:
        if receipt_status not in {"accepted", "rejected", "failed"}:
            raise ConflictError("consumer receipt status is invalid")
        accepted = receipt_status == "accepted"
        now = datetime.now(UTC)
        with self._owner.connection() as connection:
            row = connection.execute(
                """UPDATE ops.consumer_import_operation operation SET publication_receipt_id=%s,
                status=%s,phase_key=%s,finished_at=%s,lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,heartbeat_at=NULL,version=operation.version+1
                FROM ops.publication_receipt receipt WHERE operation.id=%s
                AND operation.status='claimed' AND operation.phase_key='record_receipt'
                AND operation.lease_owner=%s AND operation.lease_token=%s
                AND operation.lease_expires_at>%s AND receipt.id=%s
                AND receipt.dataset_release_id=operation.dataset_release_id
                AND receipt.target_feature=operation.target_feature
                AND receipt.consumer_operation_id=operation.consumer_operation_id
                AND receipt.schema_version=operation.schema_version
                AND receipt.content_sha256=operation.content_sha256
                AND receipt.status=%s AND receipt.rows_received<=operation.record_count
                AND (receipt.status<>'accepted' OR (
                    receipt.rows_received=operation.record_count
                    AND receipt.rows_accepted=operation.record_count
                    AND receipt.rows_rejected=0)) RETURNING operation.*""",
                (
                    receipt_id,
                    "activation_pending" if accepted else receipt_status,
                    "queue_activation" if accepted else "complete",
                    None if accepted else now,
                    operation_id,
                    worker_id,
                    lease_token,
                    now,
                    receipt_id,
                    receipt_status,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise LeaseConflictError("consumer import receipt phase lease is stale")
        return _dict(row)

    def attach_activation(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        activation_id: uuid.UUID,
    ) -> JsonObject:
        now = datetime.now(UTC)
        with self._owner.connection() as connection:
            row = connection.execute(
                """UPDATE ops.consumer_import_operation operation SET release_activation_id=%s,
                status='activation_queued',phase_key='wait_activation',finished_at=NULL,
                next_attempt_at=%s,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                version=operation.version+1 FROM ops.release_activation activation
                WHERE operation.id=%s AND operation.status='claimed'
                AND operation.phase_key='queue_activation' AND operation.lease_owner=%s
                AND operation.lease_token=%s AND operation.lease_expires_at>%s
                AND activation.id=%s
                AND activation.dataset_release_id=operation.dataset_release_id
                AND activation.publication_receipt_id=operation.publication_receipt_id
                AND activation.expected_release_version=operation.expected_release_version
                AND activation.status IN ('queued','claimed','running','interrupted','succeeded')
                RETURNING operation.*""",
                (
                    activation_id,
                    now + timedelta(seconds=2),
                    operation_id,
                    worker_id,
                    lease_token,
                    now,
                    activation_id,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise LeaseConflictError("consumer import activation phase lease is stale")
        return _dict(row)

    def record_activation_outcome(
        self,
        operation_id: uuid.UUID,
        *,
        worker_id: str,
        lease_token: str,
        activation_status: str,
        error: Mapping[str, Any] | None,
        poll_seconds: int,
    ) -> JsonObject:
        if activation_status not in {
            "queued",
            "claimed",
            "running",
            "interrupted",
            "succeeded",
            "failed",
        }:
            raise ConflictError("release activation status is invalid")
        now = datetime.now(UTC)
        terminal = activation_status in {"succeeded", "failed"}
        with self._owner.connection() as connection:
            row = connection.execute(
                """UPDATE ops.consumer_import_operation operation SET
                status=CASE WHEN %s='succeeded' THEN 'published'
                    WHEN %s='failed' THEN 'failed' ELSE 'activation_queued' END,
                phase_key=CASE WHEN %s IN ('succeeded','failed') THEN 'complete'
                    ELSE 'wait_activation' END,
                next_attempt_at=%s,error_json=%s,finished_at=CASE WHEN %s THEN %s ELSE NULL END,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                version=operation.version+1 FROM ops.release_activation activation
                WHERE operation.id=%s AND operation.status='claimed'
                AND operation.phase_key='wait_activation' AND operation.lease_owner=%s
                AND operation.lease_token=%s AND operation.lease_expires_at>%s
                AND activation.id=operation.release_activation_id
                AND activation.dataset_release_id=operation.dataset_release_id
                AND activation.publication_receipt_id=operation.publication_receipt_id
                AND activation.status=%s RETURNING operation.*""",
                (
                    activation_status,
                    activation_status,
                    activation_status,
                    now if terminal else now + timedelta(seconds=poll_seconds),
                    _json(error) if error is not None else None,
                    terminal,
                    now,
                    operation_id,
                    worker_id,
                    lease_token,
                    now,
                    activation_status,
                ),
            ).fetchone()
            connection.commit()
        if row is None:
            raise LeaseConflictError("consumer import activation monitor lease is stale")
        return _dict(row)

    @staticmethod
    def _identity_from_release(release: Mapping[str, Any]) -> tuple[str, ...]:
        return (
            str(release["id"]),
            str(release["dataset_id"]),
            str(release["target_feature"]),
            str(release["schema_version"]),
            str(release["content_sha256"]),
            str(int(release["record_count"])),
        )

    @staticmethod
    def _identity_from_values(release_id: uuid.UUID, values: Mapping[str, Any]) -> tuple[str, ...]:
        return (
            str(release_id),
            str(values["dataset_id"]),
            str(values["target_feature"]),
            str(values["schema_version"]),
            str(values["content_sha256"]),
            str(int(values["record_count"])),
        )

    def _attach_alias(
        self,
        connection: Connection[Any],
        operation: Mapping[str, Any],
        release_id: uuid.UUID,
        values: Mapping[str, Any],
        requested_at: datetime,
    ) -> None:
        inserted = connection.execute(
            """INSERT INTO ops.consumer_import_delivery_alias (
            target_feature,idempotency_key,consumer_import_operation_id,dataset_release_id,
            dataset_id,schema_version,content_sha256,record_count,artifact_path,
            expected_release_version,review_comment,request_id,requested_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (target_feature,idempotency_key) DO NOTHING
            RETURNING consumer_import_operation_id""",
            (
                str(values["target_feature"]),
                str(values["idempotency_key"]).strip(),
                operation["id"],
                release_id,
                str(values["dataset_id"]),
                str(values["schema_version"]),
                str(values["content_sha256"]),
                int(values["record_count"]),
                str(values["artifact_path"]),
                int(values["expected_release_version"]),
                str(values["comment"]).strip(),
                str(values["request_id"]),
                requested_at,
            ),
        ).fetchone()
        if inserted is not None:
            return
        alias = connection.execute(
            """SELECT alias.*,operation.dataset_id,operation.schema_version,
            operation.content_sha256,operation.record_count
            FROM ops.consumer_import_delivery_alias alias
            JOIN ops.consumer_import_operation operation
              ON operation.id=alias.consumer_import_operation_id
            WHERE alias.target_feature=%s AND alias.idempotency_key=%s FOR SHARE""",
            (str(values["target_feature"]), str(values["idempotency_key"]).strip()),
        ).fetchone()
        if alias is None:
            raise ConflictError("publication delivery key could not be durably attached")
        self._assert_alias_replay(alias, release_id, values)
        if str(alias["consumer_import_operation_id"]) != str(operation["id"]):
            raise ConflictError("publication delivery key belongs to another operation")

    def _assert_alias_replay(
        self, existing: Mapping[str, Any], release_id: uuid.UUID, values: Mapping[str, Any]
    ) -> None:
        existing_identity = (
            str(existing["dataset_release_id"]),
            str(existing["dataset_id"]),
            str(existing["target_feature"]),
            str(existing["schema_version"]),
            str(existing["content_sha256"]),
            str(int(existing["record_count"])),
        )
        if (
            existing_identity != self._identity_from_values(release_id, values)
            or int(
                existing.get("alias_expected_release_version", existing["expected_release_version"])
            )
            != int(values["expected_release_version"])
            or str(existing.get("alias_review_comment", existing["review_comment"]))
            != str(values["comment"]).strip()
            or str(existing.get("alias_artifact_path", existing["artifact_path"]))
            != str(values["artifact_path"])
        ):
            raise ConflictError("publication idempotency key arguments do not match")
