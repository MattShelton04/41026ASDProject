"""Capture live feature HTTP and owning-store evidence without exporting user records.

Features 1 and 4 create uniquely labelled audit records and remove only those records in a
finally block. Other features use read-only owning database HTTP count routes.
This command neither starts services nor acquires/publishes data or calls a model provider.

Run against an existing stack with local Docker Compose access. Internal database credentials
are read inside each owning container; no credential argument or OpenAI key is needed.
The JSON contains allowlisted HTTP observations, the HEAD software SHA and a tracked-files
dirty flag. Commit the software first, then capture; untracked output files do not set that flag.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.devtools.config import COMPOSE_FILES, PROFILES, REPOSITORY_ROOT


@dataclass(frozen=True)
class Feature:
    key: str
    port: int
    api_path: str
    database_service: str
    database_port: int
    database_path: str


FEATURES = (
    Feature(
        "student-1-propertyscope-data-platform",
        5200,
        "/api/data-platform/v1/sources?limit=10",
        "f1-db-api",
        5202,
        "/health/ready",
    ),
    Feature(
        "student-2-market-intelligence",
        5300,
        "/api/market-intelligence/v1/market-cases?limit=10",
        "f2-db-api",
        5302,
        "/internal/market-intelligence/v1/seed-report",
    ),
    Feature(
        "student-3-suburb-analytics",
        5600,
        "/api/suburb-analytics/v1/suburbs?limit=10",
        "f3-database",
        5302,
        "/health/ready",
    ),
    Feature(
        "student-4-due-diligence",
        5400,
        "/api/due-diligence/v1/site-reviews?limit=10",
        "f4-db-api",
        5402,
        "/health/ready",
    ),
    Feature(
        "student-5-buyer-journey",
        5500,
        "/api/buyer-workspaces/v1/buyer-cases?page_size=10",
        "f5-db-api",
        5502,
        "/internal/buyer-workspaces/v1/seed-report",
    ),
)

OWNER_HTTP_PROBE = """
import json, os, sys, urllib.request
request = urllib.request.Request(
    'http://127.0.0.1:' + sys.argv[1] + sys.argv[2],
    headers={'X-PropertyScope-Internal-Token': os.environ.get('PROPERTYSCOPE_INTERNAL_TOKEN', '')},
)
with urllib.request.urlopen(request, timeout=45) as response:
    value = json.load(response)
    print(json.dumps({'http_status': response.status, 'status': value.get('status'),
                      'tables': value.get('tables', {})}))
