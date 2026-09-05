"""Durable sales importer: bounded memory, full validation, invisible replayable batches."""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import tempfile
import threading
import time
from collections.abc import Mapping
from typing import Any

import httpx

from propertyscope_market_intelligence.clients import DependencyUnavailableError
from propertyscope_market_intelligence.domain import PublicationRequest, SaleRecordV3

INTERNAL = "/internal/market-intelligence/v1/sales-imports"
MAX_RECORD_BYTES = 1024 * 1024
BATCH_BYTES = 1024 * 1024
LOGGER = logging.getLogger(__name__)


def public_import(operation: Mapping[str, Any]) -> dict[str, Any]:
    publication = operation["publication"]
    status = operation["status"]
    result = {
        "consumer_operation_id": operation["id"],
        "status": status,
        "release_id": publication["release_id"],
        "dataset_id": publication["dataset_id"],
        "target_feature": "feature-2",
        "schema_version": publication["schema_version"],
        "content_sha256": publication["content_sha256"],
        "record_count": publication["record_count"],
    }
    if status in {"accepted", "rejected", "failed"}:
        count = publication["record_count"] if status == "accepted" else operation["rows_staged"]
        result.update(
            rows_received=count,
            rows_accepted=count if status == "accepted" else 0,
            rows_rejected=0 if status == "accepted" else count,
            error=operation.get("error"),
        )
    return result


class SalesImportWorker:
    def __init__(self, store: Any, feature1: Any) -> None:
        self.store = store
        self.feature1 = feature1
        self.stopped = threading.Event()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        response = self.store.request(method, path, **kwargs)
        response.raise_for_status()
        return dict(response.json())

    def run_once(self) -> bool:
        operation = self._request("POST", f"{INTERNAL}/claim").get("operation")
        if operation is None:
            return False
        path = f"{INTERNAL}/{operation['id']}"
        lease = {"lease_token": operation["lease_token"]}
        error = None
        try:
            self._import(operation, path, lease)
        except (gzip.BadGzipFile, EOFError):
            error = {
                "code": "invalid_sales_artifact",
                "message": "Sales artifact is not complete gzip data",
                "retryable": False,
            }
        except (DependencyUnavailableError, httpx.TransportError, OSError) as exc:
            LOGGER.warning("Sales import interrupted: %s", type(exc).__name__)
            error = {
                "code": "sales_import_unavailable",
                "message": "Import transport or storage is temporarily unavailable",
                "retryable": True,
            }
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 409:
                return True  # A replacement worker owns this lease; do not change its state.
            error = {
                "code": "sales_import_store_error",
                "message": "Database rejected the import batch",
                "retryable": exc.response.status_code >= 500,
            }
        except ValueError as exc:
            error = {
                "code": "invalid_sales_artifact",
                "message": str(exc)[:500],
                "retryable": False,
            }
        self._request("POST", f"{path}/finish", json={**lease, "error": error})
        return True

    def _import(self, operation: Mapping[str, Any], path: str, lease: dict[str, Any]) -> None:
        publication = PublicationRequest.model_validate(operation["publication"])
        digest = hashlib.sha256()
        received = 0
        heartbeat_at = time.monotonic()
        # Temporary disk holds compressed bytes only; no dataset-sized memory buffer or SQL txn.
        with tempfile.TemporaryFile() as artifact:
            for chunk in self.feature1.iter_artifact(publication.artifact_path):
                received += len(chunk)
                declared_bytes = publication.manifest.get("byte_count")
                if declared_bytes is not None and received > declared_bytes:
                    raise ValueError("artifact exceeds its declared byte count")
                artifact.write(chunk)
                digest.update(chunk)
                if time.monotonic() - heartbeat_at >= 10:
                    self._request("POST", f"{path}/heartbeat", json=lease)
                    heartbeat_at = time.monotonic()
            if digest.hexdigest() != publication.content_sha256:
                raise ValueError("sales artifact checksum does not match")
            if publication.manifest.get("byte_count", received) != received:
                raise ValueError("sales artifact byte count does not match")
            artifact.seek(0)
            self._request("POST", f"{path}/heartbeat", json=lease)
            batch: list[dict[str, Any]] = []
            batch_bytes = 0
            count = 0
            synthetic = "synthetic" in str(publication.manifest.get("source", "")).lower()
            with gzip.GzipFile(fileobj=artifact) as expanded:
                while line := expanded.readline(MAX_RECORD_BYTES + 1):
                    count += 1
                    if len(line) > MAX_RECORD_BYTES:
                        raise ValueError("sales record exceeds the per-record memory budget")
                    if count > publication.record_count:
                        raise ValueError("sales artifact exceeds the declared record count")
                    record = SaleRecordV3.model_validate_json(line)
                    if record.provenance.release_id != publication.release_id:
                        raise ValueError(f"sales record {count} has the wrong release_id")
                    if str(record.provenance.candidate_generation_id) != publication.manifest.get(
                        "candidate_generation_id", str(publication.release_id)
                    ):
                        raise ValueError(f"sales record {count} has the wrong generation")
                    normalized = record.normalized(synthetic=synthetic)
                    size = len(json.dumps(normalized, ensure_ascii=True))
                    if batch and (len(batch) >= 1000 or batch_bytes + size > BATCH_BYTES):
                        self._request(
                            "POST",
                            f"{path}/batches",
                            json={
                                **lease,
                                "start": count - len(batch),
                                "records": batch,
                            },
                        )
                        batch, batch_bytes = [], 0
                    batch.append(normalized)
                    batch_bytes += size
            if count != publication.record_count:
                raise ValueError("sales artifact record count does not match")
            if batch:
                self._request(
                    "POST",
                    f"{path}/batches",
                    json={
                        **lease,
                        "start": count - len(batch) + 1,
                        "records": batch,
                    },
                )

    def run(self) -> None:
        while not self.stopped.is_set():
            try:
                if self.run_once():
                    continue
            except (DependencyUnavailableError, httpx.HTTPError, ValueError):
                LOGGER.exception("Sales import reconciliation will retry after its durable lease")
            self.stopped.wait(2)

    def start(self) -> None:
        threading.Thread(target=self.run, name="sales-import-worker", daemon=True).start()
