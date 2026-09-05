"""Serial credential-owning bulk import loader."""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import signal
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from threading import Event, Thread
from typing import Any

from propertyscope_data_store.configuration import StoreSettings
from propertyscope_data_store.import_profiles import (
    CANONICAL_PARQUET_MEDIA_TYPE,
    IMPORT_PHASE_LABELS,
    REGISTERED_PROFILES,
    ImportProfileError,
    iter_ndjson_import,
    iter_parquet_import,
    prepare_import,
)
from propertyscope_data_store.repository import PropertyScopeStore
from propertyscope_data_store.runtime_registry import load_runtime_registry

logger = logging.getLogger(__name__)
ACTIVATION_LEASE_SECONDS = 120
ACTIVATION_HEARTBEAT_SECONDS = 30
IMPORT_LEASE_SECONDS = 120
IMPORT_HEARTBEAT_SECONDS = 30
ARTIFACT_HASH_CHUNK_BYTES = 1024 * 1024
ACTIVATION_PHASE_LABELS = {
    "artifact_verification": "Verifying release artifact",
    "materialisation": "Materialising reviewed release",
    "commit_pointer": "Committing accepted-generation pointer",
}
GIBIBYTE = 1024 * 1024 * 1024
# Floors conservatively project the largest measured 1m relation and WAL growth to the
# official-source record counts with the documented 2.5 safety factor, rounded upward.
# PSI includes accepted G-NAF identity anchors and their provenance (ADR-038).
SOURCE_SCALE_DATABASE_GROWTH_FLOORS_BYTES = {
    "psi-sales": 24 * GIBIBYTE,
    "bocsar-sparse": 8 * GIBIBYTE,
}
SOURCE_SCALE_WAL_FLOORS_BYTES = {
    "psi-sales": 64 * GIBIBYTE,
    "bocsar-sparse": 20 * GIBIBYTE,
}


class ImportCancelledError(RuntimeError):
    """The owning ingestion run was cancelled while the loader held the operation."""


class ReleaseArtifactVerificationError(RuntimeError):
    """The release export no longer matches its durable artifact-ledger evidence."""


