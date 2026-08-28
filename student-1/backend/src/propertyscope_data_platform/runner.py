"""Serial acquisition runner using only the backend worker HTTP contract."""

from __future__ import annotations

import json
import logging
import os
import signal
import time
import uuid
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Any

import httpx

from propertyscope_data_platform.acquisition_scope import complete_scope_error
from propertyscope_data_platform.adapters.bocsar import (
    CrimeCoverage,
    CrimeObservation,
    iter_bocsar_archive,
    parse_bocsar_archive,
)
from propertyscope_data_platform.adapters.gnaf import GnafAddress, iter_gnaf_archive_path
from propertyscope_data_platform.adapters.psi import (
    PsiSale,
    iter_psi_archive_path,
    parse_psi_archive_path,
)
from propertyscope_data_platform.adapters.schools import parse_schools_csv
from propertyscope_data_platform.artifacts import LocalArtifactStore
from propertyscope_data_platform.release_builders import (
    BuildContext,
    resolve_release_builder,
    validate_feature_registration,
)
from propertyscope_data_platform.source_transport import RegisteredSourceTransport

SCHOOLS_MASTER_URL = (
    "https://data.nsw.gov.au/data/dataset/"
    "78c10ea3-8d04-4c9c-b255-bbf8547e37e7/resource/"
    "3e6d5f6a-055c-440d-a690-fc0537c31095/download/master_dataset.csv"
)
BOCSAR_URLS = {
    "suburb": "https://bocsarblob.blob.core.windows.net/bocsar-open-data/SuburbData.zip",
    "postcode": "https://bocsarblob.blob.core.windows.net/bocsar-open-data/PostcodeData.zip",
}
PSI_YEARLY_URL = "https://www.valuergeneral.nsw.gov.au/__psi/yearly/{year}.zip"
PSI_WEEKLY_URL = "https://www.valuergeneral.nsw.gov.au/__psi/weekly/{date}.zip"
GNAF_CKAN_URL = (
    "https://data.gov.au/data/api/3/action/package_show?id=19432f89-dc3a-4ef3-b943-5326ef1dbecc"
)
logger = logging.getLogger(__name__)


class TaskCancelledError(RuntimeError):
    """The control plane acknowledged an operator cancellation for active work."""


@dataclass(frozen=True, slots=True)
class RunnerSettings:
    backend_url: str
    token: str
    artifact_root: Path
    worker_id: str
    poll_seconds: float
    lease_seconds: int
    gnaf_archive_path: Path | None = None
    gnaf_archive_crs: str = "GDA94"
    psi_archive_root: Path | None = None

    @classmethod
    def from_environment(cls) -> RunnerSettings:
        return cls(
            backend_url=os.environ.get(
                "PROPERTYSCOPE_BACKEND_URL", "http://f1-backend:5201"
            ).rstrip("/"),
            token=os.environ.get("PROPERTYSCOPE_RUNNER_TOKEN", "local-runner-only"),
            artifact_root=Path(
                os.environ.get("PROPERTYSCOPE_ARTIFACT_ROOT", "/var/lib/propertyscope/artifacts")
            ),
            worker_id=os.environ.get("PROPERTYSCOPE_RUNNER_ID", f"runner-{uuid.uuid4().hex[:8]}"),
            poll_seconds=float(os.environ.get("PROPERTYSCOPE_RUNNER_POLL_SECONDS", "1")),
            lease_seconds=int(os.environ.get("PROPERTYSCOPE_RUNNER_LEASE_SECONDS", "30")),
            gnaf_archive_path=_optional_path(os.environ.get("PROPERTYSCOPE_GNAF_ARCHIVE_PATH")),
            gnaf_archive_crs=os.environ.get("PROPERTYSCOPE_GNAF_CRS", "GDA94").upper(),
            psi_archive_root=_optional_path(os.environ.get("PROPERTYSCOPE_PSI_ARCHIVE_ROOT")),
        )


