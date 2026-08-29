"""Serial credential-owning bulk import loader."""

from __future__ import annotations

import hashlib
import logging
import os
import signal
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from threading import Event, Thread
from typing import Any

from propertyscope_data_store.configuration import StoreSettings
from propertyscope_data_store.import_profiles import (
    REGISTERED_PROFILES,
    iter_ndjson_import,
    prepare_import,
)
from propertyscope_data_store.repository import PropertyScopeStore

logger = logging.getLogger(__name__)
ACTIVATION_LEASE_SECONDS = 120
ACTIVATION_HEARTBEAT_SECONDS = 30


class ImportCancelledError(RuntimeError):
    """The owning ingestion run was cancelled while the loader held the operation."""


class DatabaseLoader:
    """Claims durable operations and executes only registered import implementations."""

    def __init__(self, store: PropertyScopeStore, artifact_root: Path, *, worker_id: str) -> None:
        self.store = store
        self.artifact_root = artifact_root.resolve()
        self.worker_id = worker_id
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
        operation = self.store.claim_import(worker_id=self.worker_id, lease_seconds=86_400)
        if operation is None:
            return False
        operation_id = uuid.UUID(str(operation["id"]))
        token = str(operation["lease_token"])
        try:
            self.store.heartbeat_import(
                operation_id, worker_id=self.worker_id, lease_token=token, lease_seconds=86_400
            )
            work = self.store.import_work(operation_id)
            counts, result = self._execute(work)
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
                    else {"code": "stage_parse_failed", "message": _safe_loader_message(exc)}
                ),
            )
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
            self.store.finish_release_activation(
                operation_id,
                worker_id=self.worker_id,
                lease_token=token,
                status="succeeded",
                error=None,
            )
        except Exception:
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
                            else "activation_materialization_failed"
                        ),
                        "message": (
                            "Publication will resume after the database loader restarts"
                            if interrupted
                            else "Publication activation failed before the live pointer changed"
                        ),
                        "retryable": interrupted,
                    },
                )
            except Exception:
                # A lost database connection leaves the leased operation recoverable after expiry.
                logger.exception("Publication activation outcome could not be persisted")

    def stop(self) -> None:
        self.stop_event.set()

    def _execute(self, work: dict[str, Any]) -> tuple[dict[str, int], dict[str, Any]]:
        profile = str(work["import_profile_key"])
        if profile not in REGISTERED_PROFILES:
            raise RuntimeError("import profile is not registered")
        path = self._artifact_path(str(work["storage_key"]))
        if path.stat().st_size != int(work["artifact_bytes"]):
            raise RuntimeError("artifact size does not match registered metadata")
        last_cancel_check = 0.0

        def raise_if_cancelled(*, force: bool = False) -> None:
            nonlocal last_cancel_check
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
            phase="verifying and copying canonical stream",
            rows_processed=0,
            bytes_processed=0,
            total_bytes=total_bytes,
        )
        raise_if_cancelled(force=True)
        if work["media_type"] == "application/x-ndjson":
            with path.open("rb") as stream:
                verified = _VerifiedLineStream(
                    stream,
                    expected_sha256=str(work["content_sha256"]),
                    expected_bytes=total_bytes,
                    progress=lambda rows, bytes_: self._update_import_progress(
                        operation_id,
                        phase="verifying and copying canonical stream",
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
                    phase_callback=lambda phase, count: self._update_import_progress(
                        operation_id,
                        phase=phase,
                        rows_processed=count,
                        bytes_processed=verified.bytes_processed,
                        total_bytes=total_bytes,
                    ),
                )
        elif work["media_type"] == "application/json":
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != work["content_sha256"]:
                raise RuntimeError("artifact checksum does not match registered metadata")
            self._update_import_progress(
                operation_id,
                phase="verified canonical document",
                rows_processed=0,
                bytes_processed=len(data),
                total_bytes=total_bytes,
            )
            prepared = prepare_import(data, profile=profile)
            raise_if_cancelled(force=True)
            imported = self.store.execute_import_profile(work, prepared)
        else:
            raise RuntimeError("registered import requires canonical JSON or NDJSON")
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

    def _update_import_progress(self, operation_id: uuid.UUID, **values: Any) -> None:
        reporter = getattr(self.store, "update_import_progress", None)
        if reporter is not None:
            reporter(operation_id, **values)

    def _artifact_path(self, storage_key: str) -> Path:
        if not storage_key.startswith("sha256/") or ".." in Path(storage_key).parts:
            raise RuntimeError("artifact storage key is invalid")
        path = (self.artifact_root / storage_key).resolve()
        if self.artifact_root not in path.parents or not path.is_file():
            raise RuntimeError("artifact is unavailable inside the loader boundary")
        return path


def _raise_between_rows(
    rows: Iterable[dict[str, Any]], raise_if_cancelled: Callable[[], None]
) -> Iterable[dict[str, Any]]:
    for row in rows:
        raise_if_cancelled()
        yield row


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


def _safe_loader_message(exc: Exception) -> str:
    known = (
        "not registered",
        "size does not match",
        "checksum does not match",
        "canonical import",
        "unavailable",
    )
    return (
        str(exc) if any(fragment in str(exc) for fragment in known) else "Registered import failed"
    )


def main() -> None:
    settings = StoreSettings.from_environment()
    store = PropertyScopeStore(settings.database_url)
    loader = DatabaseLoader(
        store,
        settings.artifact_root,
        worker_id=os.environ.get("PROPERTYSCOPE_LOADER_ID", f"loader-{uuid.uuid4().hex[:8]}"),
    )
    signal.signal(signal.SIGTERM, lambda *_: loader.stop())
    signal.signal(signal.SIGINT, lambda *_: loader.stop())
    loader.run_forever()


if __name__ == "__main__":
    main()
