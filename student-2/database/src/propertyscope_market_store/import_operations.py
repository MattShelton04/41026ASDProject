"""Fenced, replayable sales import staging owned exclusively by the database service."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any, cast


class ImportConflictError(ValueError):
    """Immutable import identity or worker ownership does not match."""


class ImportLeaseConflictError(ImportConflictError):
    """The caller no longer owns the import worker lease."""


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _operation(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["publication"] = json.loads(value.pop("payload_json"))
    value["error"] = json.loads(value.pop("error_json") or "null")
    return value


class SalesImportOperations:
    def __init__(self, connect: Callable[[], sqlite3.Connection]) -> None:
        self._connect = connect

    def get(self, operation_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sales_import_operation WHERE id=?", (operation_id,)
            ).fetchone()
        return _operation(row) if row else None

    def create(self, publication: Mapping[str, Any]) -> dict[str, Any]:
        payload = _json(publication)
        release_id = str(uuid.UUID(str(publication["release_id"])))
        key = str(publication["idempotency_key"])
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            alias = connection.execute(
                "SELECT * FROM sales_import_alias WHERE idempotency_key=?", (key,)
            ).fetchone()
            if alias:
                if alias["payload_json"] != payload:
                    raise ImportConflictError("delivery key has different publication evidence")
                operation_id = alias["operation_id"]
            else:
                generation = connection.execute(
                    "SELECT * FROM sales_import_generation WHERE release_id=?", (release_id,)
                ).fetchone()
                if generation and (
                    generation["content_sha256"] != publication["content_sha256"]
                    or generation["record_count"] != publication["record_count"]
                ):
                    raise ImportConflictError("release identity has different digest or count")
                connection.execute(
                    "INSERT OR IGNORE INTO sales_import_generation VALUES (?,?,?,0)",
                    (release_id, publication["content_sha256"], publication["record_count"]),
                )
                active = connection.execute(
                    "SELECT * FROM sales_import_operation WHERE release_id=? "
                    "AND status IN ('queued','running','accepted')",
                    (release_id,),
                ).fetchone()
                if active:
                    original = json.loads(active["payload_json"])
                    if {k: v for k, v in original.items() if k != "idempotency_key"} != {
                        k: v for k, v in publication.items() if k != "idempotency_key"
                    }:
                        raise ImportConflictError(
                            "release identity has different manifest evidence"
                        )
                    operation_id = active["id"]
                else:
                    operation_id = str(uuid.uuid4())
                    connection.execute(
                        "INSERT INTO sales_import_operation "
                        "(id,release_id,payload_json,status,next_attempt_at,created_at) "
                        "VALUES (?,?,?,'queued',?,?)",
                        (operation_id, release_id, payload, now, now),
                    )
                connection.execute(
                    "INSERT INTO sales_import_alias VALUES (?,?,?)", (key, operation_id, payload)
                )
            connection.commit()
        result = self.get(operation_id)
        assert result is not None
        return result

    def claim(self) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE sales_import_operation SET status='failed',completed_at=?,"
                "lease_token=NULL,lease_until=NULL,error_json=? "
                "WHERE status='running' AND lease_until<=? AND attempt>=5",
                (
                    now,
                    _json(
                        {
                            "code": "import_retry_limit",
                            "message": "Worker retry limit reached",
                            "retryable": False,
                        }
                    ),
                    now,
                ),
            )
            connection.execute(
                "UPDATE sales_import_operation SET status='queued',attempt=attempt+1,"
                "lease_token=NULL,lease_until=NULL,next_attempt_at=? "
                "WHERE status='running' AND lease_until<=?",
                (now, now),
            )
            row = connection.execute(
                "SELECT id FROM sales_import_operation WHERE status='queued' "
                "AND next_attempt_at<=? "
                "AND NOT EXISTS (SELECT 1 FROM sales_import_operation WHERE status='running') "
                "ORDER BY created_at,id LIMIT 1",
                (now,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            connection.execute(
                "UPDATE sales_import_operation SET status='running',lease_token=?,lease_until=?,"
                "error_json=NULL WHERE id=?",
                (uuid.uuid4().hex, now + 120, row["id"]),
            )
            connection.commit()
        return self.get(row["id"])

    @staticmethod
    def _lease(connection: sqlite3.Connection, operation_id: str, token: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM sales_import_operation WHERE id=? AND status='running' "
            "AND lease_token=? AND lease_until>?",
            (operation_id, token, time.time()),
        ).fetchone()
        if row is None:
            raise ImportLeaseConflictError("import worker lease is stale")
        return cast(sqlite3.Row, row)

    def heartbeat(self, operation_id: str, token: str) -> None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._lease(connection, operation_id, token)
            connection.execute(
                "UPDATE sales_import_operation SET lease_until=? WHERE id=?",
                (time.time() + 120, operation_id),
            )
            connection.commit()

    def stage(
        self, operation_id: str, token: str, start: int, records: list[dict[str, Any]]
    ) -> None:
        if not records or len(records) > 2000 or start < 1:
            raise ValueError("stage requires 1-2000 records and a positive starting ordinal")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            operation = self._lease(connection, operation_id, token)
            publication = json.loads(operation["payload_json"])
            if (
                start > operation["rows_staged"] + 1
                or start + len(records) - 1 > publication["record_count"]
            ):
                raise ImportConflictError(
                    "staged rows must be contiguous within the declared count"
                )
            existing = {
                row["ordinal"]: row["record_sha256"]
                for row in connection.execute(
                    "SELECT ordinal,record_sha256 FROM sale_generation_record "
                    "WHERE release_id=? AND ordinal>=? AND ordinal<?",
                    (operation["release_id"], start, start + len(records)),
                )
            }
            rows = []
            for ordinal, record in enumerate(records, start):
                if record["release_id"] != operation["release_id"]:
                    raise ImportConflictError("staged row belongs to another release")
                encoded = _json(record)
                digest = hashlib.sha256(encoded.encode()).hexdigest()
                if ordinal in existing:
                    if existing[ordinal] != digest:
                        raise ImportConflictError("staged row replay has different evidence")
                    continue
                rows.append(
                    (
                        operation["release_id"],
                        ordinal,
                        record["source_business_key"],
                        record["source_revision"],
                        record.get("property_ref"),
                        record.get("contract_date"),
                        digest,
                        encoded,
                    )
                )
            try:
                connection.executemany(
                    "INSERT INTO sale_generation_record VALUES (?,?,?,?,?,?,?,?)", rows
                )
            except sqlite3.IntegrityError as exc:
                raise ImportConflictError("duplicate sales identity in artifact") from exc
            connection.execute(
                "UPDATE sales_import_generation SET stored_count=stored_count+? WHERE release_id=?",
                (len(rows), operation["release_id"]),
            )
            connection.execute(
                "UPDATE sales_import_operation SET rows_staged=max(rows_staged,?),lease_until=? "
                "WHERE id=?",
                (start + len(records) - 1, time.time() + 120, operation_id),
            )
            connection.commit()

    def finish(self, operation_id: str, token: str, *, error: Mapping[str, Any] | None) -> None:
        now = time.time()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            operation = self._lease(connection, operation_id, token)
            publication = json.loads(operation["payload_json"])
            status = "accepted"
            if error:
                status = (
                    "queued" if error.get("retryable") and operation["attempt"] < 5 else "failed"
                )
            else:
                generation = connection.execute(
                    "SELECT * FROM sales_import_generation WHERE release_id=?",
                    (operation["release_id"],),
                ).fetchone()
                if (
                    generation["stored_count"] != publication["record_count"]
                    or operation["rows_staged"] != publication["record_count"]
                ):
                    raise ImportConflictError("complete validated record count is required")
                connection.execute(
                    "INSERT INTO sales_current_generation VALUES (?,?,?) "
                    "ON CONFLICT(dataset_id) DO UPDATE SET release_id=excluded.release_id,"
                    "operation_id=excluded.operation_id WHERE "
                    "(SELECT created_at FROM sales_import_operation "
                    "WHERE id=sales_current_generation.operation_id)<=?",
                    (
                        publication["dataset_id"],
                        operation["release_id"],
                        operation_id,
                        operation["created_at"],
                    ),
                )
            connection.execute(
                "UPDATE sales_import_operation SET status=?,completed_at=?,error_json=?,"
                "lease_token=NULL,lease_until=NULL,next_attempt_at=?,attempt=attempt+? WHERE id=?",
                (
                    status,
                    None if status == "queued" else now,
                    _json(error) if error else None,
                    now + min(60, 2 ** operation["attempt"]),
                    int(status == "queued"),
                    operation_id,
                ),
            )
            connection.commit()
