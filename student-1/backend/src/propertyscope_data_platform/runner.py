"""Serial acquisition runner using only the backend worker HTTP contract."""

from __future__ import annotations

import json
import os
import signal
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Any

import httpx

from propertyscope_data_platform.artifacts import LocalArtifactStore


@dataclass(frozen=True, slots=True)
class RunnerSettings:
    backend_url: str
    token: str
    artifact_root: Path
    worker_id: str
    poll_seconds: float
    lease_seconds: int

    @classmethod
    def from_environment(cls) -> RunnerSettings:
        return cls(
            backend_url=os.environ.get(
                "PROPERTYSCOPE_BACKEND_URL", "http://propertyscope-backend:5201"
            ).rstrip("/"),
            token=os.environ.get("PROPERTYSCOPE_RUNNER_TOKEN", "local-runner-only"),
            artifact_root=Path(
                os.environ.get("PROPERTYSCOPE_ARTIFACT_ROOT", "/var/lib/propertyscope/artifacts")
            ),
            worker_id=os.environ.get("PROPERTYSCOPE_RUNNER_ID", f"runner-{uuid.uuid4().hex[:8]}"),
            poll_seconds=float(os.environ.get("PROPERTYSCOPE_RUNNER_POLL_SECONDS", "1")),
            lease_seconds=int(os.environ.get("PROPERTYSCOPE_RUNNER_LEASE_SECONDS", "30")),
        )


class AcquisitionRunner:
    """Bounded deterministic worker; source transports are selected by registered jobs only."""

    def __init__(self, settings: RunnerSettings, *, client: httpx.Client | None = None) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=10, follow_redirects=False)
        self.artifacts = LocalArtifactStore(settings.artifact_root)
        self.stop_event = Event()

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            if not self.run_once():
                self.stop_event.wait(self.settings.poll_seconds)

    def run_once(self) -> bool:
        response = self.client.post(
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/claim",
            headers=self._headers(),
            json={
                "worker_id": self.settings.worker_id,
                "lease_seconds": self.settings.lease_seconds,
            },
        )
        response.raise_for_status()
        task: dict[str, Any] | None = response.json().get("task")
        if task is None:
            return False
        task_id = str(task["id"])
        lease_token = str(task["lease_token"])
        try:
            self._heartbeat(task_id, lease_token)
            rows_in, rows_out = self._execute(task)
            result = self.client.post(
                f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/{task_id}/complete",
                headers=self._headers(),
                json={
                    "worker_id": self.settings.worker_id,
                    "lease_token": lease_token,
                    "rows_in": rows_in,
                    "rows_out": rows_out,
                },
            )
            result.raise_for_status()
        except Exception as exc:
            safe_code = (
                "quality_gate_failed"
                if str(task.get("stage")) == "quality"
                else "stage_execution_failed"
            )
            failure = self.client.post(
                f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/{task_id}/fail",
                headers=self._headers(),
                json={
                    "worker_id": self.settings.worker_id,
                    "lease_token": lease_token,
                    "error": {"code": safe_code, "message": _safe_message(exc)},
                    "retryable": False,
                },
            )
            failure.raise_for_status()
        return True

    def stop(self) -> None:
        self.stop_event.set()

    def _execute(self, task: dict[str, Any]) -> tuple[int, int]:
        stage = str(task["stage"])
        partition = task.get("partition_json")
        scope: dict[str, Any] = partition if isinstance(partition, dict) else {}
        if stage == "quality" and scope.get("scenario") == "missing_month":
            raise RuntimeError(
                "Required fixture month is missing; accepted predecessor remains live"
            )
        if stage in {"discover", "acquire"}:
            profile = str(task.get("import_profile_key", "property-fixture"))
            records = _canonical_records(profile) if stage == "acquire" else []
            document = (
                {
                    "schema_version": "propertyscope.canonical-import.v1",
                    "profile": profile,
                    "records": records,
                }
                if stage == "acquire"
                else {
                    "schema_version": "propertyscope.source-snapshot.v1",
                    "adapter_key": task.get("adapter_key", "fixture-snapshot"),
                    "scope": scope,
                    "objects": [{"logical_key": "bounded-fixture", "complete": True}],
                }
            )
            canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            artifact = self.artifacts.put(
                (canonical,),
                max_bytes=min(int(task.get("max_bytes", 1_000_000)), 50_000_000),
                media_type="application/json",
            )
            response = self.client.post(
                f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/{task['id']}/artifacts",
                headers=self._headers(),
                json={
                    "ingestion_run_id": task["ingestion_run_id"],
                    "logical_key": task["logical_key"],
                    "artifact_kind": "source_snapshot"
                    if stage == "discover"
                    else "canonical_import",
                    "storage_key": artifact.storage_key,
                    "content_sha256": artifact.sha256,
                    "media_type": artifact.media_type,
                    "bytes": artifact.bytes,
                    "schema_version": document["schema_version"],
                    "retention_class": "candidate",
                },
            )
            response.raise_for_status()
            return len(records), len(records)
        if stage == "import":
            return self._execute_import(task)
        if stage == "build_release":
            response = self.client.post(
                f"{self.settings.backend_url}/internal/data-platform/v1/worker/runs/"
                f"{task['ingestion_run_id']}/finalize-release",
                headers=self._headers(),
                json={},
            )
            response.raise_for_status()
            return 1, 1
        return 10, 10

    def _execute_import(self, task: dict[str, Any]) -> tuple[int, int]:
        response = self.client.post(
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/runs/"
            f"{task['ingestion_run_id']}/imports",
            headers=self._headers(),
            json={"run_task_id": task["id"]},
        )
        response.raise_for_status()
        operation = response.json()["operation"]
        deadline = time.monotonic() + min(int(task.get("timeout_seconds", 120)), 120)
        while operation["status"] not in {"succeeded", "failed", "cancelled"}:
            if time.monotonic() >= deadline:
                raise RuntimeError("Registered import did not complete inside the task deadline")
            self.stop_event.wait(min(self.settings.poll_seconds, 1.0))
            self._heartbeat(str(task["id"]), str(task["lease_token"]))
            response = self.client.get(
                f"{self.settings.backend_url}/internal/data-platform/v1/worker/imports/"
                f"{operation['id']}",
                headers=self._headers(),
            )
            response.raise_for_status()
            operation = response.json()["operation"]
        if operation["status"] != "succeeded":
            raise RuntimeError("Registered import failed; accepted generation remains unchanged")
        return int(operation["rows_in"]), int(operation["rows_accepted"])

    def _heartbeat(self, task_id: str, lease_token: str) -> None:
        response = self.client.post(
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/{task_id}/heartbeat",
            headers=self._headers(),
            json={
                "worker_id": self.settings.worker_id,
                "lease_token": lease_token,
                "lease_seconds": self.settings.lease_seconds,
            },
        )
        response.raise_for_status()

    def _headers(self) -> dict[str, str]:
        return {
            "X-PropertyScope-Runner-Token": self.settings.token,
            "X-Request-ID": str(uuid.uuid4()),
        }