class LoaderResourceLimitError(RuntimeError):
    """A bounded loader resource preflight failed before destination materialisation."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        details: dict[str, int],
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details


class DatabaseLoader:
    """Claims durable operations and executes only registered import implementations."""

    def __init__(
        self,
        store: PropertyScopeStore,
        artifact_root: Path,
        *,
        worker_id: str,
        disk_reserve_bytes: int = 4 * 1024 * 1024 * 1024,
        artifact_expansion_factor: int = 3,
        temp_file_limit_kib: int = 16 * 1024 * 1024,
        database_capacity_bytes: int | None = None,
        disk_free_bytes: Callable[[Path], int] | None = None,
    ) -> None:
        if disk_reserve_bytes < 0:
            raise ValueError("loader disk reserve must not be negative")
        if not 1 <= artifact_expansion_factor <= 16:
            raise ValueError("loader artifact expansion factor must be between 1 and 16")
        if not 64 * 1024 <= temp_file_limit_kib <= 64 * 1024 * 1024:
            raise ValueError("loader temp-file limit is outside the supported bound")
        if database_capacity_bytes is not None and database_capacity_bytes <= 0:
            raise ValueError("loader database capacity must be positive when configured")
        self.store = store
        self.artifact_root = artifact_root.resolve()
        self.worker_id = worker_id
        self.disk_reserve_bytes = disk_reserve_bytes
        self.artifact_expansion_factor = artifact_expansion_factor
        self.temp_file_limit_kib = temp_file_limit_kib
        self.database_capacity_bytes = database_capacity_bytes
        self._disk_free_bytes = disk_free_bytes or (lambda path: shutil.disk_usage(path).free)
        self.stop_event = Event()

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                worked = self.run_once()
            except Exception:
                logger.exception("Import claim failed; polling will resume")
                worked = False
            if not worked:
                self.stop_event.wait(1.0)

    def run_once(self) -> bool:
        activation = self.store.claim_release_activation(
            worker_id=self.worker_id, lease_seconds=ACTIVATION_LEASE_SECONDS
        )
        if activation is not None:
            self._activate(activation)
            return True
        operation = self.store.claim_import(
            worker_id=self.worker_id,
            lease_seconds=IMPORT_LEASE_SECONDS,
        )
        if operation is None:
            return False
        operation_id = uuid.UUID(str(operation["id"]))
        token = str(operation["lease_token"])
        heartbeat_stop = Event()
        heartbeat_failed = Event()
        heartbeater: Thread | None = None

        def heartbeat() -> None:
            while not heartbeat_stop.wait(IMPORT_HEARTBEAT_SECONDS):
                if self.stop_event.is_set():
                    return
                try:
                    self.store.heartbeat_import(
                        operation_id,
                        worker_id=self.worker_id,
                        lease_token=token,
                        lease_seconds=IMPORT_LEASE_SECONDS,
                    )
                except Exception:
                    logger.exception("Import lease heartbeat failed")
                    heartbeat_failed.set()
                    return

        try:
            if self.stop_event.is_set():
                return True
            self.store.heartbeat_import(
                operation_id,
                worker_id=self.worker_id,
                lease_token=token,
                lease_seconds=IMPORT_LEASE_SECONDS,
            )
            heartbeater = Thread(
                target=heartbeat,
                name=f"import-heartbeat-{operation_id}",
                daemon=True,
            )
            heartbeater.start()
            work = self.store.import_work(operation_id)
            counts, result = self._execute(work, lease_failed_event=heartbeat_failed)
            if heartbeat_failed.is_set():
                raise RuntimeError("import lease could not be renewed")
            self.store.finish_import(
                operation_id,
                worker_id=self.worker_id,
                lease_token=token,
                status="succeeded",
                counts=counts,
                result=result,
                error=None,
            )
        except Exception as exc:
            if self.stop_event.is_set() or heartbeat_failed.is_set():
                logger.error(
                    "Registered import %s stopped before completion; expiry recovery will resume",
                    operation_id,
                )
                return True
            cancelled = self.store.import_cancel_requested(operation_id)
            if cancelled:
                logger.info("Registered import %s cancelled by operator", operation_id)
            else:
                logger.exception("Registered import %s failed", operation_id)
            self.store.finish_import(
                operation_id,
                worker_id=self.worker_id,
                lease_token=token,
                status="cancelled" if cancelled else "failed",
                counts={"rows_in": 0, "rows_staged": 0, "rows_accepted": 0, "rows_rejected": 0},
                result=None,
                error=(
                    {"code": "operator_cancelled", "message": "Run cancelled by operator"}
                    if cancelled
                    else _safe_loader_error(exc)
                ),
            )
            recover = getattr(self.store, "recover_import_space", None)
            if recover is not None:
                try:
                    recover(operation_id)
                except Exception:
                    logger.exception(
                        "Bounded space recovery for import %s remains needed", operation_id
                    )
        finally:
            heartbeat_stop.set()
            if heartbeater is not None:
                heartbeater.join(timeout=2)
        return True

    def _activate(self, operation: dict[str, Any]) -> None:
        """Materialise a reviewed release off-request, then atomically switch its pointer."""
        operation_id = uuid.UUID(str(operation["id"]))
        token = str(operation["lease_token"])
        heartbeat_stop = Event()
        heartbeat_failed = Event()

        def heartbeat() -> None:
            while not heartbeat_stop.wait(ACTIVATION_HEARTBEAT_SECONDS):
                try:
                    self.store.heartbeat_release_activation(
                        operation_id,
                        worker_id=self.worker_id,
                        lease_token=token,
                        lease_seconds=ACTIVATION_LEASE_SECONDS,
                    )
                except Exception:
                    logger.exception("Publication activation heartbeat failed")
                    heartbeat_failed.set()
                    return

        try:
            self.store.heartbeat_release_activation(
                operation_id,
                worker_id=self.worker_id,
                lease_token=token,
                lease_seconds=ACTIVATION_LEASE_SECONDS,
            )
            heartbeater = Thread(
                target=heartbeat,
                name=f"activation-heartbeat-{operation_id}",
                daemon=True,
            )
            heartbeater.start()
            try:
                self._update_activation_progress(
                    operation_id, lease_token=token, phase_key="artifact_verification"
                )
                artifact = self.store.release_artifact(
                    uuid.UUID(str(operation["dataset_release_id"]))
                )
                self._verify_release_export(artifact, lease_failed_event=heartbeat_failed)
                self._update_activation_progress(
                    operation_id, lease_token=token, phase_key="materialisation"
                )
                self.store.materialize_release_activation(
                    operation_id,
                    worker_id=self.worker_id,
                    lease_token=token,
                    stop_event=self.stop_event,
                    lease_failed_event=heartbeat_failed,
                )
            finally:
                heartbeat_stop.set()
                heartbeater.join(timeout=2)
            if heartbeat_failed.is_set():
                raise RuntimeError("publication activation lease could not be renewed")
            if self.stop_event.is_set():
                raise InterruptedError("database loader stopped during publication activation")
            self._update_activation_progress(
                operation_id, lease_token=token, phase_key="commit_pointer"
            )
            self.store.finish_release_activation(
                operation_id,
                worker_id=self.worker_id,
                lease_token=token,
                status="succeeded",
                error=None,
            )
        except Exception as exc:
            interrupted = self.stop_event.is_set()
            if interrupted:
                logger.info(
                    "Publication activation %s interrupted by loader shutdown", operation_id
                )
            else:
                logger.exception("Publication activation %s failed", operation_id)
            try:
                self.store.finish_release_activation(
                    operation_id,
                    worker_id=self.worker_id,
                    lease_token=token,
                    status="interrupted" if interrupted else "failed",
                    error={
                        "code": (
                            "loader_shutdown"
                            if interrupted
                            else (
                                "release_artifact_verification_failed"
                                if isinstance(exc, ReleaseArtifactVerificationError)
                                else "activation_materialization_failed"
                            )
                        ),
                        "message": (
                            "Publication will resume after the database loader restarts"
                            if interrupted
                            else (
                                "Release export artifact is missing or does not match its "
                                "durable metadata; the live pointer was not changed"
                                if isinstance(exc, ReleaseArtifactVerificationError)
                                else "Publication activation failed before the live pointer changed"
                            )
                        ),
                        "retryable": interrupted,
                    },
                )
            except Exception:
                # A lost database connection leaves the leased operation recoverable after expiry.
                logger.exception("Publication activation outcome could not be persisted")

    def _update_activation_progress(
        self, operation_id: uuid.UUID, *, lease_token: str, phase_key: str
    ) -> None:
        reporter = getattr(self.store, "update_release_activation_progress", None)
        if reporter is not None:
            reporter(
                operation_id,
                worker_id=self.worker_id,
                lease_token=lease_token,
                phase_key=phase_key,
                phase=ACTIVATION_PHASE_LABELS[phase_key],
            )

    def stop(self) -> None:
        self.stop_event.set()

    def _execute(
        self,
        work: dict[str, Any],
        *,
        lease_failed_event: Event | None = None,
    ) -> tuple[dict[str, int], dict[str, Any]]:
        profile = str(work["import_profile_key"])
        if profile not in REGISTERED_PROFILES:
            raise RuntimeError("import profile is not registered")
        path = self._artifact_path(str(work["storage_key"]))
        if path.stat().st_size != int(work["artifact_bytes"]):
            raise RuntimeError("artifact size does not match registered metadata")
        self._preflight_materialisation_capacity(int(work["artifact_bytes"]), profile=profile)
        last_cancel_check = 0.0

        def raise_if_cancelled(*, force: bool = False) -> None:
            nonlocal last_cancel_check
            if self.stop_event.is_set():
                raise InterruptedError("database loader stopped during import")
            if lease_failed_event is not None and lease_failed_event.is_set():
                raise RuntimeError("import lease could not be renewed")
            now = time.monotonic()
            if not force and now - last_cancel_check < 0.5:
                return
            last_cancel_check = now
            if self.store.import_cancel_requested(uuid.UUID(str(work["id"]))):
                raise ImportCancelledError("Run cancelled by operator")

        operation_id = uuid.UUID(str(work["id"]))
        total_bytes = int(work["artifact_bytes"])
        self._update_import_progress(
            operation_id,
            phase_key="artifact_verification",
            rows_processed=0,
            bytes_processed=0,
            total_bytes=total_bytes,
        )
        raise_if_cancelled(force=True)
        if work["media_type"] == CANONICAL_PARQUET_MEDIA_TYPE:
            _verify_registered_file(
                path,
                expected_sha256=str(work["content_sha256"]),
                expected_bytes=total_bytes,
                progress=lambda bytes_: self._update_import_progress(
                    operation_id,
                    phase_key="artifact_verification",
                    rows_processed=0,
                    bytes_processed=bytes_,
                    total_bytes=total_bytes,
                ),
                raise_if_cancelled=raise_if_cancelled,
            )
            self._update_import_progress(
                operation_id,
                phase_key="typed_staging",
                rows_processed=0,
                bytes_processed=0,
                total_bytes=total_bytes,
            )
            rows = iter_parquet_import(path, profile=profile)
            cancellable_rows = _raise_between_rows(
                rows,
                raise_if_cancelled,
                progress=lambda count: self._update_import_progress(
                    operation_id,
                    phase_key="typed_staging",
                    rows_processed=count,
                    bytes_processed=0,
                    total_bytes=None,
                ),
            )
            imported = self.store.execute_stream_import_profile(
                work,
                profile=profile,
                rows=cancellable_rows,
                verify_complete=lambda: None,
                phase_callback=lambda phase_key, count: self._update_import_progress(
                    operation_id,
                    phase_key=phase_key,
                    rows_processed=count,
                    bytes_processed=0,
                    total_rows=count if phase_key == "verification" else None,
                    total_bytes=None,
                ),
                lease_failed_event=lease_failed_event,
                stop_event=self.stop_event,
            )
        elif work["media_type"] == "application/x-ndjson":
            self._update_import_progress(
                operation_id,
                phase_key="typed_staging",
                rows_processed=0,
                bytes_processed=0,
                total_bytes=total_bytes,
            )
            with path.open("rb") as stream:
                verified = _VerifiedLineStream(
                    stream,
                    expected_sha256=str(work["content_sha256"]),
                    expected_bytes=total_bytes,
                    progress=lambda rows, bytes_: self._update_import_progress(
                        operation_id,
                        phase_key="typed_staging",
                        rows_processed=rows,
                        bytes_processed=bytes_,
                        total_bytes=total_bytes,
                    ),
                    raise_if_cancelled=raise_if_cancelled,
                )
                rows = iter_ndjson_import(verified, profile=profile)
                cancellable_rows = _raise_between_rows(rows, raise_if_cancelled)
                imported = self.store.execute_stream_import_profile(
                    work,
                    profile=profile,
                    rows=cancellable_rows,
                    verify_complete=verified.verify_complete,
                    phase_callback=lambda phase_key, count: self._update_import_progress(
                        operation_id,
                        phase_key=phase_key,
                        # COPY completion does not measure the following set-based SQL insert.
                        # Retain its durable row checkpoint, but clear the gauge rather than
                        # displaying 100% for that long phase.
                        rows_processed=count,
                        bytes_processed=0,
                        total_rows=count if phase_key == "verification" else None,
                        total_bytes=None,
                    ),
                    lease_failed_event=lease_failed_event,
                    stop_event=self.stop_event,
                )
        elif work["media_type"] == "application/json":
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != work["content_sha256"]:
                raise RuntimeError("artifact checksum does not match registered metadata")
            self._update_import_progress(
                operation_id,
                phase_key="artifact_verification",
                rows_processed=0,
                bytes_processed=len(data),
                total_bytes=total_bytes,
            )
            self._update_import_progress(
                operation_id,
                phase_key="typed_staging",
                rows_processed=0,
                bytes_processed=0,
            )
            prepared = prepare_import(data, profile=profile)
            raise_if_cancelled(force=True)
            imported = self.store.execute_import_profile(
                work,
                prepared,
                phase_callback=lambda phase_key, count: self._update_import_progress(
                    operation_id,
                    phase_key=phase_key,
                    rows_processed=count,
                    bytes_processed=0,
                    total_rows=count if phase_key == "verification" else None,
                ),
                lease_failed_event=lease_failed_event,
                stop_event=self.stop_event,
            )
        else:
            raise RuntimeError(
                "registered import requires canonical JSON, NDJSON, or BOCSAR Parquet"
            )
        counts = {
            "rows_in": imported.rows_in,
            "rows_staged": imported.rows_staged,
            "rows_accepted": imported.rows_accepted,
            "rows_rejected": imported.rows_rejected,
        }
        return counts, {
            "profile": profile,
            "verified": True,
            "staging_method": "postgresql-copy",
            "candidate_generation": str(work["candidate_release_id"]),
            "quality_checks": imported.quality_checks,
            "accepted_generation_unchanged": True,
        }

    def _preflight_materialisation_capacity(
        self, artifact_bytes: int, *, profile: str = ""
    ) -> None:
        """Fail before COPY unless declared and physical database headroom are sufficient."""
        temporary_file_allowance_bytes = self.temp_file_limit_kib * 1024
        artifact_growth_allowance_bytes = artifact_bytes * self.artifact_expansion_factor
        database_growth_floor_bytes = SOURCE_SCALE_DATABASE_GROWTH_FLOORS_BYTES.get(profile, 0)
        database_growth_allowance_bytes = max(
            artifact_growth_allowance_bytes, database_growth_floor_bytes
        )
        wal_allowance_bytes = SOURCE_SCALE_WAL_FLOORS_BYTES.get(profile, 0)
        required_database_headroom_bytes = (
            database_growth_allowance_bytes
            + temporary_file_allowance_bytes
            + wal_allowance_bytes
            + self.disk_reserve_bytes
        )
        try:
            artifact_available_free_bytes = self._disk_free_bytes(self.artifact_root)
        except OSError as exc:
            raise LoaderResourceLimitError(
                "loader_artifact_capacity_unavailable",
                "Artifact filesystem capacity could not be observed before materialisation",
                retryable=True,
                details={
                    "artifact_bytes": artifact_bytes,
                    "artifact_expansion_factor": self.artifact_expansion_factor,
                    "artifact_growth_allowance_bytes": artifact_growth_allowance_bytes,
                    "database_growth_floor_bytes": database_growth_floor_bytes,
                    "database_growth_allowance_bytes": database_growth_allowance_bytes,
                    "temporary_file_allowance_bytes": temporary_file_allowance_bytes,
                    "wal_allowance_bytes": wal_allowance_bytes,
                    "reserve_bytes": self.disk_reserve_bytes,
                },
            ) from exc
        if self.database_capacity_bytes is None:
            raise LoaderResourceLimitError(
                "loader_database_capacity_unconfigured",
                "PostgreSQL deployment capacity is not configured for safe materialisation",
                retryable=True,
                details={
                    "artifact_bytes": artifact_bytes,
                    "artifact_available_free_bytes": max(0, artifact_available_free_bytes),
                    "required_database_headroom_bytes": required_database_headroom_bytes,
                    "artifact_expansion_factor": self.artifact_expansion_factor,
                    "artifact_growth_allowance_bytes": artifact_growth_allowance_bytes,
                    "database_growth_floor_bytes": database_growth_floor_bytes,
                    "database_growth_allowance_bytes": database_growth_allowance_bytes,
                    "temporary_file_allowance_bytes": temporary_file_allowance_bytes,
                    "wal_allowance_bytes": wal_allowance_bytes,
                    "reserve_bytes": self.disk_reserve_bytes,
                },
            )
        try:
            database_size_bytes = self.store.database_size_bytes()
        except Exception as exc:
            raise LoaderResourceLimitError(
                "loader_database_capacity_unavailable",
                "PostgreSQL database capacity could not be verified before materialisation",
                retryable=True,
                details={
                    "artifact_bytes": artifact_bytes,
                    "artifact_available_free_bytes": max(0, artifact_available_free_bytes),
                    "database_capacity_bytes": self.database_capacity_bytes,
                    "required_database_headroom_bytes": required_database_headroom_bytes,
                    "artifact_expansion_factor": self.artifact_expansion_factor,
                    "artifact_growth_allowance_bytes": artifact_growth_allowance_bytes,
                    "database_growth_floor_bytes": database_growth_floor_bytes,
                    "database_growth_allowance_bytes": database_growth_allowance_bytes,
                    "temporary_file_allowance_bytes": temporary_file_allowance_bytes,
                    "wal_allowance_bytes": wal_allowance_bytes,
                    "reserve_bytes": self.disk_reserve_bytes,
                },
            ) from exc
        try:
            database_filesystem_available_bytes = self.store.database_filesystem_available_bytes()
        except Exception as exc:
            raise LoaderResourceLimitError(
                "loader_database_filesystem_capacity_unavailable",
                "PostgreSQL data/WAL filesystem capacity could not be observed "
                "before materialisation",
                retryable=True,
                details={
                    "artifact_bytes": artifact_bytes,
                    "artifact_available_free_bytes": max(0, artifact_available_free_bytes),
                    "database_size_bytes": database_size_bytes,
                    "database_capacity_bytes": self.database_capacity_bytes,
                    "required_database_headroom_bytes": required_database_headroom_bytes,
                    "artifact_expansion_factor": self.artifact_expansion_factor,
                    "artifact_growth_allowance_bytes": artifact_growth_allowance_bytes,
                    "database_growth_floor_bytes": database_growth_floor_bytes,
                    "database_growth_allowance_bytes": database_growth_allowance_bytes,
                    "temporary_file_allowance_bytes": temporary_file_allowance_bytes,
                    "wal_allowance_bytes": wal_allowance_bytes,
                    "reserve_bytes": self.disk_reserve_bytes,
                },
            ) from exc
        if database_filesystem_available_bytes < required_database_headroom_bytes:
            raise LoaderResourceLimitError(
                "insufficient_loader_database_filesystem_space",
                "Insufficient physical PostgreSQL data/WAL filesystem space for safe "
                "materialisation",
                retryable=True,
                details={
                    "artifact_bytes": artifact_bytes,
                    "artifact_available_free_bytes": max(0, artifact_available_free_bytes),
                    "database_size_bytes": database_size_bytes,
                    "database_capacity_bytes": self.database_capacity_bytes,
                    "database_filesystem_available_bytes": max(
                        0, database_filesystem_available_bytes
                    ),
                    "required_database_headroom_bytes": required_database_headroom_bytes,
                    "artifact_expansion_factor": self.artifact_expansion_factor,
                    "artifact_growth_allowance_bytes": artifact_growth_allowance_bytes,
                    "database_growth_floor_bytes": database_growth_floor_bytes,
                    "database_growth_allowance_bytes": database_growth_allowance_bytes,
                    "temporary_file_allowance_bytes": temporary_file_allowance_bytes,
                    "wal_allowance_bytes": wal_allowance_bytes,
                    "reserve_bytes": self.disk_reserve_bytes,
                },
            )
        projected_database_bytes = database_size_bytes + required_database_headroom_bytes
        if projected_database_bytes > self.database_capacity_bytes:
            raise LoaderResourceLimitError(
                "insufficient_loader_database_capacity",
                "Insufficient PostgreSQL deployment capacity for safe materialisation",
                retryable=True,
                details={
                    "artifact_bytes": artifact_bytes,
                    "artifact_available_free_bytes": max(0, artifact_available_free_bytes),
                    "database_size_bytes": database_size_bytes,
                    "database_capacity_bytes": self.database_capacity_bytes,
                    "database_filesystem_available_bytes": max(
                        0, database_filesystem_available_bytes
                    ),
                    "database_available_headroom_bytes": max(
                        0, self.database_capacity_bytes - database_size_bytes
                    ),
                    "required_database_headroom_bytes": required_database_headroom_bytes,
                    "projected_database_bytes": projected_database_bytes,
                    "artifact_expansion_factor": self.artifact_expansion_factor,
                    "artifact_growth_allowance_bytes": artifact_growth_allowance_bytes,
                    "database_growth_floor_bytes": database_growth_floor_bytes,
                    "database_growth_allowance_bytes": database_growth_allowance_bytes,
                    "temporary_file_allowance_bytes": temporary_file_allowance_bytes,
                    "wal_allowance_bytes": wal_allowance_bytes,
                    "reserve_bytes": self.disk_reserve_bytes,
                },
            )

    def _update_import_progress(self, operation_id: uuid.UUID, **values: Any) -> None:
        reporter = getattr(self.store, "update_import_progress", None)
        if reporter is not None:
            phase_key = str(values.pop("phase_key"))
            reporter(
                operation_id,
                phase_key=phase_key,
                phase=IMPORT_PHASE_LABELS[phase_key],
                **values,
            )

    def _verify_release_export(
        self,
        artifact: dict[str, Any],
        *,
        lease_failed_event: Event,
    ) -> None:
        """Stream-verify the loader-owned export before any activation materialisation."""
        if artifact.get("artifact_kind") != "release_export":
            raise ReleaseArtifactVerificationError("release artifact is not an export")
        try:
            expected_bytes = int(artifact["bytes"])
            expected_sha256 = str(artifact["content_sha256"])
            try:
                path = self._artifact_path(str(artifact["storage_key"]))
            except RuntimeError as exc:
                raise ReleaseArtifactVerificationError("release artifact is unavailable") from exc
            if path.stat().st_size != expected_bytes:
                raise ReleaseArtifactVerificationError(
                    "release artifact size does not match registered metadata"
                )
            digest = hashlib.sha256()
            bytes_read = 0
            with path.open("rb") as stream:
                while True:
                    if self.stop_event.is_set():
                        raise InterruptedError(
                            "database loader stopped during release artifact verification"
                        )
                    if lease_failed_event.is_set():
                        raise RuntimeError("publication activation lease could not be renewed")
                    chunk = stream.read(ARTIFACT_HASH_CHUNK_BYTES)
                    if not chunk:
                        break
                    digest.update(chunk)
                    bytes_read += len(chunk)
        except ReleaseArtifactVerificationError:
            raise
        except InterruptedError:
            raise
        except (KeyError, OSError, TypeError, ValueError) as exc:
            raise ReleaseArtifactVerificationError("release artifact is unavailable") from exc
        if bytes_read != expected_bytes:
            raise ReleaseArtifactVerificationError(
                "release artifact size does not match registered metadata"
            )
        if digest.hexdigest() != expected_sha256:
            raise ReleaseArtifactVerificationError(
                "release artifact checksum does not match registered metadata"
            )

    def _artifact_path(self, storage_key: str) -> Path:
        if not storage_key.startswith("sha256/") or ".." in Path(storage_key).parts:
            raise RuntimeError("artifact storage key is invalid")
        path = (self.artifact_root / storage_key).resolve()
        if self.artifact_root not in path.parents or not path.is_file():
            raise RuntimeError("artifact is unavailable inside the loader boundary")
        return path


def _raise_between_rows(
    rows: Iterable[dict[str, Any]],
    raise_if_cancelled: Callable[[], None],
    *,
    progress: Callable[[int], None] | None = None,
) -> Iterable[dict[str, Any]]:
    processed = 0
    reported = 0
    last_report = time.monotonic()
    for row in rows:
        raise_if_cancelled()
        yield row
        processed += 1
        if progress is not None and processed % 10_000 == 0:
            now = time.monotonic()
            if now - last_report >= 1:
                progress(processed)
                reported = processed
                last_report = now
    if progress is not None and processed != reported:
        progress(processed)


def _verify_registered_file(
    path: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    progress: Callable[[int], None],
    raise_if_cancelled: Callable[[], None],
) -> None:
    """Verify a seekable canonical artifact completely before database COPY begins."""
    if path.stat().st_size != expected_bytes:
        raise RuntimeError("artifact size does not match registered metadata")
    digest = hashlib.sha256()
    bytes_processed = 0
    last_report = time.monotonic()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(ARTIFACT_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
            bytes_processed += len(chunk)
            now = time.monotonic()
            if now - last_report >= 1.0:
                progress(bytes_processed)
                raise_if_cancelled()
                last_report = now
    progress(bytes_processed)
    raise_if_cancelled()
    if bytes_processed != expected_bytes:
        raise RuntimeError("artifact size does not match registered metadata")
    if digest.hexdigest() != expected_sha256:
        raise RuntimeError("artifact checksum does not match registered metadata")


class _VerifiedLineStream:
    """Hash one NDJSON file while the same bytes are parsed and copied."""

    def __init__(
        self,
        stream: Any,
        *,
        expected_sha256: str,
        expected_bytes: int,
        progress: Callable[[int, int], None],
        raise_if_cancelled: Callable[[], None],
    ) -> None:
        self._stream = stream
        self._expected_sha256 = expected_sha256
        self._expected_bytes = expected_bytes
        self._progress = progress
        self._raise_if_cancelled = raise_if_cancelled
        self._digest = hashlib.sha256()
        self._rows = 0
        self.bytes_processed = 0
        self._last_report = time.monotonic()

    def __iter__(self) -> Iterator[bytes]:
        for line in self._stream:
            self._digest.update(line)
            self.bytes_processed += len(line)
            if line.strip():
                self._rows += 1
            now = time.monotonic()
            if now - self._last_report >= 1.0:
                self._progress(self._rows, self.bytes_processed)
                self._raise_if_cancelled()
                self._last_report = now
            yield line
        self._progress(self._rows, self.bytes_processed)

    def verify_complete(self) -> None:
        self._raise_if_cancelled()
        if self.bytes_processed != self._expected_bytes:
            raise RuntimeError("artifact size does not match registered metadata")
        if self._digest.hexdigest() != self._expected_sha256:
            raise RuntimeError("artifact checksum does not match registered metadata")


def _safe_loader_error(exc: Exception) -> dict[str, object]:
    if isinstance(exc, LoaderResourceLimitError):
        return {
            "code": exc.code,
            "category": "resource_limit",
            "message": str(exc),
            "retryable": exc.retryable,
            "details": exc.details,
        }
    if getattr(exc, "sqlstate", None) == "53400" and "temp_file_limit" in str(exc):
        return {
            "code": "loader_temp_file_limit_exceeded",
            "category": "resource_limit",
            "message": "Import exceeded the loader transaction temporary-file limit",
            "retryable": False,
        }
    if isinstance(exc, ImportProfileError):
        return {
            "code": "canonical_record_invalid",
            "category": "data_validation",
            "message": f"Import stopped because {exc}.",
            "retryable": False,
        }
    known = (
        "not registered",
        "size does not match",
        "checksum does not match",
        "canonical import",
        "unavailable",
    )
    message = (
        str(exc) if any(fragment in str(exc) for fragment in known) else "Registered import failed"
    )
    return {"code": "stage_parse_failed", "message": message, "retryable": False}


def main() -> None:
    settings = StoreSettings.from_environment()
    store = PropertyScopeStore(
        settings.database_url,
        runtime_registry=load_runtime_registry(settings.runtime_profile_root),
        loader_temp_file_limit_kib=settings.loader_temp_file_limit_kib,
    )
    loader = DatabaseLoader(
        store,
        settings.artifact_root,
        worker_id=os.environ.get("PROPERTYSCOPE_LOADER_ID", f"loader-{uuid.uuid4().hex[:8]}"),
        disk_reserve_bytes=settings.loader_disk_reserve_bytes,
        artifact_expansion_factor=settings.loader_artifact_expansion_factor,
        temp_file_limit_kib=settings.loader_temp_file_limit_kib,
        database_capacity_bytes=settings.loader_database_capacity_bytes,
    )
    signal.signal(signal.SIGTERM, lambda *_: loader.stop())
    signal.signal(signal.SIGINT, lambda *_: loader.stop())
    loader.run_forever()


if __name__ == "__main__":
    main()
