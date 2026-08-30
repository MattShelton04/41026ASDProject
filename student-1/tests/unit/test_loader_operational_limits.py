from __future__ import annotations

import hashlib
import uuid
from contextlib import nullcontext
from pathlib import Path
from typing import Any, cast

import pytest

from propertyscope_data_store.configuration import (
    DEFAULT_LOADER_ARTIFACT_EXPANSION_FACTOR,
    DEFAULT_LOADER_DATABASE_CAPACITY_BYTES,
    DEFAULT_LOADER_DISK_RESERVE_BYTES,
    DEFAULT_LOADER_TEMP_FILE_LIMIT_KIB,
    StoreSettings,
)
from propertyscope_data_store.loader import (
    DatabaseLoader,
    LoaderResourceLimitError,
    _safe_loader_error,
)
from propertyscope_data_store.repository import PropertyScopeStore


class _RecordingConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute(self, query: str) -> None:
        self.queries.append(query)


def test_store_applies_loader_temp_limit_only_to_the_current_transaction() -> None:
    connection = _RecordingConnection()
    store = cast(Any, object.__new__(PropertyScopeStore))
    store._loader_temp_file_limit_kib = 2 * 1024 * 1024

    store._apply_loader_transaction_limits(connection)

    assert connection.queries == ["SET LOCAL temp_file_limit = '2097152kB'"]
    assert all(
        "ALTER SYSTEM" not in query and "SET GLOBAL" not in query for query in connection.queries
    )


def test_store_observes_current_database_size_through_the_owning_connection() -> None:
    class SizeConnection:
        def __init__(self) -> None:
            self.query = ""

        def execute(self, query: str) -> SizeConnection:
            self.query = query
            return self

        def fetchone(self) -> dict[str, int]:
            return {"database_size_bytes": 12_345}

    connection = SizeConnection()
    store = cast(Any, object.__new__(PropertyScopeStore))
    store.connection = lambda: nullcontext(connection)

    assert PropertyScopeStore.database_size_bytes(store) == 12_345
    assert connection.query == (
        "SELECT pg_database_size(current_database())::bigint AS database_size_bytes"
    )