class AcquisitionRunner:
    """Deterministic worker; source transports are selected by registered jobs only."""

    def __init__(
        self,
        settings: RunnerSettings,
        *,
        client: httpx.Client | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.settings = settings
        self.client = client or httpx.Client(timeout=10, follow_redirects=False)
        self.source_transport = RegisteredSourceTransport(self.client)
        self.artifacts = LocalArtifactStore(settings.artifact_root)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.stop_event = Event()

    def run_forever(self) -> None:
        while not self.stop_event.is_set():
            try:
                worked = self.run_once()
            except httpx.HTTPError:
                logger.exception("Runner control-plane request failed; polling will resume")
                worked = False
            if not worked:
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
        except TaskCancelledError:
            logger.info("Run task %s (%s) cancelled by operator", task_id, task.get("stage"))
        except httpx.TransportError as exc:
            logger.exception("Run task %s (%s) lost a dependency", task_id, task.get("stage"))
            self._report_failure(task, lease_token, exc, retryable=True)
        except Exception as exc:
            logger.exception("Run task %s (%s) failed", task_id, task.get("stage"))
            self._report_failure(task, lease_token, exc, retryable=False)
        return True

    def _report_failure(
        self,
        task: dict[str, Any],
        lease_token: str,
        exc: Exception,
        *,
        retryable: bool,
    ) -> None:
        safe_code = (
            "quality_gate_failed"
            if str(task.get("stage")) == "quality"
            else "stage_execution_failed"
        )
        failure = self.client.post(
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/{task['id']}/fail",
            headers=self._headers(),
            json={
                "worker_id": self.settings.worker_id,
                "lease_token": lease_token,
                "error": {"code": safe_code, "message": _safe_message(exc)},
                "retryable": retryable,
            },
        )
        failure.raise_for_status()

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
            scope_error = complete_scope_error(profile, scope)
            if scope_error is not None:
                raise RuntimeError(f"Incomplete acquisition scope: {scope_error}")
            if profile in {"psi-sales", "gnaf-nsw", "bocsar-sparse"} and stage == "acquire":
                scope = task.get("partition_json") or {}
                if not isinstance(scope, dict):
                    raise RuntimeError("Registered live scope is invalid")
                counter = [0]
                if profile == "psi-sales":
                    canonical_chunks = self._live_psi_chunks(task, scope, counter)
                elif profile == "gnaf-nsw":
                    canonical_chunks = self._live_gnaf_chunks(task, scope, counter)
                else:
                    canonical_chunks = self._live_bocsar_chunks(task, scope, counter)
                artifact = self.artifacts.put(
                    canonical_chunks,
                    media_type="application/x-ndjson",
                )
                self._register_stage_artifact(
                    task,
                    stage=stage,
                    artifact=artifact,
                    schema_version="propertyscope.canonical-import.v1",
                )
                return counter[0], counter[0]
            if profile != "property-fixture":
                document, records = self._live_document(task, stage=stage, profile=profile)
            else:
                records = _fixture_records() if stage == "acquire" else []
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
                        "source_release": "fixture-v1",
                        "scope": scope,
                        "objects": [{"logical_key": "bounded-fixture", "complete": True}],
                    }
                )
            canonical = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
            artifact = self.artifacts.put(
                (canonical,),
                media_type="application/json",
            )
            self._register_stage_artifact(
                task,
                stage=stage,
                artifact=artifact,
                schema_version=str(document["schema_version"]),
                source_snapshot=document if stage == "discover" else None,
            )
            return len(records), len(records)
        if stage == "import":
            return self._execute_import(task)
        if stage == "build_release":
            return self._execute_release_build(task)
        return 0, 0

    def _execute_release_build(self, task: dict[str, Any]) -> tuple[int, int]:
        run_id = str(task["ingestion_run_id"])
        context_response = self._control_request(
            "GET",
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/runs/"
            f"{run_id}/release-build-context",
            headers=self._headers(),
        )
        context_response.raise_for_status()
        payload = context_response.json()
        builder_ref = payload.get("builder")
        if not isinstance(builder_ref, dict):
            raise RuntimeError("Release build context has no registered builder")
        builder = resolve_release_builder(
            str(builder_ref.get("key")), str(builder_ref.get("version"))
        )
        target_contract = str(payload.get("target_contract"))
        if target_contract != builder.spec.contract:
            raise RuntimeError("Release target contract does not match the registered builder")
        context = BuildContext.model_validate(payload.get("context"))
        release_id = str(payload["release_id"])
        product_scope = context.scope.get("release_scope", context.scope)
        if not isinstance(product_scope, dict):
            raise RuntimeError("Release product scope is invalid")
        maximum_records = product_scope.get("maximum_records")
        if (
            not isinstance(maximum_records, int)
            or isinstance(maximum_records, bool)
            or maximum_records < 1
            or maximum_records > builder.spec.max_rows
        ):
            raise RuntimeError("Release product scope has no valid registered row bound")
        rows: list[dict[str, Any]] = []
        offset = 0
        page_size = 5_000
        expected_total: int | None = None
        while True:
            page_response = self._control_request(
                "GET",
                f"{self.settings.backend_url}/internal/data-platform/v1/worker/releases/"
                f"{release_id}/product-records",
                headers=self._headers(),
                params={"limit": page_size, "offset": offset},
                timeout=120,
            )
            page_response.raise_for_status()
            page = page_response.json()
            page_release_id = str(page.get("release_id", release_id))
            generation_id = str(
                page.get("candidate_generation_id", context.candidate_generation_id)
            )
            if page_release_id != release_id or generation_id != str(
                context.candidate_generation_id
            ):
                raise RuntimeError("Candidate generation changed during release construction")
            total = int(page["total"])
            if expected_total is None:
                expected_total = total
                if total > maximum_records:
                    raise RuntimeError(
                        "Release product exceeds requested maximum_records; narrow the scope"
                    )
            elif total != expected_total:
                raise RuntimeError("Candidate generation count changed during release construction")
            items = page.get("items")
            if not isinstance(items, list):
                raise RuntimeError("Release product page is malformed")
            rows.extend(items)
            if len(rows) > builder.spec.max_rows:
                raise RuntimeError(
                    "Release product exceeds its row bound; narrow the requested scope"
                )
            next_offset = page.get("next_offset")
            if next_offset is None:
                break
            if not isinstance(next_offset, int) or next_offset <= offset:
                raise RuntimeError("Release product pagination cursor is invalid")
            lease_token = task.get("lease_token")
            if isinstance(lease_token, str) and lease_token:
                self._heartbeat(str(task["id"]), lease_token)
            offset = next_offset
        if expected_total != len(rows):
            raise RuntimeError("Release product page count is inconsistent")
        product = builder.build(context, rows, created_at=self.clock())
        artifact = self.artifacts.put(
            (product.content,),
            max_bytes=builder.spec.max_bytes,
            media_type=builder.spec.media_type,
        )
        registration = self._control_request(
            "POST",
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/"
            f"{task['id']}/artifacts",
            headers=self._headers(),
            json={
                "ingestion_run_id": run_id,
                "logical_key": task["logical_key"],
                "artifact_kind": "release_export",
                "storage_key": artifact.storage_key,
                "content_sha256": artifact.sha256,
                "media_type": artifact.media_type,
                "bytes": artifact.bytes,
                "schema_version": builder.spec.contract,
                "retention_class": "candidate",
            },
        )
        registration.raise_for_status()
        artifact_record = registration.json()["artifact"]
        finalize = self._control_request(
            "POST",
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/runs/"
            f"{run_id}/finalize-release",
            headers=self._headers(),
            json={
                "artifact_record_id": artifact_record["id"],
                "schema_version": builder.spec.contract,
                "content_sha256": artifact.sha256,
                "record_count": product.manifest.record_count,
                "manifest": product.manifest.model_dump(mode="json"),
            },
        )
        finalize.raise_for_status()
        return len(rows), product.manifest.record_count

    def _register_stage_artifact(
        self,
        task: dict[str, Any],
        *,
        stage: str,
        artifact: Any,
        schema_version: str,
        source_snapshot: dict[str, object] | None = None,
    ) -> None:
        response = self.client.post(
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/{task['id']}/artifacts",
            headers=self._headers(),
            json={
                "ingestion_run_id": task["ingestion_run_id"],
                "logical_key": task["logical_key"],
                "artifact_kind": "source_snapshot" if stage == "discover" else "canonical_import",
                "storage_key": artifact.storage_key,
                "content_sha256": artifact.sha256,
                "media_type": artifact.media_type,
                "bytes": artifact.bytes,
                "schema_version": schema_version,
                "retention_class": "candidate",
                "source_snapshot": source_snapshot,
            },
        )
        response.raise_for_status()

    def _live_document(
        self, task: dict[str, Any], *, stage: str, profile: str
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        """Acquire a registered real source or fail instead of substituting fixtures."""
        if profile not in {"schools-master", "bocsar-sparse", "psi-sales", "gnaf-nsw"}:
            raise RuntimeError("This registered profile has no connected live transport")
        scope = task.get("partition_json") or {}
        if not isinstance(scope, dict):
            raise RuntimeError("Registered live scope is invalid")
        if stage == "discover":
            objects = self._live_objects(profile, scope)
            return (
                {
                    "schema_version": "propertyscope.source-snapshot.v1",
                    "adapter_key": task.get("adapter_key"),
                    "source_release": _source_release_for_objects(objects),
                    "scope": scope,
                    "objects": objects,
                },
                [],
            )
        if profile == "bocsar-sparse":
            return self._live_bocsar(task, scope)
        if profile == "psi-sales":
            return self._live_psi(task, scope)
        if profile == "gnaf-nsw":
            raise RuntimeError("G-NAF live acquisition is available through the run worker")
        content = self._download_registered(SCHOOLS_MASTER_URL)
        parsed = parse_schools_csv(content)
        records: list[dict[str, object]] = [
            {
                "school_code": record.school_code,
                "school_name": record.school_name,
                "school_type": record.school_type,
                "status": record.status,
                "locality_original": record.locality_original,
                "locality_normalised": record.locality_normalised,
                "lga_name": record.lga_name,
                "latitude": record.latitude,
                "longitude": record.longitude,
            }
            for record in parsed
        ]
        return (
            {
                "schema_version": "propertyscope.canonical-import.v1",
                "profile": profile,
                "source": {
                    "publisher": "NSW Department of Education",
                    "source_url": SCHOOLS_MASTER_URL,
                    "media_type": "text/csv",
                    "real_source": True,
                },
                "records": records,
            },
            records,
        )

    def _live_objects(self, profile: str, scope: dict[str, object]) -> list[dict[str, object]]:
        if profile == "schools-master":
            return [_source_object("nsw-government-schools-master", SCHOOLS_MASTER_URL, "text/csv")]
        if profile == "bocsar-sparse":
            kinds = _bocsar_kinds(scope)
            return [
                _source_object(f"bocsar-{kind}", BOCSAR_URLS[kind], "application/zip")
                for kind in kinds
            ]
        if profile == "gnaf-nsw":
            url, crs = self._gnaf_source()
            return [
                {
                    **_source_object("gnaf-nsw-bulk", url, "application/zip"),
                    "coordinate_reference_system": crs,
                    "cached": url.startswith("file-cache://"),
                }
            ]
        years = _psi_years(scope)
        objects: list[dict[str, object]] = []
        for year in years:
            cached = self._psi_archive(int(year))
            source = _source_object(
                f"psi-year-{year}", PSI_YEARLY_URL.format(year=year), "application/zip"
            )
            source["cached"] = cached is not None
            if cached is not None:
                source["cache_key"] = f"psi/{year}.zip"
            objects.append(source)
        for week in _psi_weeks(scope):
            source = _source_object(
                f"psi-week-{week.isoformat()}",
                PSI_WEEKLY_URL.format(date=week.strftime("%Y%m%d")),
                "application/zip",
            )
            cached_week = self._psi_week_archive(week)
            source["cached"] = cached_week is not None
            if cached_week is not None:
                source["cache_key"] = f"psi/weekly/{week.strftime('%Y%m%d')}.zip"
            objects.append(source)
        return objects

    def _live_bocsar(
        self, task: dict[str, Any], scope: dict[str, object]
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        kind = str(scope.get("geography_kind", "postcode"))
        if kind not in BOCSAR_URLS:
            raise RuntimeError("BOCSAR geography_kind must be postcode or suburb")
        raw_values = scope.get("geography_values")
        geography_values = (
            frozenset(str(value).strip() for value in raw_values)
            if isinstance(raw_values, list) and raw_values
            else None
        )
        content = self._download_registered(BOCSAR_URLS[kind])
        observations, coverage = parse_bocsar_archive(
            content,
            geography_kind=kind,
            maximum_rows=None,
            geography_values=geography_values,
            start_month=_month_scope(scope.get("start_month")),
            end_month=_month_scope(scope.get("end_month")),
            maximum_records=None,
        )
        records: list[dict[str, object]] = [
            {
                "record_kind": "observation",
                "geography_kind": item.geography_kind,
                "geography_value": item.geography_value,
                "source_category_key": item.category_key,
                "offence_label": item.offence_label,
                "subcategory_label": item.subcategory_label,
                "month": item.month.isoformat(),
                "count": item.count,
            }
            for item in observations
        ]
        records.extend(
            {
                "record_kind": "coverage",
                "geography_kind": item.geography_kind,
                "geography_value": item.geography_value,
                "source_category_key": item.category_key,
                "observed_months": [month.isoformat() for month in item.observed_months],
                "blank_means_observed_zero": item.blank_means_observed_zero,
            }
            for item in coverage
        )
        return _live_canonical_document("bocsar-sparse", BOCSAR_URLS[kind], records), records

    def _live_bocsar_chunks(
        self, task: dict[str, Any], scope: dict[str, object], counter: list[int]
    ) -> Iterable[bytes]:
        raw_values = scope.get("geography_values")
        geography_values = (
            frozenset(str(value).strip() for value in raw_values)
            if isinstance(raw_values, list) and raw_values
            else None
        )
        for kind in _bocsar_kinds(scope):
            content = self._download_registered(BOCSAR_URLS[kind])
            records = iter_bocsar_archive(
                content,
                geography_kind=kind,
                maximum_rows=None,
                geography_values=geography_values,
                start_month=_month_scope(scope.get("start_month")),
                end_month=_month_scope(scope.get("end_month")),
                maximum_records=None,
                maximum_uncompressed_bytes=None,
            )
            for item in records:
                counter[0] += 1
                if counter[0] % 25_000 == 0:
                    self._heartbeat(str(task["id"]), str(task["lease_token"]))
                yield (
                    json.dumps(_bocsar_record(item), sort_keys=True, separators=(",", ":")).encode()
                    + b"\n"
                )

    def _live_psi(
        self, task: dict[str, Any], scope: dict[str, object]
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        years = scope.get("years")
        if (
            not isinstance(years, list)
            or not years
            or any(not isinstance(year, int) for year in years)
        ):
            raise RuntimeError("PSI live scope requires integer source years")
        records: list[dict[str, object]] = []
        source_urls: list[str] = []
        cached_years: list[int] = []
        for year in years:
            url = PSI_YEARLY_URL.format(year=year)
            source_urls.append(url)
            cached = self._psi_archive(year)
            if cached is not None:
                cached_years.append(year)
            source: AbstractContextManager[Path]
            if cached is not None:
                source = nullcontext(cached)
            else:
                source = self.source_transport.psi_archive_path(
                    url,
                    directory=self.settings.artifact_root,
                    progress=self._heartbeat_progress(task),
                )
            with source as path:
                sales = parse_psi_archive_path(path, source_year=year)
            for sale in sales:
                records.append(_psi_record(sale, source_year=year))
        document = _live_canonical_document("psi-sales", source_urls, records)
        source_metadata = document["source"]
        assert isinstance(source_metadata, dict)
        source_metadata["cached_source_years"] = cached_years
        return document, records

    def _live_psi_chunks(
        self, task: dict[str, Any], scope: dict[str, object], counter: list[int]
    ) -> Iterable[bytes]:
        """Stream complete PSI partitions as canonical NDJSON without retaining history in RAM."""
        years = _psi_years(scope)
        sources = [
            (year, PSI_YEARLY_URL.format(year=year), self._psi_archive(year)) for year in years
        ]
        sources.extend(
            (
                week.year,
                PSI_WEEKLY_URL.format(date=week.strftime("%Y%m%d")),
                self._psi_week_archive(week),
            )
            for week in _psi_weeks(scope)
        )
        if not sources:
            raise RuntimeError("PSI full-data scope contains no annual or weekly partitions")
        for source_year, url, cached in sources:
            source: AbstractContextManager[Path]
            if cached is not None:
                source = nullcontext(cached)
            else:
                source = self.source_transport.psi_archive_path(
                    url,
                    directory=self.settings.artifact_root,
                    progress=self._heartbeat_progress(task),
                )
            with source as path:
                for sale in iter_psi_archive_path(path, source_year=source_year):
                    counter[0] += 1
                    if counter[0] % 25_000 == 0:
                        self._heartbeat(str(task["id"]), str(task["lease_token"]))
                    yield (
                        json.dumps(
                            _psi_record(sale, source_year=source_year),
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode()
                        + b"\n"
                    )

    def _psi_archive(self, year: int) -> Path | None:
        root = self.settings.psi_archive_root
        if root is None:
            return None
        candidate = root / f"{year}.zip"
        return candidate if candidate.is_file() else None

    def _psi_week_archive(self, week: date) -> Path | None:
        root = self.settings.psi_archive_root
        if root is None:
            return None
        candidate = root / "weekly" / f"{week.strftime('%Y%m%d')}.zip"
        return candidate if candidate.is_file() else None

    def _live_gnaf_chunks(
        self, task: dict[str, Any], scope: dict[str, object], counter: list[int]
    ) -> Iterable[bytes]:
        """Stream the complete registered NSW address generation without retaining it in RAM."""
        source_url, declared_crs = self._discovered_gnaf_source(task)
        if self.settings.gnaf_archive_path and self.settings.gnaf_archive_path.is_file():
            stream = self.settings.gnaf_archive_path.open("rb")
            try:
                raw_artifact = self.artifacts.put(
                    self._heartbeat_chunks(task, iter(lambda: stream.read(1024 * 1024), b"")),
                    media_type="application/zip",
                )
            finally:
                stream.close()
        else:
            headers = {"Accept": "application/zip", "User-Agent": "PropertyScope/1.0"}
            with (
                httpx.Client(timeout=None, follow_redirects=False) as source_client,
                source_client.stream("GET", source_url, headers=headers) as response,
            ):
                response.raise_for_status()
                if response.url.host != "data.gov.au":
                    raise RuntimeError("G-NAF download left the registered host")
                raw_artifact = self.artifacts.put(
                    self._heartbeat_chunks(task, response.iter_bytes()),
                    media_type="application/zip",
                )
        raw_path = self.artifacts.verified_path(
            raw_artifact.storage_key,
            raw_artifact.sha256,
            expected_bytes=raw_artifact.bytes,
        )
        registration = self.client.post(
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/{task['id']}/artifacts",
            headers=self._headers(),
            json={
                "ingestion_run_id": task["ingestion_run_id"],
                "logical_key": f"{task['logical_key']}/raw-gnaf",
                "artifact_kind": "source_payload",
                "storage_key": raw_artifact.storage_key,
                "content_sha256": raw_artifact.sha256,
                "media_type": raw_artifact.media_type,
                "bytes": raw_artifact.bytes,
                "schema_version": "geoscape.gnaf.psv.zip",
                "retention_class": "source-cache",
            },
        )
        registration.raise_for_status()
        raw_localities = scope.get("localities")
        localities = (
            frozenset(str(value).strip().upper() for value in raw_localities)
            if isinstance(raw_localities, list) and raw_localities
            else None
        )
        parsed = iter_gnaf_archive_path(
            raw_path,
            declared_crs=declared_crs,
            maximum_records=None,
            capacity_ceiling=None,
            localities=localities,
            progress=self._heartbeat_progress(task),
        )
        for item in parsed:
            counter[0] += 1
            yield (
                json.dumps(_gnaf_record(item), sort_keys=True, separators=(",", ":")).encode()
                + b"\n"
            )

    def _discovered_gnaf_source(self, task: dict[str, Any]) -> tuple[str, str]:
        snapshot = task.get("source_snapshot_json")
        if not isinstance(snapshot, dict):
            raise RuntimeError("G-NAF acquisition requires retained discovery evidence")
        objects = snapshot.get("objects")
        if not isinstance(objects, list) or len(objects) != 1 or not isinstance(objects[0], dict):
            raise RuntimeError("G-NAF discovery evidence is invalid")
        source_url = objects[0].get("source_url")
        declared_crs = objects[0].get("coordinate_reference_system")
        if not isinstance(source_url, str) or declared_crs not in {"GDA94", "GDA2020"}:
            raise RuntimeError("G-NAF discovery resource evidence is incomplete")
        return source_url, str(declared_crs)

    def _gnaf_source(self) -> tuple[str, str]:
        if self.settings.gnaf_archive_path and self.settings.gnaf_archive_path.is_file():
            if self.settings.gnaf_archive_crs not in {"GDA94", "GDA2020"}:
                raise RuntimeError("Cached G-NAF CRS must be GDA94 or GDA2020")
            return "file-cache://gnaf.zip", self.settings.gnaf_archive_crs
        response = self.client.get(
            GNAF_CKAN_URL, headers={"Accept": "application/json", "User-Agent": "PropertyScope/1.0"}
        )
        response.raise_for_status()
        resources = response.json().get("result", {}).get("resources", [])
        candidates = [
            item
            for item in resources
            if isinstance(item, dict)
            and str(item.get("url", "")).startswith("https://data.gov.au/")
            and str(item.get("url", "")).lower().endswith(".zip")
            and "psv" in str(item.get("url", "")).lower()
            and any(crs in str(item.get("url", "")).lower() for crs in ("gda2020", "gda94"))
        ]
        if not candidates:
            raise RuntimeError("G-NAF CKAN package has no registered PSV resource")
        selected = max(
            candidates,
            key=lambda item: (
                str(item.get("last_modified", "")),
                "gda2020" in str(item.get("url", "")).lower(),
            ),
        )
        url = str(selected["url"])
        return url, "GDA2020" if "gda2020" in url.lower() else "GDA94"

    def _heartbeat_chunks(self, task: dict[str, Any], chunks: Iterable[bytes]) -> Iterable[bytes]:
        progress = self._heartbeat_progress(task)
        for chunk in chunks:
            progress(len(chunk))
            yield chunk

    def _heartbeat_progress(self, task: dict[str, Any]) -> Callable[[int], None]:
        last_heartbeat = time.monotonic()
        interval = _cancellation_poll_interval(self.settings.lease_seconds)

        def report_progress(_bytes_processed: int) -> None:
            nonlocal last_heartbeat
            if time.monotonic() - last_heartbeat >= interval:
                self._heartbeat(str(task["id"]), str(task["lease_token"]))
                last_heartbeat = time.monotonic()

        return report_progress

    def _download_registered(self, url: str) -> bytes:
        return self.source_transport.download_bytes(url)

    def _execute_import(self, task: dict[str, Any]) -> tuple[int, int]:
        response = self._control_request(
            "POST",
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/runs/"
            f"{task['ingestion_run_id']}/imports",
            headers=self._headers(),
            json={"run_task_id": task["id"]},
        )
        response.raise_for_status()
        operation = response.json()["operation"]
        while operation["status"] not in {"succeeded", "failed", "cancelled"}:
            self.stop_event.wait(min(self.settings.poll_seconds, 1.0))
            self._heartbeat(str(task["id"]), str(task["lease_token"]))
            response = self._control_request(
                "GET",
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
        response = self._control_request(
            "POST",
            f"{self.settings.backend_url}/internal/data-platform/v1/worker/tasks/{task_id}/heartbeat",
            headers=self._headers(),
            json={
                "worker_id": self.settings.worker_id,
                "lease_token": lease_token,
                "lease_seconds": self.settings.lease_seconds,
            },
        )
        response.raise_for_status()
        task = response.json().get("task")
        if isinstance(task, dict) and task.get("status") == "cancelled":
            raise TaskCancelledError("Run task cancelled by operator")

    def _control_request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Retry brief control-plane disconnects without losing durable work."""
        for attempt in range(5):
            try:
                return self.client.request(method, url, **kwargs)
            except httpx.TransportError:
                if attempt == 4:
                    raise
                self.stop_event.wait(min(2**attempt, 5))
        raise AssertionError("unreachable")

    def _headers(self) -> dict[str, str]:
        return {
            "X-PropertyScope-Runner-Token": self.settings.token,
            "X-Request-ID": str(uuid.uuid4()),
        }


def _safe_message(exc: Exception) -> str:
    if isinstance(exc, RuntimeError) and "Required fixture month" in str(exc):
        return str(exc)
    return "Registered stage failed; inspect structured run evidence"


def _cancellation_poll_interval(lease_seconds: int) -> float:
    """Keep cancellation responsive without shortening the durable recovery lease."""
    return min(5.0, max(1.0, lease_seconds / 3))


def _psi_years(scope: dict[str, object]) -> list[int]:
    if scope.get("all_history") is True:
        return list(range(1990, datetime.now(UTC).year))
    years = scope.get("years")
    if years is None and isinstance(scope.get("weeks"), list) and scope.get("weeks"):
        return []
    if not isinstance(years, list) or any(not isinstance(year, int) for year in years):
        raise RuntimeError("PSI live scope requires integer source years or all_history")
    return years


def _psi_weeks(scope: dict[str, object]) -> list[date]:
    raw = scope.get("weeks", [])
    if not isinstance(raw, list) or any(not isinstance(value, str) for value in raw):
        raise RuntimeError("PSI weekly partitions must be ISO dates")
    try:
        weeks = [date.fromisoformat(value) for value in raw]
    except ValueError as exc:
        raise RuntimeError("PSI weekly partitions must be ISO dates") from exc
    if scope.get("include_current_weekly") is True:
        today = datetime.now(UTC).date()
        cursor = date(today.year, 1, 1)
        cursor += timedelta(days=(7 - cursor.weekday()) % 7)
        while cursor <= today:
            weeks.append(cursor)
            cursor += timedelta(days=7)
    return sorted(set(weeks))


def _psi_record(sale: PsiSale, *, source_year: int) -> dict[str, object]:
    return {
        "source_business_key": sale.source_business_key,
        "source_revision": 1,
        "source_era": sale.source_era,
        "source_partition_year": source_year,
        "district_code": sale.district_code or None,
        "property_id": sale.property_id or None,
        "dealing_id": sale.dealing_id,
        "source_system": sale.source_system,
        "valuation_number": sale.valuation_number,
        "source_downloaded_at": sale.source_downloaded_at.isoformat()
        if sale.source_downloaded_at
        else None,
        "property_name": sale.property_name,
        "unit_number": sale.unit_number,
        "house_number": sale.house_number,
        "street_number_first": sale.street_number_first,
        "street_number_suffix": sale.street_number_suffix,
        "street_name": sale.street_name,
        "street_name_normalised": sale.street_name_normalised,
        "street_type": sale.street_type,
        "locality": sale.locality,
        "postcode": sale.postcode,
        "land_description": sale.land_description,
        "dimensions": sale.dimensions,
        "zoning_code": sale.zoning_code,
        "nature_code": sale.nature_code,
        "primary_purpose": sale.primary_purpose,
        "strata_lot_number": sale.strata_lot_number,
        "component_code": sale.component_code,
        "sale_code": sale.sale_code,
        "interest_of_sale": sale.interest_of_sale,
        "contract_date": sale.contract_date.isoformat() if sale.contract_date else None,
        "settlement_date": sale.settlement_date.isoformat() if sale.settlement_date else None,
        "price_aud": sale.price_aud,
        "area_original": str(sale.area_original) if sale.area_original is not None else None,
        "area_unit": sale.area_unit,
        "area_square_metres": str(sale.area_square_metres)
        if sale.area_square_metres is not None
        else None,
        "property_ref": None,
        "match_tier": "MISS",
        "match_confidence": "0",
        "geographic_precision": "unmatched",
    }


def _gnaf_record(item: GnafAddress) -> dict[str, object]:
    return {
        "gnaf_pid": item.gnaf_pid,
        "property_ref": None,
        "address_display": item.address_display,
        "flat_type": item.flat_type,
        "unit_number": item.unit_number,
        "street_number_first": item.street_number_first,
        "street_number_suffix": item.street_number_suffix,
        "street_number_last": item.street_number_last,
        "street_name": item.street_name,
        "street_type": item.street_type,
        "locality": item.locality,
        "postcode": item.postcode,
        "source_status": item.source_status,
        "geocode_type": item.geocode_type,
        "source_crs": item.source_crs,
        "latitude": item.latitude,
        "longitude": item.longitude,
    }


def _bocsar_record(item: CrimeObservation | CrimeCoverage) -> dict[str, object]:
    if isinstance(item, CrimeObservation):
        return {
            "record_kind": "observation",
            "geography_kind": item.geography_kind,
            "geography_value": item.geography_value,
            "source_category_key": item.category_key,
            "offence_label": item.offence_label,
            "subcategory_label": item.subcategory_label,
            "month": item.month.isoformat(),
            "count": item.count,
        }
    return {
        "record_kind": "coverage",
        "geography_kind": item.geography_kind,
        "geography_value": item.geography_value,
        "source_category_key": item.category_key,
        "observed_months": [month.isoformat() for month in item.observed_months],
        "blank_means_observed_zero": item.blank_means_observed_zero,
    }


def _month_scope(value: object) -> date | None:
    if value in {None, ""}:
        return None
    try:
        return date.fromisoformat(f"{value}-01" if len(str(value)) == 7 else str(value))
    except ValueError as exc:
        raise RuntimeError("Month scope must use YYYY-MM") from exc


def _bocsar_kinds(scope: dict[str, object]) -> tuple[str, ...]:
    raw_kinds = scope.get("geography_kinds")
    kinds = (
        tuple(str(value) for value in raw_kinds)
        if isinstance(raw_kinds, list) and raw_kinds
        else (str(scope.get("geography_kind", "postcode")),)
    )
    if (
        len(kinds) > 2
        or len(set(kinds)) != len(kinds)
        or any(kind not in BOCSAR_URLS for kind in kinds)
    ):
        raise RuntimeError("BOCSAR geography scope must select postcode, suburb, or both")
    return kinds


def _source_object(logical_key: str, url: str, media_type: str) -> dict[str, object]:
    return {
        "logical_key": logical_key,
        "source_url": url,
        "media_type": media_type,
        "complete": True,
    }


def _source_release_for_objects(objects: list[dict[str, object]]) -> str:
    keys = [str(item["logical_key"]) for item in objects]
    if not keys:
        raise RuntimeError("Source discovery returned no versioned objects")
    if len(keys) == 1:
        return keys[0]
    return f"{keys[0]}..{keys[-1]} ({len(keys)} objects)"[:100]


def _live_canonical_document(
    profile: str, source_url: str | list[str], records: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schema_version": "propertyscope.canonical-import.v1",
        "profile": profile,
        "source": {"source_url": source_url, "real_source": True},
        "records": records,
    }


def _optional_path(value: str | None) -> Path | None:
    return Path(value).resolve() if value and value.strip() else None


def _fixture_records() -> list[dict[str, object]]:
    """Return every record in the finite, explicitly synthetic fixture source."""
    localities = (
        ("PARRAMATTA", "2150", -33.8151, 151.0011),
        ("MOSMAN", "2088", -33.8298, 151.2441),
        ("WOLLONGONG", "2500", -34.4278, 150.8931),
    )
    return [
        {
            "source_pid": f"FIX-{index:03d}",
            "property_ref": None,
            "address_display": (
                f"{index} FIXTURE STREET {localities[(index - 1) % 3][0]} NSW "
                f"{localities[(index - 1) % 3][1]}"
            ),
            "flat_type": None,
            "unit_number": None,
            "street_number_first": index,
            "street_number_suffix": None,
            "street_number_last": None,
            "street_name": "FIXTURE",
            "street_type": "STREET",
            "locality": localities[(index - 1) % 3][0],
            "postcode": localities[(index - 1) % 3][1],
            "source_status": "CURRENT",
            "geocode_type": "FIXTURE",
            "source_crs": 4326,
            "latitude": localities[(index - 1) % 3][2] + index * 0.00001,
            "longitude": localities[(index - 1) % 3][3] + index * 0.00001,
        }
        for index in range(1, 11)
    ]


def main() -> None:
    validate_feature_registration(Path(__file__).resolve().parents[3])
    runner = AcquisitionRunner(RunnerSettings.from_environment())
    signal.signal(signal.SIGTERM, lambda *_: runner.stop())
    signal.signal(signal.SIGINT, lambda *_: runner.stop())
    runner.run_forever()


if __name__ == "__main__":
    main()
