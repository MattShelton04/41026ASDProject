"""Opt-in real HTTP/PostGIS reference pipeline, mocking only publisher acquisition.

Supply PROPERTYSCOPE_TEST_POSTGRES_URL for a disposable administrator database.
Each test migrates and drops its own uniquely named database. No retained stack
database or publisher endpoint is used by these tests.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx
import psycopg
import pytest
from flask import Flask
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from werkzeug.serving import make_server

import propertyscope_data_platform.runner as runner_module
from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import DataStoreClient
from propertyscope_data_platform.reference_catalog import REFERENCE_PROFILES
from propertyscope_data_platform.runner import AcquisitionRunner, RunnerSettings
from propertyscope_data_store.app import create_app as create_database_app
from propertyscope_data_store.configuration import StoreSettings
from propertyscope_data_store.loader import DatabaseLoader
from propertyscope_data_store.repository import PropertyScopeStore
from propertyscope_data_store.runtime_registry import load_runtime_registry

ADMIN_URL = os.getenv("PROPERTYSCOPE_TEST_POSTGRES_URL", "").strip()
ROOT = Path(__file__).parents[2]
BASE = "/api/data-platform/v1"
TOKEN = "reference-e2e-internal-token"
RUNNER_TOKEN = "reference-e2e-runner-token"
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="requires disposable PostGIS administrator URL"
)


@contextmanager
def _serve(app: Flask) -> Iterator[str]:
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@dataclass
class _Platform:
    store: PropertyScopeStore
    client: httpx.Client
    runner: AcquisitionRunner
    artifacts: Path
    database_origin: str

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self.client.request(method, BASE + path, **kwargs)
        assert response.status_code < 400, response.text
        return response

    def job(self, profile: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            result = connection.execute(
                "SELECT * FROM ops.job_definition WHERE profile_key=%s", (profile,)
            ).fetchone()
        assert result is not None
        return cast(dict[str, Any], result)

    def start(self, profile: str) -> str:
        job = self.job(profile)
        plan = self.request("POST", f"/jobs/{job['id']}/plans", json={}).json()
        assert plan["valid"] and plan["accepted_watermark_unchanged_until_publication"]
        key = uuid.uuid4().hex
        response = self.request(
            "POST", f"/jobs/{job['id']}/runs", json={}, headers={"Idempotency-Key": key}
        )
        replay = self.request(
            "POST", f"/jobs/{job['id']}/runs", json={}, headers={"Idempotency-Key": key}
        )
        assert response.json()["run"]["id"] == replay.json()["run"]["id"]
        return str(response.json()["run"]["id"])

    def finish(self, run_id: str, expected: str = "succeeded") -> dict[str, Any]:
        for _ in range(12):
            envelope = self.request("GET", f"/ingestion-runs/{run_id}").json()
            run = envelope["run"]
            if run["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                assert run["status"] == expected, envelope
                return cast(dict[str, Any], run)
            assert self.runner.run_once(include_publications=False)
        pytest.fail(f"reference run did not reach a terminal state: {run_id}")

    def release_for(self, run_id: str) -> dict[str, Any]:
        with self.store.connection() as connection:
            row = connection.execute(
                "SELECT id FROM ops.dataset_release WHERE ingestion_run_id=%s", (run_id,)
            ).fetchone()
        assert row is not None
        return cast(
            dict[str, Any], self.request("GET", f"/dataset-releases/{row['id']}").json()["release"]
        )

    def publish(self, release: dict[str, Any]) -> dict[str, Any]:
        release_id = release["id"]
        if release["status"] != "awaiting_review":
            self.request(
                "POST",
                f"/dataset-releases/{release_id}/submit-review",
                json={"version": release["version"], "comment": "Synthetic reference E2E review"},
            )
        release = self.request("GET", f"/dataset-releases/{release_id}").json()["release"]
        key = uuid.uuid4().hex
        body = {
            "approved": True,
            "version": release["version"],
            "comment": "Approve synthetic reference E2E data",
        }
        publication = self.request(
            "POST",
            f"/dataset-releases/{release_id}/publish",
            json=body,
            headers={"Idempotency-Key": key},
        )
        assert publication.status_code in (200, 202)
        for _ in range(100):
            release = self.request("GET", f"/dataset-releases/{release_id}").json()["release"]
            if release["status"] == "accepted":
                break
            time.sleep(0.05)
        assert release["status"] == "accepted", release
        replay = self.request(
            "POST",
            f"/dataset-releases/{release_id}/publish",
            json=body,
            headers={"Idempotency-Key": key},
        )
        assert replay.json()["replayed"] is True
        return release


def _records(profile: str) -> list[dict[str, Any]]:
    valid = {
        "type": "Polygon",
        "coordinates": [[[151, -34], [151.01, -34], [151.01, -33.99], [151, -33.99], [151, -34]]],
    }
    invalid = {
        "type": "Polygon",
        "coordinates": [[[151, -34], [151.01, -33.99], [151, -33.99], [151.01, -34], [151, -34]]],
    }
    return [
        {
            "record_id": f"synthetic:{index}",
            "layer": "synthetic-reference",
            "name": None,
            "geometry": geometry,
            "attributes": {
                "publisher_value": "retained",
                "aep_percent": None,
                "absence_interpretation": "unknown",
            },
            "source_url": "https://example.nsw.gov.au/synthetic-publisher",
            "source_crs": "EPSG:7844",
            "source_updated_at": "2026-09-13T00:00:00+00:00",
            "valid_from": None,
            "valid_to": None,
        }
        for index, geometry in enumerate((valid, invalid, None), 1)
    ]


@pytest.fixture
def platform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Platform]:
    database = f"propertyscope_reference_e2e_{uuid.uuid4().hex}"
    values = conninfo_to_dict(ADMIN_URL)
    values["dbname"] = database
    database_url = make_conninfo(**cast(Any, values))
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    store = PropertyScopeStore(
        database_url, runtime_registry=load_runtime_registry(ROOT / "config/job-profiles")
    )
    try:
        store.initialize()
        monkeypatch.setenv("PROPERTYSCOPE_RUNNER_TOKEN", RUNNER_TOKEN)
        monkeypatch.setenv("PROPERTYSCOPE_INTERNAL_TOKEN", TOKEN)
        monkeypatch.setattr(
            runner_module,
            "discover_reference_objects",
            lambda profile, client: [
                {
                    "logical_key": "synthetic-reference",
                    "url": "https://example.nsw.gov.au/synthetic-publisher",
                    "media_type": "application/geo+json",
                    "complete": True,
                    "count": 3,
                    "coverage": {"kind": "synthetic-test-only"},
                    "source_crs": "EPSG:7844",
                }
            ],
        )
        monkeypatch.setattr(
            runner_module,
            "iter_reference_records",
            lambda profile, client, objects: iter(_records(profile)),
        )
        db_app = create_database_app(
            StoreSettings(database_url, tmp_path, TOKEN, auto_migrate=False), store=store
        )
        with _serve(db_app) as db_origin, httpx.Client(trust_env=False, timeout=10) as db_http:
            backend = create_app(
                store_client=DataStoreClient(db_origin, TOKEN, client=db_http),
                feature_root=ROOT,
                artifact_root=tmp_path,
            )
            with (
                _serve(backend) as origin,
                httpx.Client(base_url=origin, trust_env=False, timeout=20) as client,
                httpx.Client(trust_env=False, timeout=20) as runner_http,
            ):
                runner = AcquisitionRunner(
                    RunnerSettings(
                        origin,
                        RUNNER_TOKEN,
                        tmp_path,
                        "reference-e2e-runner",
                        0.01,
                        30,
                        release_projection_workers=0,
                    ),
                    client=runner_http,
                )
                loader = DatabaseLoader(
                    store,
                    tmp_path,
                    worker_id="reference-e2e-loader",
                    disk_reserve_bytes=0,
                    database_capacity_bytes=8 * 1024**3,
                    temp_file_limit_kib=64 * 1024,
                )
                thread = threading.Thread(target=loader.run_forever, daemon=True)
                thread.start()
                try:
                    yield _Platform(store, client, runner, tmp_path, db_origin)
                finally:
                    loader.stop_event.set()
                    thread.join(timeout=5)
    finally:
        store.close()
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname=%s AND pid<>pg_backend_pid()",
                (database,),
            )
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database)))


@pytest.mark.parametrize("profile", sorted(REFERENCE_PROFILES))
def test_registered_reference_profile_complete_http_lifecycle(
    platform: _Platform, profile: str
) -> None:
    run_id = platform.start(profile)
    platform.finish(run_id)
    release = platform.release_for(run_id)
    assert release["record_count"] == 3
    assert release["target_feature"] == "feature-1"
    preview = platform.request("GET", f"/dataset-releases/{release['id']}/records").json()
    assert len(preview["items"]) == 3
    assert {row["geometry_status"] for row in preview["items"]} == {
        "valid",
        "invalid",
        "not_provided",
    }
    release = platform.publish(release)
    with platform.store.connection() as connection:
        pointer = connection.execute(
            "SELECT dataset_release_id FROM serving.accepted_generation WHERE dataset_id=%s",
            (profile,),
        ).fetchone()
        assert pointer is not None
        assert str(pointer["dataset_release_id"]) == str(release["id"])
        count = connection.execute(
            "SELECT count(*) AS n FROM ops.consumer_import_operation WHERE dataset_release_id=%s",
            (release["id"],),
        ).fetchone()
        assert count is not None and count["n"] == 0
    download = platform.client.get(BASE + f"/dataset-releases/{release['id']}/artifact")
    assert download.status_code == 200, download.text
    assert hashlib.sha256(download.content).hexdigest() == release["content_sha256"]
    records = [json.loads(line) for line in gzip.decompress(download.content).splitlines()]
    assert len(records) == 3
    assert records[2]["geometry"] is None
    assert all(row["attributes"]["absence_interpretation"] == "unknown" for row in records)


def test_explicitly_restricted_reference_release_blocks_download(platform: _Platform) -> None:
    profile = "nsw-cadastre"
    with platform.store.connection() as connection:
        connection.execute(
            "UPDATE ops.source_definition SET redistribution_policy='licence-controlled' "
            "WHERE id=%s",
            (platform.job(profile)["source_definition_id"],),
        )
        connection.commit()
    run_id = platform.start(profile)
    platform.finish(run_id)
    release = platform.publish(platform.release_for(run_id))
    download = platform.client.get(BASE + f"/dataset-releases/{release['id']}/artifact")
    assert download.status_code == 403


@pytest.mark.parametrize("failure", ["duplicate", "truncated", "malformed-geometry", "nonfinite"])
def test_reference_failure_rolls_back_candidate_and_preserves_predecessor(
    platform: _Platform, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    profile = "nsw-flood-planning"
    previous_run = platform.start(profile)
    platform.finish(previous_run)
    previous = platform.publish(platform.release_for(previous_run))

    def broken_publisher(
        profile: str, client: httpx.Client, objects: list[dict[str, Any]]
    ) -> Iterator[dict[str, Any]]:
        records = _records(profile)
        if failure == "duplicate":
            yield records[0]
            yield records[0]
        elif failure == "truncated":
            yield records[0]
            raise ValueError("Publisher pagination was truncated before the declared count")
        elif failure == "nonfinite":
            records[0]["attributes"]["FSR"] = float("nan")
            yield records[0]
        else:
            yield records[0]
            records[1]["geometry"] = {"type": "Point", "coordinates": [151, 999]}
            yield records[1]

    monkeypatch.setattr(runner_module, "iter_reference_records", broken_publisher)
    failed_run = platform.start(profile)
    platform.finish(failed_run, expected="failed")
    with platform.store.connection() as connection:
        pointer = connection.execute(
            "SELECT dataset_release_id FROM serving.accepted_generation WHERE dataset_id=%s",
            (profile,),
        ).fetchone()
        assert pointer is not None
        assert str(pointer["dataset_release_id"]) == str(previous["id"])
        count = connection.execute(
            "SELECT count(*) AS n FROM warehouse.reference_feature WHERE ingestion_run_id=%s",
            (failed_run,),
        ).fetchone()
        assert count is not None and count["n"] == 0
    retained = platform.request("GET", f"/dataset-releases/{previous['id']}/artifact")
    assert hashlib.sha256(retained.content).hexdigest() == previous["content_sha256"]


def test_reference_cached_reprocess_preserves_facts_without_publisher_reads(
    platform: _Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = "nsw-flood-planning"
    original_run = platform.start(profile)
    platform.finish(original_run)
    original = platform.publish(platform.release_for(original_run))

    def forbidden_publisher(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("Cached reprocessing contacted the external publisher boundary")

    monkeypatch.setattr(runner_module, "discover_reference_objects", forbidden_publisher)
    monkeypatch.setattr(runner_module, "iter_reference_records", forbidden_publisher)
    replay = platform.request(
        "POST",
        f"/ingestion-runs/{original_run}/reprocess-cached",
        json={},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    ).json()["run"]
    platform.finish(replay["id"])
    replacement = platform.release_for(replay["id"])
    assert replacement["record_count"] == original["record_count"]
    first = platform.request("GET", f"/dataset-releases/{original['id']}/records").json()["items"]
    second = platform.request("GET", f"/dataset-releases/{replacement['id']}/records").json()[
        "items"
    ]
    assert first == second
    with platform.store.connection() as connection:
        pointer = connection.execute(
            "SELECT dataset_release_id FROM serving.accepted_generation WHERE dataset_id=%s",
            (profile,),
        ).fetchone()
    assert pointer is not None
    assert str(pointer["dataset_release_id"]) == str(original["id"])
    platform.publish(replacement)
    assert (
        platform.request("GET", f"/dataset-releases/{original['id']}").json()["release"]["status"]
        == "superseded"
    )


def test_concurrent_jobs_finish_while_another_publisher_is_blocked(
    platform: _Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real task leases and serial loader allow unrelated jobs to make progress."""
    from dataclasses import replace

    blocked, release_publisher = threading.Event(), threading.Event()

    def publisher(
        profile: str, client: httpx.Client, objects: list[dict[str, Any]]
    ) -> Iterator[dict[str, Any]]:
        if profile == "nsw-flood-planning":
            blocked.set()
            assert release_publisher.wait(30), "unrelated job was starved"
        yield from _records(profile)

    monkeypatch.setattr(runner_module, "iter_reference_records", publisher)
    slow = platform.start("nsw-flood-planning")
    fast = platform.start("abs-cpi")
    platform.runner.settings = replace(platform.runner.settings, acquisition_workers=2)
    worker = threading.Thread(target=platform.runner.run_forever, daemon=True)
    worker.start()
    try:
        assert blocked.wait(10)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = platform.request("GET", f"/ingestion-runs/{fast}").json()["run"]["status"]
            if state == "succeeded":
                break
            time.sleep(0.05)
        assert state == "succeeded"
        assert not release_publisher.is_set()
        release_publisher.set()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            state = platform.request("GET", f"/ingestion-runs/{slow}").json()["run"]["status"]
            if state == "succeeded":
                break
            time.sleep(0.05)
        assert state == "succeeded"
        assert platform.release_for(fast)["record_count"] == 3
        assert platform.release_for(slow)["record_count"] == 3
    finally:
        release_publisher.set()
        platform.runner.stop()
        worker.join(timeout=5)
        assert not worker.is_alive()