def test_loader_limit_configuration_is_typed_and_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROPERTYSCOPE_DATABASE_URL", "postgresql://database")
    monkeypatch.setenv("PROPERTYSCOPE_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("PROPERTYSCOPE_LOADER_TEMP_FILE_LIMIT_KIB", "2097152")
    monkeypatch.setenv("PROPERTYSCOPE_LOADER_DISK_RESERVE_BYTES", "1073741824")
    monkeypatch.setenv("PROPERTYSCOPE_LOADER_ARTIFACT_EXPANSION_FACTOR", "5")
    monkeypatch.setenv("PROPERTYSCOPE_POSTGRES_CAPACITY_BYTES", "68719476736")

    settings = StoreSettings.from_environment()

    assert settings.loader_temp_file_limit_kib == 2 * 1024 * 1024
    assert settings.loader_disk_reserve_bytes == 1024 * 1024 * 1024
    assert settings.loader_artifact_expansion_factor == 5
    assert settings.loader_database_capacity_bytes == 64 * 1024 * 1024 * 1024

    monkeypatch.setenv("PROPERTYSCOPE_LOADER_ARTIFACT_EXPANSION_FACTOR", "0")
    with pytest.raises(RuntimeError, match="must be between 1 and 16"):
        StoreSettings.from_environment()

    monkeypatch.setenv("PROPERTYSCOPE_LOADER_ARTIFACT_EXPANSION_FACTOR", "3")
    monkeypatch.setenv("PROPERTYSCOPE_POSTGRES_CAPACITY_BYTES", "1024")
    with pytest.raises(RuntimeError, match="must be between 8589934592"):
        StoreSettings.from_environment()


def test_loader_limit_configuration_has_fail_closed_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PROPERTYSCOPE_DATABASE_URL", "postgresql://database")
    monkeypatch.setenv("PROPERTYSCOPE_ARTIFACT_ROOT", str(tmp_path))
    for name in (
        "PROPERTYSCOPE_LOADER_TEMP_FILE_LIMIT_KIB",
        "PROPERTYSCOPE_LOADER_DISK_RESERVE_BYTES",
        "PROPERTYSCOPE_LOADER_ARTIFACT_EXPANSION_FACTOR",
        "PROPERTYSCOPE_POSTGRES_CAPACITY_BYTES",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = StoreSettings.from_environment()

    assert settings.loader_temp_file_limit_kib == DEFAULT_LOADER_TEMP_FILE_LIMIT_KIB
    assert settings.loader_disk_reserve_bytes == DEFAULT_LOADER_DISK_RESERVE_BYTES
    assert settings.loader_artifact_expansion_factor == DEFAULT_LOADER_ARTIFACT_EXPANSION_FACTOR
    assert settings.loader_database_capacity_bytes == DEFAULT_LOADER_DATABASE_CAPACITY_BYTES


class _PreflightStore:
    def __init__(self, work: dict[str, Any]) -> None:
        self.operation_id = uuid.UUID(str(work["id"]))
        self.work = work
        self.destination_started = False
        self.finished: dict[str, Any] | None = None
        self.recovery_requested: uuid.UUID | None = None
        self.accepted_predecessor = "50000000-0000-0000-0000-000000000001"
        self.current_database_bytes = 1024

    def claim_release_activation(self, **_: Any) -> None:
        return None

    def claim_import(self, **_: Any) -> dict[str, Any]:
        return {"id": self.operation_id, "lease_token": "loader-lease"}

    def heartbeat_import(self, *_: Any, **__: Any) -> None:
        return None

    def import_work(self, operation_id: uuid.UUID) -> dict[str, Any]:
        assert operation_id == self.operation_id
        return self.work

    def import_cancel_requested(self, operation_id: uuid.UUID) -> bool:
        assert operation_id == self.operation_id
        return False

    def database_size_bytes(self) -> int:
        return self.current_database_bytes

    def execute_stream_import_profile(self, *_: Any, **__: Any) -> None:
        self.destination_started = True
        raise AssertionError("destination materialisation must not start")

    def execute_import_profile(self, *_: Any, **__: Any) -> None:
        self.destination_started = True
        raise AssertionError("destination materialisation must not start")

    def finish_import(self, *_: Any, **values: Any) -> None:
        self.finished = values

    def recover_import_space(self, operation_id: uuid.UUID) -> None:
        self.recovery_requested = operation_id


def test_insufficient_database_capacity_fails_despite_artifact_headroom_and_preserves_predecessor(
    tmp_path: Path,
) -> None:
    payload = b'{"record":1}\n'
    digest = hashlib.sha256(payload).hexdigest()
    relative = Path("sha256") / digest[:2] / digest
    artifact = tmp_path / relative
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(payload)
    work = {
        "id": "70000000-0000-0000-0000-000000000051",
        "import_profile_key": "psi-sales",
        "storage_key": relative.as_posix(),
        "artifact_bytes": len(payload),
        "content_sha256": digest,
        "media_type": "application/x-ndjson",
        "candidate_release_id": "60000000-0000-0000-0000-000000000051",
    }
    store = _PreflightStore(work)
    predecessor = store.accepted_predecessor
    loader = DatabaseLoader(
        cast(Any, store),
        tmp_path,
        worker_id="loader-limits",
        disk_reserve_bytes=100,
        artifact_expansion_factor=2,
        temp_file_limit_kib=64 * 1024,
        database_capacity_bytes=store.current_database_bytes + 64 * 1024 * 1024 + 100,
        disk_free_bytes=lambda _: 1024 * 1024 * 1024 * 1024,
    )

    assert loader.run_once() is True

    assert store.destination_started is False
    assert store.recovery_requested == store.operation_id
    assert store.accepted_predecessor == predecessor
    assert artifact.read_bytes() == payload
    assert store.finished is not None
    assert store.finished["status"] == "failed"
    assert store.finished["counts"] == {
        "rows_in": 0,
        "rows_staged": 0,
        "rows_accepted": 0,
        "rows_rejected": 0,
    }
    error = store.finished["error"]
    assert error["code"] == "insufficient_loader_database_capacity"
    assert error["category"] == "resource_limit"
    assert error["retryable"] is True
    assert error["details"] == {
        "artifact_bytes": len(payload),
        "artifact_available_free_bytes": 1024 * 1024 * 1024 * 1024,
        "database_size_bytes": store.current_database_bytes,
        "database_capacity_bytes": store.current_database_bytes + 64 * 1024 * 1024 + 100,
        "database_available_headroom_bytes": 64 * 1024 * 1024 + 100,
        "required_database_headroom_bytes": len(payload) * 2 + 100 + 64 * 1024 * 1024,
        "projected_database_bytes": (
            store.current_database_bytes + len(payload) * 2 + 100 + 64 * 1024 * 1024
        ),
        "artifact_expansion_factor": 2,
        "database_growth_allowance_bytes": len(payload) * 2,
        "temporary_file_allowance_bytes": 64 * 1024 * 1024,
        "reserve_bytes": 100,
    }
    assert str(tmp_path) not in str(error)


def test_missing_database_capacity_fails_closed_before_database_size_lookup(tmp_path: Path) -> None:
    store = _PreflightStore({"id": uuid.uuid4()})
    loader = DatabaseLoader(
        cast(Any, store),
        tmp_path,
        worker_id="loader-limits",
        disk_reserve_bytes=0,
        artifact_expansion_factor=1,
        temp_file_limit_kib=64 * 1024,
        database_capacity_bytes=None,
        disk_free_bytes=lambda _: 10**12,
    )

    with pytest.raises(LoaderResourceLimitError) as captured:
        loader._preflight_materialisation_capacity(1)

    assert captured.value.code == "loader_database_capacity_unconfigured"
    assert captured.value.retryable is True


def test_database_size_observation_failure_is_not_masked_by_artifact_capacity(
    tmp_path: Path,
) -> None:
    store = _PreflightStore({"id": uuid.uuid4()})

    def unavailable() -> int:
        raise RuntimeError("database unavailable")

    store.database_size_bytes = unavailable  # type: ignore[method-assign]
    loader = DatabaseLoader(
        cast(Any, store),
        tmp_path,
        worker_id="loader-limits",
        disk_reserve_bytes=0,
        artifact_expansion_factor=1,
        temp_file_limit_kib=64 * 1024,
        database_capacity_bytes=128 * 1024 * 1024 * 1024,
        disk_free_bytes=lambda _: 10**12,
    )

    with pytest.raises(LoaderResourceLimitError) as captured:
        loader._preflight_materialisation_capacity(1)

    assert captured.value.code == "loader_database_capacity_unavailable"
    assert captured.value.retryable is True


def test_temp_file_limit_failure_is_safe_and_does_not_expose_database_text() -> None:
    class TempLimitExceededError(RuntimeError):
        sqlstate = "53400"

    error = _safe_loader_error(
        TempLimitExceededError(
            "temporary file size exceeds temp_file_limit at /private/postgresql/base/pgsql_tmp"
        )
    )

    assert error == {
        "code": "loader_temp_file_limit_exceeded",
        "category": "resource_limit",
        "message": "Import exceeded the loader transaction temporary-file limit",
        "retryable": False,
    }
