"""Serial acquisition runner using only the backend worker HTTP contract."""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import urlparse

import httpx

from propertyscope_data_platform.adapters.bocsar import parse_bocsar_archive
from propertyscope_data_platform.adapters.gnaf import parse_gnaf_archive_path
from propertyscope_data_platform.adapters.psi import parse_psi_archive
from propertyscope_data_platform.adapters.schools import parse_schools_csv
from propertyscope_data_platform.artifacts import LocalArtifactStore

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
GNAF_CKAN_URL = (
    "https://data.gov.au/data/api/3/action/package_show?id=19432f89-dc3a-4ef3-b943-5326ef1dbecc"
)
LIVE_CANONICAL_RECORD_LIMIT = 50_000
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RunnerSettings:
    backend_url: str
    token: str
    artifact_root: Path
    worker_id: str
    poll_seconds: float
    lease_seconds: int
    full_data_enabled: bool = False
    gnaf_archive_path: Path | None = None
    gnaf_archive_crs: str = "GDA94"
    psi_archive_root: Path | None = None

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
            full_data_enabled=os.environ.get("PROPERTYSCOPE_FULL_DATA_ENABLED", "false").lower()
            in {"1", "true", "yes"},
            gnaf_archive_path=_optional_path(os.environ.get("PROPERTYSCOPE_GNAF_ARCHIVE_PATH")),
            gnaf_archive_crs=os.environ.get("PROPERTYSCOPE_GNAF_CRS", "GDA94").upper(),
            psi_archive_root=_optional_path(os.environ.get("PROPERTYSCOPE_PSI_ARCHIVE_ROOT")),
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
            live_requested = scope.get("profile") == "full-data"
            if live_requested and not self.settings.full_data_enabled:
                raise RuntimeError(
                    "Full-data acquisition requires the explicit full-data runtime profile"
                )
            if live_requested and profile != "property-fixture":
                document, records = self._live_document(task, stage=stage, profile=profile)
            else:
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
        return 0, 0

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
            return self._live_gnaf(task, scope)
        maximum_bytes = min(int(task.get("max_bytes", 25_000_000)), 25_000_000)
        content = self._download_registered(SCHOOLS_MASTER_URL, maximum_bytes=maximum_bytes)
        parsed = parse_schools_csv(content, maximum_rows=int(task.get("max_rows", 5_000)))
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
            kind = str(scope.get("geography_kind", "postcode"))
            if kind not in BOCSAR_URLS:
                raise RuntimeError("BOCSAR geography_kind must be postcode or suburb")
            return [_source_object(f"bocsar-{kind}", BOCSAR_URLS[kind], "application/zip")]
        if profile == "gnaf-nsw":
            url, crs = self._gnaf_source()
            return [
                {
                    **_source_object("gnaf-nsw-bulk", url, "application/zip"),
                    "coordinate_reference_system": crs,
                    "cached": url.startswith("file-cache://"),
                }
            ]
        years = scope.get("years")
        if not isinstance(years, list) or not years:
            raise RuntimeError("PSI live scope requires source years")
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
        return objects

    def _live_bocsar(
        self, task: dict[str, Any], scope: dict[str, object]
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        kind = str(scope.get("geography_kind", "postcode"))
        if kind not in BOCSAR_URLS:
            raise RuntimeError("BOCSAR geography_kind must be postcode or suburb")
        maximum_records = _record_limit(task, scope)
        raw_values = scope.get("geography_values")
        geography_values = (
            frozenset(str(value).strip() for value in raw_values)
            if isinstance(raw_values, list) and raw_values
            else None
        )
        content = self._download_registered(
            BOCSAR_URLS[kind], maximum_bytes=min(int(task.get("max_bytes", 50_000_000)), 50_000_000)
        )
        observations, coverage = parse_bocsar_archive(
            content,
            geography_kind=kind,
            maximum_rows=int(task.get("max_rows", 100_000)),
            geography_values=geography_values,
            start_month=_month_scope(scope.get("start_month")),
            end_month=_month_scope(scope.get("end_month")),
            maximum_records=maximum_records,
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
        remaining = _record_limit(task, scope)
        records: list[dict[str, object]] = []
        source_urls: list[str] = []
        cached_years: list[int] = []
        for year in years:
            if remaining <= 0:
                break
            url = PSI_YEARLY_URL.format(year=year)
            source_urls.append(url)
            maximum_bytes = min(int(task.get("max_bytes", 50_000_000)), 50_000_000)
            cached = self._psi_archive(year)
            if cached is not None:
                if cached.stat().st_size > maximum_bytes:
                    raise RuntimeError("Cached PSI archive exceeds the configured byte limit")
                content = cached.read_bytes()
                cached_years.append(year)
            else:
                content = self._download_psi_archive(url, maximum_bytes=maximum_bytes)
            sales = parse_psi_archive(content, source_year=year, maximum_records=remaining)
            for sale in sales:
                records.append(
                    {
                        "source_business_key": sale.source_business_key,
                        "source_revision": 1,
                        "source_era": sale.source_era,
                        "district_code": sale.district_code or None,
                        "property_id": sale.property_id or None,
                        "dealing_id": sale.dealing_id,
                        "contract_date": sale.contract_date.isoformat()
                        if sale.contract_date
                        else None,
                        "settlement_date": sale.settlement_date.isoformat()
                        if sale.settlement_date
                        else None,
                        "price_aud": sale.price_aud,
                        "area_original": str(sale.area_original)
                        if sale.area_original is not None
                        else None,
                        "area_unit": sale.area_unit,
                        "area_square_metres": str(sale.area_square_metres)
                        if sale.area_square_metres is not None
                        else None,
                        "property_ref": None,
                        "match_tier": "MISS",
                        "match_confidence": "0",
                        "geographic_precision": "unmatched",
                    }
                )
            remaining = _record_limit(task, scope) - len(records)
        document = _live_canonical_document("psi-sales", source_urls, records)
        source = document["source"]
        assert isinstance(source, dict)
        source["cached_source_years"] = cached_years
        return document, records

    def _psi_archive(self, year: int) -> Path | None:
        root = self.settings.psi_archive_root
        if root is None:
            return None
        candidate = root / f"{year}.zip"
        return candidate if candidate.is_file() else None

    def _live_gnaf(
        self, task: dict[str, Any], scope: dict[str, object]
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        source_url, declared_crs = self._gnaf_source()
        maximum_bytes = min(int(task.get("max_bytes", 2_500_000_000)), 2_500_000_000)
        if self.settings.gnaf_archive_path and self.settings.gnaf_archive_path.is_file():
            stream = self.settings.gnaf_archive_path.open("rb")
            try:
                raw_artifact = self.artifacts.put(
                    self._heartbeat_chunks(task, iter(lambda: stream.read(1024 * 1024), b"")),
                    max_bytes=maximum_bytes,
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
                    max_bytes=maximum_bytes,
                    media_type="application/zip",
                )
        raw_path = self.artifacts.verified_path(
            raw_artifact.storage_key,
            raw_artifact.sha256,
            expected_bytes=raw_artifact.bytes,
            max_bytes=maximum_bytes,
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
        parsed = parse_gnaf_archive_path(
            raw_path,
            declared_crs=declared_crs,
            maximum_records=_record_limit(task, scope),
            localities=localities,
        )
        records: list[dict[str, object]] = [
            {
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
            for item in parsed
        ]
        document = _live_canonical_document("gnaf-nsw", source_url, records)
        document["source"] = {
            "source_url": source_url,
            "real_source": True,
            "coordinate_reference_system": declared_crs,
            "raw_content_sha256": raw_artifact.sha256,
            "raw_bytes": raw_artifact.bytes,
            "raw_storage_key": raw_artifact.storage_key,
        }
        return document, records

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
        last_heartbeat = time.monotonic()
        interval = max(1.0, self.settings.lease_seconds / 3)
        for chunk in chunks:
            if time.monotonic() - last_heartbeat >= interval:
                self._heartbeat(str(task["id"]), str(task["lease_token"]))
                last_heartbeat = time.monotonic()
            yield chunk

    def _download_registered(self, url: str, *, maximum_bytes: int) -> bytes:
        parsed = urlparse(url)
        allowed_hosts = {
            "data.nsw.gov.au",
            "bocsarblob.blob.core.windows.net",
            "www.valuergeneral.nsw.gov.au",
        }
        if parsed.scheme != "https" or parsed.hostname not in allowed_hosts:
            raise RuntimeError("Source URL is outside the registered HTTPS allowlist")
        chunks: list[bytes] = []
        total = 0
        with self.client.stream(
            "GET", url, headers={"Accept": "*/*", "User-Agent": "PropertyScope/1.0"}
        ) as response:
            response.raise_for_status()
            media_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if media_type not in {
                "text/csv",
                "application/csv",
                "application/octet-stream",
                "application/zip",
                "application/x-zip-compressed",
            }:
                raise RuntimeError("Registered source returned an unexpected media type")
            declared = response.headers.get("content-length")
            if declared and int(declared) > maximum_bytes:
                raise RuntimeError("Registered source exceeds the configured byte limit")
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > maximum_bytes:
                    raise RuntimeError("Registered source exceeds the configured byte limit")
                chunks.append(chunk)
        return b"".join(chunks)

    def _download_psi_archive(self, url: str, *, maximum_bytes: int) -> bytes:
        try:
            return self._download_registered(url, maximum_bytes=maximum_bytes)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 403:
                raise
        # The publisher's current Cloudflare policy serves the public annual files via
        # bounded Range requests while intermittently rejecting an ordinary full GET.
        chunks: list[bytes] = []
        offset = 0
        expected_total: int | None = None
        chunk_size = 256 * 1024
        while expected_total is None or offset < expected_total:
            end = min(offset + chunk_size - 1, maximum_bytes - 1)
            response: httpx.Response | None = None
            for _attempt in range(4):
                candidate = self.client.get(
                    url,
                    headers={
                        "Accept": "application/zip",
                        "Range": f"bytes={offset}-{end}",
                        "User-Agent": "PropertyScope/1.0",
                    },
                )
                if candidate.status_code == 206:
                    response = candidate
                    break
                if candidate.status_code != 403:
                    candidate.raise_for_status()
            if response is None:
                raise RuntimeError("PSI source rejected bounded range acquisition")
            match = re.fullmatch(
                r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", "")
            )
            if match is None or int(match.group(1)) != offset:
                raise RuntimeError("PSI source returned an invalid content range")
            range_end, total = int(match.group(2)), int(match.group(3))
            invalid_length = len(response.content) != range_end - offset + 1
            if total > maximum_bytes or range_end >= total or invalid_length:
                raise RuntimeError("PSI source range exceeds the registered byte limit")
            if expected_total is not None and total != expected_total:
                raise RuntimeError("PSI source changed during ranged acquisition")
            expected_total = total
            chunks.append(response.content)
            offset = range_end + 1
        return b"".join(chunks)

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


def _record_limit(task: dict[str, Any], scope: dict[str, object]) -> int:
    requested = scope.get("maximum_records", task.get("max_rows", LIVE_CANONICAL_RECORD_LIMIT))
    if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
        raise RuntimeError("maximum_records must be a positive integer")
    return min(requested, int(task.get("max_rows", requested)), LIVE_CANONICAL_RECORD_LIMIT)


def _month_scope(value: object) -> date | None:
    if value in {None, ""}:
        return None
    try:
        return date.fromisoformat(f"{value}-01" if len(str(value)) == 7 else str(value))
    except ValueError as exc:
        raise RuntimeError("Month scope must use YYYY-MM") from exc


def _source_object(logical_key: str, url: str, media_type: str) -> dict[str, object]:
    return {
        "logical_key": logical_key,
        "source_url": url,
        "media_type": media_type,
        "complete": True,
    }


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
