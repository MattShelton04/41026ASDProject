"""Serial acquisition runner using only the backend worker HTTP contract."""

from __future__ import annotations

import json
import os
import signal
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
            document = {
                "schema_version": "propertyscope.fixture-artifact.v1",
                "run_id": task["ingestion_run_id"],
                "task_id": task["id"],
                "stage": stage,
                "scope": scope,
                "records": [
                    {"source_key": f"fixture-{index:03d}", "value": index} for index in range(1, 11)
                ],
            }
            canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            artifact = self.artifacts.put(
                (canonical,), max_bytes=1_000_000, media_type="application/json"
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
                    "schema_version": "propertyscope.fixture-artifact.v1",
                    "retention_class": "candidate",
                },
            )
            response.raise_for_status()
            return len(document["records"]), len(document["records"])
        # Database import execution is separately durable; showcase stages remain bounded no-ops
        # until a registered operation is available. They still produce a complete auditable ledger.
        return 10, 10

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


def main() -> None:
    runner = AcquisitionRunner(RunnerSettings.from_environment())
    signal.signal(signal.SIGTERM, lambda *_: runner.stop())
    signal.signal(signal.SIGINT, lambda *_: runner.stop())
    runner.run_forever()


if __name__ == "__main__":
    main()