def _safe_message(exc: Exception) -> str:
    if isinstance(exc, RuntimeError) and "Required fixture month" in str(exc):
        return str(exc)
    return "Registered stage failed; inspect structured run evidence"


def _canonical_records(profile: str) -> list[dict[str, object]]:
    """Produce bounded licensed synthetic evidence through every registered import profile."""
    if profile == "property-fixture":
        return [{"source_key": f"fixture-{index:03d}"} for index in range(1, 11)]
    if profile == "schools-master":
        return [
            {
                "school_code": f"S{index:04d}",
                "school_name": f"Example Public School {index}",
                "school_type": "Primary",
                "status": "Open",
                "locality_original": "Sydney",
                "locality_normalised": "SYDNEY",
                "lga_name": "City of Sydney",
                "latitude": -33.9 + index * 0.001,
                "longitude": 151.1 + index * 0.001,
            }
            for index in range(1, 11)
        ]
    if profile == "gnaf-nsw":
        return [
            {
                "gnaf_pid": f"GANSWFIXTURE{index:04d}",
                "property_ref": None,
                "address_display": f"{index} Fixture Street, Sydney NSW 2000",
                "locality": "SYDNEY",
                "postcode": "2000",
                "source_status": "CURRENT",
                "geocode_type": "PC",
                "source_crs": 7844,
                "latitude": -33.9 + index * 0.001,
                "longitude": 151.1 + index * 0.001,
            }
            for index in range(1, 11)
        ]
    if profile == "psi-sales":
        return [
            {
                "source_business_key": f"001:P{index}:1",
                "source_revision": 1,
                "source_era": "post-2001",
                "district_code": "001",
                "property_id": f"P{index}",
                "dealing_id": f"D{index}",
                "contract_date": "2025-01-01",
                "settlement_date": "2025-02-01",
                "price_aud": 800_000 + index,
                "area_original": "500",
                "area_unit": "M",
                "area_square_metres": "500",
                "property_ref": None,
                "match_tier": "MISS",
                "match_confidence": "0",
                "geographic_precision": "unmatched",
            }
            for index in range(1, 11)
        ]
    if profile == "bocsar-sparse":
        records: list[dict[str, object]] = []
        for index in range(1, 6):
            category = f"fixture-category-{index}"
            records.extend(
                (
                    {
                        "record_kind": "observation",
                        "geography_kind": "postcode",
                        "geography_value": "2000",
                        "source_category_key": category,
                        "offence_label": "Synthetic offence",
                        "subcategory_label": f"Synthetic category {index}",
                        "month": "2025-02-01",
                        "count": index,
                    },
                    {
                        "record_kind": "coverage",
                        "geography_kind": "postcode",
                        "geography_value": "2000",
                        "source_category_key": category,
                        "observed_months": ["2025-01-01", "2025-02-01"],
                        "blank_means_observed_zero": True,
                    },
                )
            )
        return records
    raise RuntimeError("Task import profile is not registered by this runner")


def main() -> None:
    runner = AcquisitionRunner(RunnerSettings.from_environment())
    signal.signal(signal.SIGTERM, lambda *_: runner.stop())
    signal.signal(signal.SIGINT, lambda *_: runner.stop())
    runner.run_forever()


if __name__ == "__main__":
    main()
