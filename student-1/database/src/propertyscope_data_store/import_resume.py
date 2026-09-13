"""Explicit retry preparation, with row locks protecting loader ownership."""

from __future__ import annotations

import uuid
from typing import Any

from psycopg import Connection, errors

from .errors import ConflictError


def prepare_import_resume(connection: Connection[Any], run_id: uuid.UUID) -> None:
    """Reset only retryable failures; migration 060 retains the terminal evidence.

    Hold operation locks until the caller atomically requeues the run and tasks.
    A loader claim skips these locked rows. Never take over even an expired worker:
    the normal lease reconciliation must first establish its interrupted boundary.
    """
    try:
        operations = connection.execute(
            "SELECT status,error_json FROM ops.import_operation "
            "WHERE ingestion_run_id=%s FOR UPDATE NOWAIT",
            (run_id,),
        ).fetchall()
        active_tasks = connection.execute(
            """SELECT id FROM ops.run_task WHERE ingestion_run_id=%s
            AND status IN ('claimed','running') AND lease_expires_at>clock_timestamp()
            FOR UPDATE NOWAIT""",
            (run_id,),
        ).fetchall()
    except errors.LockNotAvailable as exc:
        raise ConflictError(
            "import operation is busy; retry resume after its worker settles"
        ) from exc
    if active_tasks:
        raise ConflictError("a run task worker is still active; wait for lease reconciliation")
    for operation in operations:
        if operation["status"] in {"claimed", "running"}:
            raise ConflictError("an import worker is still active; wait for lease reconciliation")
        if operation["status"] == "failed":
            error = operation["error_json"] or {}
            if error.get("retryable") is not True:
                raise ConflictError("non-retryable import failure requires a new reviewed run")
    connection.execute(
        """UPDATE ops.import_operation SET status='interrupted',
        lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
        started_at=NULL,finished_at=NULL,error_json=NULL,result_json=NULL,
        progress_phase=NULL,progress_phase_key=NULL,progress_rows=0,progress_bytes=0,
        progress_total_rows=NULL,progress_total_bytes=NULL,progress_updated_at=NULL,
        rows_in=0,rows_staged=0,rows_accepted=0,rows_rejected=0,version=version+1
        WHERE ingestion_run_id=%s AND status='failed' AND error_json->'retryable'='true'::jsonb""",
        (run_id,),
    )