def test_large_reference_discovery_snapshot_survives_both_http_boundaries(
    platform: _Platform, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = runner_module.discover_reference_objects

    def large_snapshot(profile: str, client: httpx.Client) -> list[dict[str, Any]]:
        objects = original(profile, client)
        objects[0]["schema"] = [{"name": "EPI_NAME", "domain": "x" * 300_000}]
        return objects

    monkeypatch.setattr(runner_module, "discover_reference_objects", large_snapshot)
    run_id = platform.start("nsw-planning-controls")
    run = platform.finish(run_id)
    assert len(run["source_snapshot_json"]["objects"][0]["schema"][0]["domain"]) == 300_000
    assert platform.release_for(run_id)["record_count"] == 3


def test_reference_snapshot_limit_remains_bounded_on_both_services(platform: _Platform) -> None:
    # Authenticated artifact registration has a larger, still finite ceiling;
    # ordinary metadata CRUD keeps its smaller request-size limit.
    oversized = {"padding": "x" * (2 * 1024 * 1024 + 1)}
    run_id = platform.start("nsw-flood-planning")
    with platform.store.connection() as connection:
        task = connection.execute(
            "SELECT id FROM ops.run_task WHERE ingestion_run_id=%s ORDER BY logical_key LIMIT 1",
            (run_id,),
        ).fetchone()
    assert task is not None
    response = platform.client.post(
        f"/internal/data-platform/v1/worker/tasks/{task['id']}/artifacts",
        headers={"X-PropertyScope-Runner-Token": RUNNER_TOKEN},
        json=oversized,
    )
    assert response.status_code == 413
    with httpx.Client(trust_env=False) as client:
        response = client.post(
            platform.database_origin
            + f"/internal/data-platform/v1/worker/tasks/{task['id']}/artifacts",
            headers={"X-PropertyScope-Internal-Token": TOKEN},
            json=oversized,
        )
    assert response.status_code == 413
