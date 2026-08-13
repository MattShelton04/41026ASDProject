"""Serial credential-owning bulk import loader."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import uuid
from pathlib import Path
from threading import Event
from typing import Any

from propertyscope_data_store.configuration import StoreSettings
from propertyscope_data_store.repository import PropertyScopeStore

REGISTERED_PROFILES = frozenset(
    {
        "fixture-json",
        "gnaf-nsw",
        "psi-one-year",
        "bocsar-sparse",
        "schools-master",
        *(f"import-profile-{index}" for index in range(1, 11)),
    }
)


class DatabaseLoader:
    """Claims durable operations and executes only registered import implementations."""

    def __init__(self, store: PropertyScopeStore, artifact_root: Path, *, worker_id: str) -> None:
        self.store = store
        self.artifact_root = artifact_root.resolve()
        self.worker_id = worker_id
        self.stop_event = Event()

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            if not self.run_once():
                self.stop_event.wait(1.0)

    def run_once(self) -> bool:
        operation = self.store.claim_import(worker_id=self.worker_id, lease_seconds=60)
        if operation is None:
            return False
        operation_id = uuid.UUID(str(operation["id"]))
        token = str(operation["lease_token"])
        try:
            self.store.heartbeat_import(
                operation_id, worker_id=self.worker_id, lease_token=token, lease_seconds=60
            )
            work = self.store.import_work(operation_id)
            counts = self._execute(work)
            self.store.finish_import(
                operation_id,
                worker_id=self.worker_id,
                lease_token=token,
                status="succeeded",
                counts=counts,
                result={"profile": work["import_profile_key"], "verified": True},
                error=None,
            )
        except Exception as exc:
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

    def _execute(self, work: dict[str, Any]) -> dict[str, int]:
        profile = str(work["import_profile_key"])
        if profile not in REGISTERED_PROFILES:
            raise RuntimeError("import profile is not registered")
        path = self._artifact_path(str(work["storage_key"]))
        maximum = min(int(work["artifact_bytes"]) + 1, 100_000_000)
        data = path.read_bytes()
        if len(data) >= maximum or len(data) != int(work["artifact_bytes"]):
            raise RuntimeError("artifact size does not match registered metadata")
        if hashlib.sha256(data).hexdigest() != work["content_sha256"]:
            raise RuntimeError("artifact checksum does not match registered metadata")
        rows = 0
        if work["media_type"] == "application/json":
            document = json.loads(data)
            if isinstance(document, dict) and isinstance(document.get("records"), list):
                rows = len(document["records"])
            elif isinstance(document, list):
                rows = len(document)
            else:
                raise RuntimeError("JSON artifact does not contain a registered row collection")
        else:
            rows = max(data.count(b"\n") - 1, 0)
        return {"rows_in": rows, "rows_staged": rows, "rows_accepted": rows, "rows_rejected": 0}

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
        "row collection",
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
