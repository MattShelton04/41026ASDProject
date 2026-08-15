"""Serial credential-owning bulk import loader."""

from __future__ import annotations

import hashlib
import logging
import os
import signal
import uuid
from pathlib import Path
from threading import Event
from typing import Any

from propertyscope_data_store.configuration import StoreSettings
from propertyscope_data_store.import_profiles import (
    REGISTERED_PROFILES,
    iter_ndjson_import,
    prepare_import,
)
from propertyscope_data_store.repository import PropertyScopeStore

logger = logging.getLogger(__name__)


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
            logger.exception("Registered import %s failed", operation_id)
            self.store.finish_import(
                operation_id,
                worker_id=self.worker_id,
                lease_token=token,
                status="failed",
                counts={"rows_in": 0, "rows_staged": 0, "rows_accepted": 0, "rows_rejected": 0},
                result=None,
                error={"code": "stage_parse_failed", "message": _safe_loader_message(exc)},
            )
        return True

    def stop(self) -> None:
        self.stop_event.set()

    def _execute(self, work: dict[str, Any]) -> tuple[dict[str, int], dict[str, Any]]:
        profile = str(work["import_profile_key"])
        if profile not in REGISTERED_PROFILES:
            raise RuntimeError("import profile is not registered")
        path = self._artifact_path(str(work["storage_key"]))
        if path.stat().st_size != int(work["artifact_bytes"]):
            raise RuntimeError("artifact size does not match registered metadata")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != work["content_sha256"]:
            raise RuntimeError("artifact checksum does not match registered metadata")
        if work["media_type"] == "application/x-ndjson":
            with path.open("rb") as stream:
                rows = iter_ndjson_import(stream, profile=profile)
                imported = self.store.execute_stream_import_profile(
                    work, profile=profile, rows=rows
                )
        elif work["media_type"] == "application/json":
            prepared = prepare_import(path.read_bytes(), profile=profile)
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

    def _artifact_path(self, storage_key: str) -> Path:
        if not storage_key.startswith("sha256/") or ".." in Path(storage_key).parts:
            raise RuntimeError("artifact storage key is invalid")
        path = (self.artifact_root / storage_key).resolve()
        if self.artifact_root not in path.parents or not path.is_file():
            raise RuntimeError("artifact is unavailable inside the loader boundary")
        return path


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