"""

DatabaseProbe = Callable[[Feature, str], dict[str, object]]
SHARED_HOME_URL = "http://127.0.0.1:5100/"


def database_probe(feature: Feature, project: str) -> dict[str, object]:
    """Call only the selected owning database API inside its existing container."""
    command = ["docker", "compose", "--project-name", project]
    for filename in COMPOSE_FILES:
        command.extend(("--file", filename))
    for profile in PROFILES:
        command.extend(("--profile", profile))
    command.extend(
        (
            "exec",
            "-T",
            feature.database_service,
            "python",
            "-c",
            OWNER_HTTP_PROBE,
            str(feature.database_port),
            feature.database_path,
        )
    )
    try:
        completed = subprocess.run(  # noqa: S603 - argv built by this script, no shell
            command, cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=True, timeout=60
        )
        body = json.loads(completed.stdout)
        if not isinstance(body, dict):
            raise ValueError("invalid owner response")
        return body
    except (OSError, subprocess.SubprocessError, ValueError):
        return {"passed": False, "error": "Owning database HTTP observation unavailable"}


def _tables(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        name: count
        for name, count in value.items()
        if isinstance(name, str)
        and isinstance(count, int)
        and not isinstance(count, bool)
        and count >= 0
    }


def _request_observation(
    client: httpx.Client, url: str, *, frontend: bool = False
) -> dict[str, object]:
    response = client.get(url)
    observation: dict[str, object] = {"url": url, "http_status": response.status_code}
    if frontend:
        observation["content_type"] = response.headers.get("content-type", "").split(";", 1)[0]
        title = re.search(r"<title[^>]*>(.*?)</title>", response.text, re.IGNORECASE | re.DOTALL)
        observation["title"] = title.group(1).strip()[:200] if title else None
        observation["passed"] = (
            response.status_code == 200 and observation["content_type"] == "text/html"
        )
    else:
        body = response.json()
        items = body.get("items") if isinstance(body, dict) else None
        observation["returned_items"] = len(items) if isinstance(items, list) else None
        observation["passed"] = (
            response.status_code == 200 and isinstance(items, list) and bool(items)
        )
    return observation


def _transient_crud(
    client: httpx.Client, base_url: str, *, source_definition: bool = False
) -> dict[str, object]:
    """Prove persisted CRUD for a new audit record without altering an existing one."""
    path = (
        "/api/data-platform/v1/sources"
        if source_definition
        else "/api/due-diligence/v1/site-reviews"
    )
    label_field = "name" if source_definition else "title"
    marker = f"Release 1 transient integration audit {uuid4()}"
    stages: list[dict[str, object]] = []
    record_id: str | None = None
    outcome: dict[str, object] = {
        "scope": "Only a uniquely labelled record created by this capture",
        "stages": stages,
        "passed": False,
        "cleanup_passed": False,
    }
    try:
        existing = client.get(base_url + path).json()
        items = existing.get("items", []) if isinstance(existing, dict) else []
        previous_ids = {item.get("id") for item in items if isinstance(item, dict)}
        source = next(
            (
                item
                for item in items
                if isinstance(item, dict)
                and isinstance(item.get("property_ref"), str)
                and isinstance(item.get("address_display"), str)
            ),
            None,
        )
        if source is None and not source_definition:
            raise ValueError("no existing property reference available")
        if source_definition:
            create_payload: dict[str, object] = {
                "name": marker,
                "publisher": "Release validation probe",
                "source_url": "https://example.test/no-acquisition",
                "adapter_key": "fixture-source",
                "cadence": "manual",
                "licence_id": "cc0-1.0",
                "licence_url": "https://example.test/licence",
                "redistribution_policy": "metadata-only",
                "target_features": ["feature-1"],
                "status": "draft",
                "notes": "Transient CRUD probe; no acquisition or publication.",
            }
        else:
            if source is None:
                raise RuntimeError("no source record is available for the CRUD probe")
            create_payload = {
                "property_ref": source["property_ref"],
                "address_display": source["address_display"],
                "title": marker,
                "notes": "Temporary release evidence probe; removed after validation.",
            }
        created = client.post(base_url + path, json=create_payload)
        stages.append({"operation": "create", "http_status": created.status_code})
        body = created.json()
        if source_definition and isinstance(body, dict):
            body = body.get("source")
        if created.status_code != 201 or not isinstance(body, dict):
            raise ValueError("audit record creation failed")
        candidate = str(body.get("id", ""))
        UUID(candidate)
        if candidate in previous_ids or body.get(label_field) != marker:
            raise ValueError("created identity is not an owned audit record")
        record_id = candidate
        outcome["record_id"] = record_id
        if source_definition and (
            not isinstance(body.get("version"), int)
            or isinstance(body["version"], bool)
            or body["version"] < 1
        ):
            raise ValueError("created source version is invalid")
        update = (
            {**create_payload, "name": marker + " updated", "version": body["version"]}
            if source_definition
            else {"title": marker + " updated"}
        )
        for operation, method, payload in (
            ("read-created", "GET", None),
            ("update", "PUT", update),
            ("read-updated", "GET", None),
        ):
            response = client.request(method, f"{base_url}{path}/{record_id}", json=payload)
            observed = response.json()
            if source_definition and isinstance(observed, dict):
                observed = observed.get("source")
            expected_title = marker if operation == "read-created" else marker + " updated"
            matched = (
                response.status_code == 200
                and isinstance(observed, dict)
                and observed.get("id") == record_id
                and observed.get(label_field) == expected_title
            )
            stages.append(
                {
                    "operation": operation,
                    "http_status": response.status_code,
                    "identity_and_value_match": matched,
                }
            )
            if not matched:
                raise ValueError("persisted audit record value differs")
        outcome["passed"] = True
    except (httpx.HTTPError, ValueError, StopIteration):
        outcome["error"] = "Transient public CRUD validation failed"
    finally:
        if record_id is not None:
            try:
                removed = client.delete(f"{base_url}{path}/{record_id}")
                missing = client.get(f"{base_url}{path}/{record_id}")
                stages.extend(
                    (
                        {"operation": "delete", "http_status": removed.status_code},
                        {"operation": "read-after-delete", "http_status": missing.status_code},
                    )
                )
                outcome["cleanup_passed"] = (
                    removed.status_code == (204 if source_definition else 200)
                    and missing.status_code == 404
                )
            except httpx.HTTPError:
                outcome["cleanup_passed"] = False
            outcome["passed"] = outcome["passed"] is True and outcome["cleanup_passed"] is True
    return outcome


def capture(
    *, project: str, client: httpx.Client, owner_probe: DatabaseProbe = database_probe
) -> dict[str, object]:
    """Collect allowlisted observations; raw records, headers and exceptions are excluded."""
    try:
        shared_home = _request_observation(client, SHARED_HOME_URL, frontend=True)
    except (httpx.HTTPError, ValueError):
        shared_home = {
            "url": SHARED_HOME_URL,
            "passed": False,
            "error": "Shared home HTTP observation unavailable or malformed",
        }
    observations: list[dict[str, object]] = []
    for feature in FEATURES:
        origin = f"http://127.0.0.1:{feature.port}"
        observed: dict[str, object] = {"feature_key": feature.key, "passed": False}
        observations.append(observed)
        try:
            frontend = _request_observation(client, origin + "/", frontend=True)
            api = _request_observation(client, origin + feature.api_path)
            raw_database = owner_probe(feature, project)
            counts = _tables(raw_database.get("tables"))
            database: dict[str, object] = {
                "service": feature.database_service,
                "interface": "Owning database service HTTP API, via selected Compose project",
                "path": feature.database_path,
                "http_status": raw_database.get("http_status"),
                "passed": raw_database.get("http_status") == 200,
            }
            if counts:
                database["tables"] = counts
                database["minimum_observed_table_count"] = min(counts.values())
            elif feature.port not in {5200, 5400}:
                database["passed"] = False
            observed.update(frontend=frontend, api=api, database=database)
            persistence_passed = database["passed"] is True
            if feature.port in {5200, 5400}:
                crud = _transient_crud(client, origin, source_definition=feature.port == 5200)
                observed["transient_crud"] = crud
                persistence_passed = persistence_passed and crud["passed"] is True
            observed["passed"] = (
                frontend["passed"] is True and api["passed"] is True and persistence_passed
            )
        except (httpx.HTTPError, ValueError):
            observed["error"] = "Feature HTTP observation unavailable or malformed"
    return {
        "schema_version": "1.0",
        "captured_at": datetime.now(UTC).isoformat(),
        "compose_project": project,
        "transport": "live-local-feature-and-owning-store-http",
        "evidence_boundary": "Actual HTTP operations on the existing developer stack. "
        "Seeded demonstration records may remain; counts do not prove official data coverage. "
        "No model, browser interaction, container restart or source acquisition was exercised.",
        "passed": shared_home["passed"] is True
        and all(item["passed"] is True for item in observations),
        "shared_home": shared_home,
        "features": observations,
    }


def _software_provenance() -> dict[str, object]:
    """Project git metadata to a SHA and boolean; never export status filenames."""
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],  # noqa: S607 - git is resolved from the developer PATH
        cwd=REPOSITORY_ROOT,
        text=True,
    ).strip()
    dirty = bool(
        subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"],  # noqa: S607 - git is resolved from the developer PATH
            cwd=REPOSITORY_ROOT,
            text=True,
        ).strip()
    )
    return {"software_sha": sha, "tracked_worktree_dirty": dirty}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        required=True,
        help="Existing Compose project; its owning services must be running",
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Allowlisted JSON evidence destination"
    )
    arguments = parser.parse_args(argv)
    provenance = _software_provenance()
    with httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as client:
        evidence = capture(project=arguments.project, client=client)
    evidence.update(provenance)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(
        f"Live feature operations: {'PASS' if evidence['passed'] else 'FAIL'}; {arguments.output}"
    )
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
