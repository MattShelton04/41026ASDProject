"""Explicit failed-import retry using disposable, fully migrated PostgreSQL databases."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from propertyscope_data_store.errors import ConflictError
from propertyscope_data_store.migrations import migrate
from propertyscope_data_store.repository import PropertyScopeStore

ADMIN_URL = os.getenv("PROPERTYSCOPE_TEST_POSTGRES_URL", "").strip()
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="requires disposable PostgreSQL test URL")
RUN_ID = uuid.UUID("30000000-0000-0000-0000-000000000001")
OPERATION_ID = uuid.UUID("70000000-0000-0000-0000-000000000001")


@pytest.fixture
def retry_store(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[PropertyScopeStore, str]]:
    database = f"propertyscope_retry_{uuid.uuid4().hex}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    url = make_conninfo(ADMIN_URL, dbname=database)
    try:
        with psycopg.connect(url, row_factory=dict_row) as connection:
            migrate(connection)
            connection.execute(
                """UPDATE ops.ingestion_run SET status='interrupted',requested_scope_json=
                '{"profile":"full-data","all_records":true}' WHERE id=%s""",
                (RUN_ID,),
            )
            connection.execute(
                """UPDATE ops.run_task SET status='retry_wait',lease_owner=NULL,lease_token=NULL,
                lease_expires_at=NULL,progress_rows=123 WHERE ingestion_run_id=%s""",
                (RUN_ID,),
            )

        @contextmanager
        def connected() -> Iterator[psycopg.Connection[dict[str, Any]]]:
            with psycopg.connect(url, row_factory=dict_row) as connection:
                connection.execute("SET LOCAL statement_timeout='2s'")
                yield connection

        store = PropertyScopeStore.__new__(PropertyScopeStore)
        monkeypatch.setattr(store, "connection", connected)
        yield store, url
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


def fail_operation(url: str, error: dict[str, Any]) -> None:
    with psycopg.connect(url) as connection:
        connection.execute(
            """UPDATE ops.import_operation SET status='failed',error_json=%s,
            progress_phase_key='capacity_preflight',progress_rows=123,rows_staged=123,
            finished_at=now() WHERE id=%s""",
            (Jsonb(error), OPERATION_ID),
        )


def test_explicit_retry_retains_failure_evidence_through_success(
    retry_store: tuple[PropertyScopeStore, str],
) -> None:
    store, url = retry_store
    failure = {
        "code": "insufficient_loader_database_capacity",
        "retryable": True,
        "details": {"capacity_bytes": 137438953472},
    }
    fail_operation(url, failure)
    before = store.get_import(OPERATION_ID)
    assert before["failure_attempts"][0]["error_json"] == failure
    assert before["failure_attempts"][0]["progress_rows"] == 123
    with store.connection() as connection:
        accepted_before = connection.execute(
            "SELECT id FROM ops.dataset_release WHERE status='accepted' ORDER BY id"
        ).fetchall()
    with pytest.raises(ConflictError, match="cannot be enqueued"):
        store.enqueue_import(OPERATION_ID)
    store.resume_run(RUN_ID)
    resumed = store.get_import(OPERATION_ID)
    assert resumed["status"] == "interrupted" and resumed["error_json"] is None
    assert resumed["progress_rows"] == 0 and resumed["started_at"] is None
    assert resumed["failure_attempts"] == before["failure_attempts"]
    queued = store.enqueue_import(OPERATION_ID)
    assert queued["status"] == "queued" and queued["attempt_number"] == 2
    claimed = store.claim_import(worker_id="retry-test", lease_seconds=60)
    assert claimed is not None and str(claimed["id"]) == str(OPERATION_ID)
    store.finish_import(
        OPERATION_ID,
        worker_id="retry-test",
        lease_token=str(claimed["lease_token"]),
        status="succeeded",
        counts={"rows_in": 10, "rows_staged": 10, "rows_accepted": 10},
        result={"verified": True},
        error=None,
    )
    finished = store.get_import(OPERATION_ID)
    assert finished["status"] == "succeeded" and finished["attempt_number"] == 2
    assert finished["failure_attempts"] == before["failure_attempts"]
    assert "lease_token" not in finished["failure_attempts"][0]
    with store.connection() as connection:
        assert (
            connection.execute(
                "SELECT id FROM ops.dataset_release WHERE status='accepted' ORDER BY id"
            ).fetchall()
            == accepted_before
        )
        task = connection.execute(
            "SELECT status,progress_rows FROM ops.run_task WHERE ingestion_run_id=%s", (RUN_ID,)
        ).fetchone()
        assert task == {"status": "pending", "progress_rows": 0}


@pytest.mark.parametrize("retryable", [False, None, "true"])
def test_nonretryable_quality_failure_cannot_be_reset(
    retry_store: tuple[PropertyScopeStore, str],
    retryable: object,
) -> None:
    store, url = retry_store
    fail_operation(url, {"code": "quality_gate_failed", "retryable": retryable})
    before = store.get_import(OPERATION_ID)
    with pytest.raises(ConflictError, match="non-retryable"):
        store.resume_run(RUN_ID)
    assert store.get_import(OPERATION_ID) == before
    assert store.get_run(RUN_ID)["status"] == "interrupted"


@pytest.mark.parametrize("lease_seconds", [60, -60])
def test_resume_never_takes_over_an_unreconciled_loader(
    retry_store: tuple[PropertyScopeStore, str],
    lease_seconds: int,
) -> None:
    store, url = retry_store
    with psycopg.connect(url) as connection:
        connection.execute(
            """UPDATE ops.import_operation SET status='running',lease_owner='active',
            lease_token='active-token',lease_expires_at=now()+%s*interval '1 second'
            WHERE id=%s""",
            (lease_seconds, OPERATION_ID),
        )
    with pytest.raises(ConflictError, match="worker is still active"):
        store.resume_run(RUN_ID)
    assert store.get_import(OPERATION_ID)["lease_token"] == "active-token"
    assert store.get_run(RUN_ID)["status"] == "interrupted"


def test_resume_refuses_a_locked_operation_without_waiting_for_its_worker(
    retry_store: tuple[PropertyScopeStore, str],
) -> None:
    store, url = retry_store
    fail_operation(url, {"code": "dependency_unavailable", "retryable": True})
    with psycopg.connect(url) as worker:
        worker.execute(
            "SELECT id FROM ops.import_operation WHERE id=%s FOR UPDATE", (OPERATION_ID,)
        )
        with pytest.raises(ConflictError, match="operation is busy"):
            store.resume_run(RUN_ID)
    assert store.get_import(OPERATION_ID)["status"] == "failed"
    assert store.get_run(RUN_ID)["status"] == "interrupted"


def test_resume_does_not_reset_an_import_while_its_runner_lease_is_active(
    retry_store: tuple[PropertyScopeStore, str],
) -> None:
    store, url = retry_store
    fail_operation(url, {"code": "dependency_unavailable", "retryable": True})
    with psycopg.connect(url) as connection:
        connection.execute(
            """UPDATE ops.run_task SET status='running',lease_owner='runner',
            lease_token='runner-token',lease_expires_at=now()+interval '1 minute'
            WHERE ingestion_run_id=%s""",
            (RUN_ID,),
        )
    with pytest.raises(ConflictError, match="run task worker is still active"):
        store.resume_run(RUN_ID)
    assert store.get_import(OPERATION_ID)["status"] == "failed"
    assert store.get_run(RUN_ID)["status"] == "interrupted"


def test_later_space_recovery_evidence_survives_retry_and_success(
    retry_store: tuple[PropertyScopeStore, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, url = retry_store
    with psycopg.connect(url) as connection:
        connection.execute(
            """UPDATE ops.import_operation SET status='running',import_profile_key='psi-sales',
            lease_owner='loader',lease_token='first-token',
            lease_expires_at=now()+interval '1 minute',progress_phase_key='target_materialisation'
            WHERE id=%s""",
            (OPERATION_ID,),
        )
    error = {"code": "dependency_unavailable", "retryable": True}
    store.finish_import(
        OPERATION_ID,
        worker_id="loader",
        lease_token="first-token",
        status="failed",
        counts={"rows_in": 123},
        result=None,
        error=error,
    )
    original = store.get_import(OPERATION_ID)["failure_attempts"][0]
    assert "measured_before" not in original["space_recovery_policy_json"]
    # Exercise the actual bounded VACUUM/REINDEX and evidence persistence without
    # requiring a multi-gigabyte bloated relation in a disposable test database.
    monkeypatch.setattr(
        "propertyscope_data_store._import_operations._requires_atomic_reindex",
        lambda before, after: before["relation"] == "warehouse.psi_sale",
    )
    recovered = store.recover_import_space(OPERATION_ID)
    assert recovered["space_recovery_status"] == "completed"
    policy = recovered["space_recovery_policy_json"]
    assert policy["measured_before"] and policy["measured_after"]
    assert policy["relations_reindexed"] == ["warehouse.psi_sale"]
    evidence = store.get_import(OPERATION_ID)["failure_attempts"][0]
    assert evidence["error_json"] == original["error_json"] == error
    assert evidence["space_recovery_policy_json"] == original["space_recovery_policy_json"]
    assert evidence["recovery_events"][0]["recovery_status"] == "completed"
    assert evidence["recovery_events"][0]["policy_json"] == policy
    assert len(evidence["recovery_events"]) >= 3
    store.resume_run(RUN_ID)
    store.enqueue_import(OPERATION_ID)
    claimed = store.claim_import(worker_id="second-loader", lease_seconds=60)
    assert claimed is not None and str(claimed["id"]) == str(OPERATION_ID)
    store.finish_import(
        OPERATION_ID,
        worker_id="second-loader",
        lease_token=str(claimed["lease_token"]),
        status="succeeded",
        counts={"rows_accepted": 123},
        result={"verified": True},
        error=None,
    )
    successful = store.get_import(OPERATION_ID)
    assert successful["space_recovery_policy_json"] == {}
    assert successful["failure_attempts"][0] == evidence


def test_upgrade_does_not_hide_or_guess_ownership_of_inherited_recovery_policy(
    retry_store: tuple[PropertyScopeStore, str],
) -> None:
    store, url = retry_store
    inherited_policy = {
        "measured_before": [{"relation": "warehouse.psi_sale", "heap_bytes": 123}],
        "relations_reindexed": ["warehouse.psi_sale"],
        "completed_at": "2026-09-13T09:00:00Z",
    }
    with psycopg.connect(url, row_factory=dict_row) as connection:
        # Only this fixture's unique disposable database is reverted to its
        # through-060 state, reproducing the real upgrade ordering precisely.
        connection.execute("DROP TABLE ops.import_recovery_attribution")
        connection.execute("DROP TRIGGER import_recovery_evidence_capture ON ops.import_operation")
        connection.execute("DROP FUNCTION ops.capture_import_recovery_evidence()")
        connection.execute("DROP TABLE ops.import_recovery_evidence")
        connection.execute(
            "DELETE FROM public.propertyscope_schema_migration WHERE version IN "
            "('061_import_recovery_evidence.sql','062_import_recovery_attribution.sql')"
        )
        connection.execute(
            """UPDATE ops.import_operation SET status='failed',error_json=
            '{"code":"dependency_unavailable","retryable":true}' WHERE id=%s""",
            (OPERATION_ID,),
        )
        connection.execute(
            """UPDATE ops.import_operation SET space_recovery_status='completed',
            space_recovery_policy_json=%s WHERE id=%s""",
            (Jsonb(inherited_policy), OPERATION_ID),
        )
        connection.execute(
            "UPDATE ops.import_operation SET status='interrupted' WHERE id=%s", (OPERATION_ID,)
        )
        connection.execute(
            """UPDATE ops.import_operation SET status='running',attempt_number=2,
            lease_owner='upgrade-loader',lease_token='upgrade-token',
            lease_expires_at=now()+interval '1 minute' WHERE id=%s""",
            (OPERATION_ID,),
        )
        connection.commit()
        migrate(connection)
        recorded = connection.execute(
            "SELECT attempt_number,policy_json FROM ops.import_recovery_evidence "
            "WHERE import_operation_id=%s",
            (OPERATION_ID,),
        ).fetchall()
        assert recorded == [{"attempt_number": 2, "policy_json": inherited_policy}]
    upgraded = store.get_import(OPERATION_ID)
    assert upgraded["failure_attempts"][0]["attempt_number"] == 1
    assert upgraded["failure_attempts"][0]["recovery_events"] == []
    legacy = upgraded["unattributed_recovery_events"]
    assert len(legacy) == 1
    assert legacy[0]["recorded_attempt_number"] == 2
    assert legacy[0]["attribution"] == "legacy_attempt_unverified"
    assert legacy[0]["policy_json"] == inherited_policy
    store.finish_import(
        OPERATION_ID,
        worker_id="upgrade-loader",
        lease_token="upgrade-token",
        status="succeeded",
        counts={"rows_accepted": 123},
        result={"verified": True},
        error=None,
    )
    successful = store.get_import(OPERATION_ID)
    assert successful["space_recovery_policy_json"] == {}
    assert successful["unattributed_recovery_events"] == legacy
    assert successful["failure_attempts"] == upgraded["failure_attempts"]
