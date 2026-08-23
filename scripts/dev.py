"""Cross-platform Docker Compose workflow for the local integration stack."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Mapping, Sequence
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from zipfile import BadZipFile, ZipFile

import httpx
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.integration-test.yml",
    "docker-compose.dev.yml",
)
FULL_DATA_COMPOSE_FILE = "docker-compose.full-data.yml"
PROFILES = ("release-0", "integration-test")
APPLICATION_SERVICES = (
    "propertyscope-shared-frontend",
    "ai-mode",
    "integration-test-feature-database",
    "integration-test-feature-backend",
    "integration-test-feature-frontend",
    "propertyscope-database-api",
    "propertyscope-database-loader",
    "propertyscope-backend",
    "propertyscope-runner",
    "propertyscope-frontend",
)
BUILD_SERVICES = APPLICATION_SERVICES
FULL_DATA_PROJECT_NAME = "41026-asd-propertyscope-full-data"
DEFAULT_PROJECT_NAME = "41026-asd-project"
RUNTIME_DIRECTORY = REPOSITORY_ROOT / ".propertyscope-runtime"
OFFLINE_OPENAI_CREDENTIAL = "offline-local-development-only"
SUPPORTED_LLM_PROVIDERS = frozenset({"gemini", "openai"})
PROPERTYSCOPE_API_URL = "http://127.0.0.1:5200/api/data-platform/v1"
JOB_PROFILE_DIRECTORY = REPOSITORY_ROOT / "student-1" / "config" / "job-profiles"
COLLECTION_JOBS = (
    "fixture-property",
    "schools-master",
    "bocsar-crime",
    "gnaf-nsw",
    "psi-sales",
)
TERMINAL_COLLECTION_STATES = frozenset({"succeeded", "failed", "cancelled"})
HOST_PORTS = {
    "propertyscope-shared-frontend": ("PROPERTYSCOPE_SHARED_PORT", 5100),
    "ai-mode": ("AI_MODE_PORT", 5005),
    "integration-test-feature-frontend": ("INTEGRATION_TEST_FEATURE_PORT", 5190),
    "propertyscope-frontend": ("PROPERTYSCOPE_PORT", 5200),
}
UI_FIXTURE_SCENARIOS = (
    "populated",
    "empty",
    "slow",
    "error",
    "partial",
    "long-content",
    "large",
    "validation-error",
)
DEFAULT_UI_FIXTURE_PORT = 5300
PSI_YEARLY_URL = "https://www.valuergeneral.nsw.gov.au/__psi/yearly/{partition}.zip"
PSI_WEEKLY_URL = "https://www.valuergeneral.nsw.gov.au/__psi/weekly/{partition}.zip"
PSI_ARCHIVE_BYTE_LIMIT = 750_000_000


def _compose_command(*arguments: str, full_data: bool = False) -> tuple[str, ...]:
    command = ["docker", "compose"]
    if full_data:
        command.extend(("--project-name", FULL_DATA_PROJECT_NAME))
    for filename in COMPOSE_FILES:
        command.extend(("--file", filename))
    if full_data:
        command.extend(("--file", FULL_DATA_COMPOSE_FILE))
    profiles = (*PROFILES, "full-data") if full_data else PROFILES
    for profile in profiles:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return tuple(command)


def _run(command: Sequence[str], *, environment: Mapping[str, str] | None = None) -> None:
    print(f"> {shlex.join(command)}", flush=True)
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, env=environment)


def _ensure_docker() -> None:
    _run(("docker", "info", "--format", "Docker Engine {{.ServerVersion}} is ready"))


def _resolved_host_ports(services: Sequence[str]) -> dict[str, tuple[str, int]]:
    resolved: dict[str, tuple[str, int]] = {}
    by_port: dict[int, tuple[str, str]] = {}
    for service in services:
        setting = HOST_PORTS.get(service)
        if setting is None:
            continue
        variable, default = setting
        raw_value = os.environ.get(variable, "").strip() or str(default)
        if re.fullmatch(r"[0-9]+", raw_value) is None or not 1 <= int(raw_value) <= 65535:
            raise RuntimeError(f"{variable} must be an integer between 1 and 65535")
        port = int(raw_value)
        if previous := by_port.get(port):
            raise RuntimeError(
                f"Host port {port} is configured for both {previous[0]} ({previous[1]}) and "
                f"{service} ({variable}). Set one environment variable to a different port."
            )
        by_port[port] = (service, variable)
        resolved[service] = (variable, port)
    return resolved


def _ui_fixture_port(argument: int | None) -> int:
    raw_value = (
        str(argument)
        if argument is not None
        else (
            os.environ.get("PROPERTYSCOPE_UI_FIXTURE_PORT", "").strip()
            or str(DEFAULT_UI_FIXTURE_PORT)
        )
    )
    if re.fullmatch(r"[0-9]+", raw_value) is None or not 1 <= int(raw_value) <= 65535:
        raise RuntimeError(
            "PROPERTYSCOPE_UI_FIXTURE_PORT/--port must be an integer between 1 and 65535"
        )
    return int(raw_value)


def _host_port_is_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            listener.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _capture(command: Sequence[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _published_port_owners(port: int) -> tuple[tuple[str, str], ...]:
    container_ids = tuple(
        line.strip()
        for line in _capture(
            ("docker", "ps", "--filter", f"publish={port}", "--format", "{{.ID}}")
        ).splitlines()
        if line.strip()
    )
    owners: list[tuple[str, str]] = []
    for container_id in container_ids:
        output = _capture(
            (
                "docker",
                "inspect",
                "--format",
                "{{json .Config.Labels}}",
                container_id,
            )
        ).strip()
        labels = json.loads(output) if output else {}
        if not isinstance(labels, dict):
            labels = {}
        project = str(labels.get("com.docker.compose.project", ""))
        service = str(labels.get("com.docker.compose.service", container_id))
        owners.append((project, service))
    return tuple(owners)


def _preflight_compose_host_ports(*, services: Sequence[str], full_data: bool) -> None:
    """Reject conflicting host ports before secrets, builds, or container mutation."""
    project = FULL_DATA_PROJECT_NAME if full_data else DEFAULT_PROJECT_NAME
    conflicts: list[str] = []
    for service, (variable, port) in _resolved_host_ports(services).items():
        if _host_port_is_available(port):
            continue
        owners = _published_port_owners(port)
        if owners and all(
            owner_project == project and owner_service == service
            for owner_project, owner_service in owners
        ):
            continue
        owner_text = ", ".join(
            f"Compose project {owner_project!r} service {owner_service!r}"
            for owner_project, owner_service in owners
        )
        if not owner_text:
            owner_text = "a non-Compose host process"
        conflicts.append(f"{service} needs 127.0.0.1:{port} ({variable}); occupied by {owner_text}")
    if conflicts:
        detail = "\n  - ".join(conflicts)
        raise RuntimeError(
            "Compose host-port preflight failed before any build or container change:\n"
            f"  - {detail}\n"
            "Stop the owning process/project or set the named port environment variable."
        )


def _openai_credential(*, offline: bool) -> str:
    """Resolve the configured remote credential or the documented offline placeholder."""
    if offline:
        return OFFLINE_OPENAI_CREDENTIAL
    provider = os.environ.get("AI_MODE_LLM_PROVIDER", "openai").strip().lower()
    if provider not in SUPPORTED_LLM_PROVIDERS:
        raise RuntimeError(
            f"AI_MODE_LLM_PROVIDER must be one of: {', '.join(sorted(SUPPORTED_LLM_PROVIDERS))}"
        )
    variable = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    credential = os.environ.get(variable, "").strip()
    if not credential:
        raise RuntimeError(
            f"{variable} is required for the complete stack when AI_MODE_LLM_PROVIDER={provider}. "
            "Set a real key or pass --offline to run data and non-AI workflows with provider "
            "readiness disabled."
        )
    return credential


def _load_environment_file(path: Path) -> None:
    """Load a small explicit dotenv file without exposing values or overriding the shell."""
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"could not read environment file: {path}") from exc
    if len(content.encode("utf-8")) > 65_536:
        raise RuntimeError(f"environment file is too large: {path}")
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, separator, value = line.partition("=")
        if not separator or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
            raise RuntimeError(f"invalid environment assignment at {path}:{line_number}")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(name, value)


def _runtime_secret_path(*, full_data: bool) -> Path:
    suffix = ".full-data" if full_data else ""
    return RUNTIME_DIRECTORY / f"openai_api_key{suffix}"


def _write_openai_secret(credential: str, *, full_data: bool) -> Path:
    """Materialise a Compose file secret without exposing it in rendered configuration."""
    RUNTIME_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = _runtime_secret_path(full_data=full_data)
    with NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=RUNTIME_DIRECTORY,
        delete=False,
    ) as temporary:
        temporary.write(credential)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, destination)
    return destination


def _remove_openai_secret(*, full_data: bool) -> None:
    _runtime_secret_path(full_data=full_data).unlink(missing_ok=True)
    with suppress(OSError):
        RUNTIME_DIRECTORY.rmdir()


def _psi_cache_years() -> tuple[int, ...]:
    root = REPOSITORY_ROOT / ".propertyscope-source-cache" / "psi"
    if not root.is_dir():
        return ()
    return tuple(
        sorted(int(path.stem) for path in root.glob("[0-9][0-9][0-9][0-9].zip") if path.is_file())
    )


def _psi_cache_weeks() -> tuple[str, ...]:
    weekly = REPOSITORY_ROOT / ".propertyscope-source-cache" / "psi" / "weekly"
    return tuple(
        sorted(
            f"{match.group(1)[:4]}-{match.group(1)[4:6]}-{match.group(1)[6:]}"
            for path in weekly.glob("*.zip")
            if (match := re.fullmatch(r"(\d{8})\.zip", path.name)) is not None
        )
    )


def _current_psi_weeks(today: date | None = None) -> tuple[date, ...]:
    resolved = today or datetime.now(UTC).date()
    cursor = date(resolved.year, 1, 1)
    cursor += timedelta(days=(7 - cursor.weekday()) % 7)
    weeks: list[date] = []
    while cursor <= resolved:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return tuple(weeks)


def _download_psi_archive(client: httpx.Client, url: str) -> bytes:
    """Acquire one official PSI archive, including the publisher's Range-only path."""
    response = client.get(
        url, headers={"Accept": "application/zip", "User-Agent": "PropertyScope/1.0"}
    )
    if response.status_code != 403:
        response.raise_for_status()
        if len(response.content) > PSI_ARCHIVE_BYTE_LIMIT:
            raise RuntimeError("PSI archive exceeds the 750 MB compressed safety limit")
        return response.content
    chunks: list[bytes] = []
    offset = 0
    expected_total: int | None = None
    chunk_size = 4 * 1024 * 1024
    while expected_total is None or offset < expected_total:
        end = min(offset + chunk_size - 1, PSI_ARCHIVE_BYTE_LIMIT - 1)
        ranged = client.get(
            url,
            headers={
                "Accept": "application/zip",
                "Range": f"bytes={offset}-{end}",
                "User-Agent": "PropertyScope/1.0",
            },
        )
        if ranged.status_code != 206:
            ranged.raise_for_status()
            raise RuntimeError("PSI publisher rejected bounded Range acquisition")
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", ranged.headers.get("content-range", ""))
        if match is None or int(match.group(1)) != offset:
            raise RuntimeError("PSI publisher returned an invalid content range")
        range_end, total = int(match.group(2)), int(match.group(3))
        if total > PSI_ARCHIVE_BYTE_LIMIT or len(ranged.content) != range_end - offset + 1:
            raise RuntimeError("PSI archive exceeds the compressed safety limit")
        if expected_total is not None and total != expected_total:
            raise RuntimeError("PSI archive changed during acquisition")
        expected_total = total
        chunks.append(ranged.content)
        offset = range_end + 1
    return b"".join(chunks)


def _sync_psi(*, years: Sequence[int], weeks: Sequence[date]) -> None:
    root = REPOSITORY_ROOT / ".propertyscope-source-cache" / "psi"
    targets = [
        (PSI_YEARLY_URL.format(partition=year), root / f"{year}.zip") for year in sorted(set(years))
    ]
    targets.extend(
        (
            PSI_WEEKLY_URL.format(partition=week.strftime("%Y%m%d")),
            root / "weekly" / f"{week.strftime('%Y%m%d')}.zip",
        )
        for week in sorted(set(weeks))
    )
    if not targets:
        raise RuntimeError("Select --all, --year, --week, or --current-weekly")
    with httpx.Client(timeout=None, follow_redirects=False) as client:
        for url, destination in targets:
            if destination.is_file():
                try:
                    with ZipFile(destination) as archive:
                        archive.testzip()
                    print(
                        f"PSI cache retained: {destination.relative_to(REPOSITORY_ROOT)}",
                        flush=True,
                    )
                    continue
                except BadZipFile:
                    pass
            print(f"PSI source: {url}", flush=True)
            content = _download_psi_archive(client, url)
            try:
                with ZipFile(io.BytesIO(content)) as archive:
                    if not archive.namelist() or archive.testzip() is not None:
                        raise RuntimeError("PSI publisher returned a corrupt ZIP archive")
            except BadZipFile as exc:
                raise RuntimeError("PSI publisher did not return a ZIP archive") from exc
            destination.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(dir=destination.parent, delete=False) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            os.replace(temporary_path, destination)
            print(
                f"PSI cached: {destination.relative_to(REPOSITORY_ROOT)} "
                f"({len(content):,} bytes, sha256 {hashlib.sha256(content).hexdigest()})",
                flush=True,
            )


def _compose_environment(*, full_data: bool, offline: bool) -> Mapping[str, str]:
    credential = _openai_credential(offline=offline)
    environment = os.environ.copy()
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("GEMINI_API_KEY", None)
    secret_path = str(_write_openai_secret(credential, full_data=full_data))
    environment["OPENAI_API_KEY_FILE"] = secret_path
    environment["GEMINI_API_KEY_FILE"] = secret_path
    if offline:
        environment["AI_MODE_REQUIRE_PROVIDER_READY"] = "false"
    if full_data:
        years = _psi_cache_years()
        weeks = _psi_cache_weeks()
        environment.setdefault("PROPERTYSCOPE_PSI_TRANSPORT_ENABLED", "true")
        if years:
            environment.setdefault("PROPERTYSCOPE_PSI_CACHED_YEARS", ",".join(map(str, years)))
        if weeks:
            environment.setdefault("PROPERTYSCOPE_PSI_CACHED_WEEKS", ",".join(weeks))
    return environment


def _up(*, full_data: bool, offline: bool) -> None:
    _openai_credential(offline=offline)
    _ensure_docker()
    _preflight_compose_host_ports(services=APPLICATION_SERVICES, full_data=full_data)
    compose_environment = _compose_environment(full_data=full_data, offline=offline)
    if full_data:
        print(f"Official PSI cache: {', '.join(map(str, _psi_cache_years()))}", flush=True)
    _run(
        _compose_command(
            "up",
            "--build",
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            *APPLICATION_SERVICES,
            full_data=full_data,
        ),
        environment=compose_environment,
    )
    ports = _resolved_host_ports(APPLICATION_SERVICES)
    print(
        f"\nIntegration console: http://localhost:{ports['integration-test-feature-frontend'][1]}"
    )
    print(f"AI-mode health:     http://localhost:{ports['ai-mode'][1]}/health/ready")
    print(f"PropertyScope home: http://localhost:{ports['propertyscope-shared-frontend'][1]}")
    print(f"PropertyScope:      http://localhost:{ports['propertyscope-frontend'][1]}")
    if full_data:
        print("Full-data mode:     enabled in an isolated Compose project")
    if offline:
        print("AI provider:        offline (data workflows remain available)")


def _rebuild(services: Sequence[str], *, full_data: bool, offline: bool) -> None:
    _openai_credential(offline=offline)
    _ensure_docker()
    selected = tuple(services) or APPLICATION_SERVICES
    _preflight_compose_host_ports(services=selected, full_data=full_data)
    compose_environment = _compose_environment(full_data=full_data, offline=offline)
    _run(
        _compose_command("build", *selected, full_data=full_data),
        environment=compose_environment,
    )
    _run(
        _compose_command(
            "up",
            "--detach",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "180",
            *selected,
            full_data=full_data,
        ),
        environment=compose_environment,
    )


def _down(*, full_data: bool, remove_volumes: bool = False) -> None:
    _ensure_docker()
    arguments = ["down", "--remove-orphans"]
    if remove_volumes:
        arguments.append("--volumes")
    _run(_compose_command(*arguments, full_data=full_data))
    _remove_openai_secret(full_data=full_data)


def _reset(*, full_data: bool) -> None:
    """Delete only volumes labelled for the selected Compose project."""
    _down(full_data=full_data, remove_volumes=True)
    project_name = FULL_DATA_PROJECT_NAME if full_data else DEFAULT_PROJECT_NAME
    _run(
        (
            "docker",
            "volume",
            "prune",
            "--all",
            "--force",
            "--filter",
            f"label=com.docker.compose.project={project_name}",
        )
    )
    print(f"Reset durable Docker volumes for Compose project {project_name}.", flush=True)


def _doctor(*, full_data: bool) -> None:
    """Validate local prerequisites and the selected merged Compose model."""
    _ensure_docker()
    _run(("docker", "compose", "version"))
    _run(_compose_command("config", "--quiet", full_data=full_data))
    provider = os.environ.get("AI_MODE_LLM_PROVIDER", "openai").strip().lower()
    variable = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    credential_state = "available" if os.environ.get(variable, "").strip() else "missing"
    print(
        f"{provider.title()} credential: {credential_state} (--offline remains available)",
        flush=True,
    )
    if full_data:
        print(f"Cached PSI annual archives: {len(_psi_cache_years())}", flush=True)
        print(f"Cached PSI weekly archives: {len(_psi_cache_weeks())}", flush=True)


def _json_response(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("PropertyScope returned a malformed JSON response")
    return value


def _collection_definition(job_profile: str, profile: str) -> tuple[str, dict[str, Any]]:
    path = JOB_PROFILE_DIRECTORY / f"{job_profile}.yaml"
    if not path.is_file():
        raise RuntimeError(f"Unknown registered collection job: {job_profile}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
        raise RuntimeError(f"Registered job profile is malformed: {path.name}")
    profiles = raw.get("scope_profiles")
    scope = profiles.get(profile) if isinstance(profiles, dict) else None
    if not isinstance(scope, dict):
        raise RuntimeError(f"{job_profile} does not define the {profile!r} acquisition profile")
    resolved_scope = dict(scope)
    resolved_scope["profile"] = profile
    return raw["key"], resolved_scope


def _collect_with_client(
    client: httpx.Client,
    *,
    job_profile: str,
    profile: str,
    wait: bool,
    timeout_seconds: int,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    """Plan and launch one registered Feature 1 collection over its public HTTP API."""
    profile_key, scope = _collection_definition(job_profile, profile)
    jobs = _json_response(client.get("jobs", params={"limit": 100})).get("items")
    if not isinstance(jobs, list):
        raise RuntimeError("PropertyScope did not return its registered jobs")
    job = next(
        (
            item
            for item in jobs
            if isinstance(item, dict) and item.get("profile_key") == profile_key
        ),
        None,
    )
    if job is None:
        raise RuntimeError(f"Registered job is missing from the running database: {profile_key}")

    request_body = {"run_mode": "full_refresh", "scope": scope}
    plan = _json_response(client.post(f"jobs/{job['id']}/plans", json=request_body))
    print(
        "Collection plan validated: "
        f"{profile_key} ({profile}); network_required={plan.get('network_required', False)}; "
        f"source_cache_required={plan.get('source_cache_required', False)}",
        flush=True,
    )
    operation_id = str(uuid.uuid4())
    created = _json_response(
        client.post(
            f"jobs/{job['id']}/runs",
            json=request_body,
            headers={
                "Idempotency-Key": f"dev-collect-{operation_id}",
                "X-Request-ID": operation_id,
            },
        )
    )
    run = created.get("run")
    if not isinstance(run, dict) or not isinstance(run.get("id"), str):
        raise RuntimeError("PropertyScope did not return the queued ingestion run")
    run_id = run["id"]
    print(f"Collection run queued: {run_id}", flush=True)
    if not wait:
        return {"run": run, "release": None}

    deadline = time.monotonic() + timeout_seconds
    previous_status: str | None = None
    while True:
        run_payload = _json_response(client.get(f"ingestion-runs/{run_id}"))
        current = run_payload.get("run")
        if not isinstance(current, dict):
            raise RuntimeError("PropertyScope returned malformed ingestion-run evidence")
        status = str(current.get("status", "unknown"))
        if status != previous_status:
            print(f"Collection run {run_id}: {status}", flush=True)
            previous_status = status
        if status in TERMINAL_COLLECTION_STATES:
            run = current
            break
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Collection run {run_id} did not finish within {timeout_seconds} seconds; "
                "it remains durable and can be inspected in the Runs screen"
            )
        time.sleep(poll_seconds)

    if run["status"] != "succeeded":
        error = json.dumps(run.get("error_json", {}), sort_keys=True)
        raise RuntimeError(f"Collection run {run_id} ended as {run['status']}: {error}")
    release: dict[str, Any] | None = None
    offset = 0
    for _page in range(100):
        page = _json_response(
            client.get("dataset-releases", params={"limit": 100, "offset": offset})
        )
        releases = page.get("items")
        if not isinstance(releases, list):
            raise RuntimeError("PropertyScope returned malformed release evidence")
        release = next(
            (
                item
                for item in releases
                if isinstance(item, dict) and item.get("ingestion_run_id") == run_id
            ),
            None,
        )
        next_offset = page.get("next_offset")
        if release is not None or next_offset is None:
            break
        if (
            not isinstance(next_offset, int)
            or isinstance(next_offset, bool)
            or next_offset <= offset
        ):
            raise RuntimeError("PropertyScope returned an invalid release-evidence cursor")
        offset = next_offset
    if release is None:
        raise RuntimeError(f"Collection run {run_id} succeeded without retained release evidence")
    print(
        f"Candidate release ready: {release['id']} ({release['status']}, "
        f"{release.get('record_count', 0):,} records).",
        flush=True,
    )
    print("Publication remains blocked until explicit human review and approval.", flush=True)
    return {"run": run, "release": release}


def _collect(
    *,
    job_profile: str,
    profile: str,
    wait: bool,
    timeout_seconds: int,
    base_url: str,
) -> None:
    if timeout_seconds < 1:
        raise RuntimeError("--timeout must be at least one second")
    with httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=30.0) as client:
        _collect_with_client(
            client,
            job_profile=job_profile,
            profile=profile,
            wait=wait,
            timeout_seconds=timeout_seconds,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the assignment-aligned local stack with fast source reloads."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    parser.set_defaults(full_data=False, env_file=None)

    def add_full_data_option(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--full-data",
            action="store_true",
            help="Use the isolated, opt-in source-scale PropertyScope profile",
        )

    def add_offline_option(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--offline",
            action="store_true",
            help="Start data/non-AI workflows without requiring a live provider credential",
        )

    def add_env_file_option(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--env-file",
            type=Path,
            help="Load provider settings from an explicit Git-ignored dotenv file",
        )

    up = commands.add_parser("up", help="Start the complete development stack")
    add_full_data_option(up)
    add_offline_option(up)
    add_env_file_option(up)

    rebuild = commands.add_parser(
        "rebuild",
        help="Rebuild images after dependency or Dockerfile changes",
    )
    rebuild.add_argument(
        "services",
        nargs="*",
        choices=BUILD_SERVICES,
        help="Optional application services to rebuild (all by default)",
    )
    add_full_data_option(rebuild)
    add_offline_option(rebuild)
    add_env_file_option(rebuild)

    restart = commands.add_parser(
        "restart", help="Recreate application containers without rebuilding"
    )
    add_full_data_option(restart)
    add_offline_option(restart)
    add_env_file_option(restart)
    down = commands.add_parser("down", help="Stop containers while preserving durable volumes")
    add_full_data_option(down)
    reset = commands.add_parser(
        "reset", help="Stop the stack and delete only its labelled durable Docker volumes"
    )
    add_full_data_option(reset)
    doctor = commands.add_parser("doctor", help="Validate Docker and the merged Compose model")
    add_full_data_option(doctor)
    add_env_file_option(doctor)
    status = commands.add_parser("status", help="Show current service and health state")
    add_full_data_option(status)
    config_command = commands.add_parser("config", help="Validate the merged Compose configuration")
    add_full_data_option(config_command)

    logs = commands.add_parser("logs", help="Follow recent application logs")
    logs.add_argument(
        "services",
        nargs="*",
        choices=APPLICATION_SERVICES,
        help="Optional services to follow (all application services by default)",
    )
    add_full_data_option(logs)

    collect = commands.add_parser(
        "collect",
        help="Plan, queue, and optionally wait for a registered Feature 1 acquisition",
    )
    collect.add_argument("job", choices=COLLECTION_JOBS, help="Registered acquisition job")
    collect.add_argument(
        "--profile",
        choices=("test", "showcase", "full-data"),
        default="showcase",
        help="Declared scope profile (default: showcase)",
    )
    collect.add_argument(
        "--wait",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Wait for retained terminal run and release evidence (default: true)",
    )
    collect.add_argument(
        "--timeout", type=int, default=900, help="Maximum seconds to wait (default: 900)"
    )
    collect.add_argument(
        "--base-url",
        default=PROPERTYSCOPE_API_URL,
        help="PropertyScope public API root",
    )

    commands.add_parser("test", help="Run the deterministic integration-feature tests")
    commands.add_parser("check", help="Run the complete canonical quality gate")
    ui = commands.add_parser(
        "ui",
        help="Serve Shared and Feature 1 with deterministic same-origin fixtures (no Docker)",
    )
    ui.add_argument("--port", type=int, default=None, help="Loopback port (default: 5300)")
    ui.add_argument(
        "--scenario",
        choices=UI_FIXTURE_SCENARIOS,
        default=os.environ.get("PROPERTYSCOPE_UI_SCENARIO", "populated"),
    )
    ui_smoke = commands.add_parser(
        "ui-smoke",
        help="Run the minimal Playwright smoke against an owned/reused UI fixture host",
    )
    ui_smoke.add_argument("--port", type=int, default=None, help="Loopback port (default: 5300)")
    ui_smoke.add_argument(
        "--scenario",
        choices=UI_FIXTURE_SCENARIOS,
        default="populated",
    )
    ui_smoke.add_argument(
        "--all-routes",
        action="store_true",
        help="Exercise every populated Shared and Feature 1 route family",
    )
    for command_name, profile in (
        ("ui-audit-quick", "quick"),
        ("ui-audit-full", "full"),
    ):
        audit = commands.add_parser(
            command_name,
            help=f"Run the {profile} resumable browser UI audit against owned fixtures",
        )
        audit.set_defaults(ui_audit_profile=profile)
        audit.add_argument("--port", type=int, default=None, help="Loopback fixture port")
        audit.add_argument("--output", type=Path, default=None, help="Artifact directory")
        audit.add_argument("--resume", type=Path, default=None, help="Resume artifact directory")
    sync_psi = commands.add_parser(
        "sync-psi", help="Acquire official PSI annual/weekly archives into the read-only app cache"
    )
    sync_psi.add_argument(
        "--all",
        action="store_true",
        help="Acquire annual history from 1990 plus every current-year Monday archive",
    )
    sync_psi.add_argument("--year", type=int, action="append", default=[], help="Annual archive")
    sync_psi.add_argument(
        "--week", action="append", default=[], metavar="YYYY-MM-DD", help="Weekly archive"
    )
    sync_psi.add_argument(
        "--current-weekly", action="store_true", help="Acquire all Monday archives this year"
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one documented development action."""
    arguments = _parser().parse_args(argv)
    try:
        if arguments.env_file is not None:
            _load_environment_file(arguments.env_file)
        if arguments.command == "up":
            _up(full_data=arguments.full_data, offline=arguments.offline)
        elif arguments.command == "rebuild":
            _rebuild(
                arguments.services,
                full_data=arguments.full_data,
                offline=arguments.offline,
            )
        elif arguments.command == "restart":
            _openai_credential(offline=arguments.offline)
            _ensure_docker()
            _preflight_compose_host_ports(
                services=APPLICATION_SERVICES,
                full_data=arguments.full_data,
            )
            compose_environment = _compose_environment(
                full_data=arguments.full_data,
                offline=arguments.offline,
            )
            _run(
                _compose_command(
                    "up",
                    "--detach",
                    "--force-recreate",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    *APPLICATION_SERVICES,
                    full_data=arguments.full_data,
                ),
                environment=compose_environment,
            )
        elif arguments.command == "down":
            _down(full_data=arguments.full_data)
        elif arguments.command == "reset":
            _reset(full_data=arguments.full_data)
        elif arguments.command == "doctor":
            _doctor(full_data=arguments.full_data)
        elif arguments.command == "status":
            _ensure_docker()
            _run(_compose_command("ps", full_data=arguments.full_data))
        elif arguments.command == "config":
            _ensure_docker()
            _run(_compose_command("config", "--quiet", full_data=arguments.full_data))
        elif arguments.command == "logs":
            _ensure_docker()
            selected = tuple(arguments.services) or APPLICATION_SERVICES
            _run(
                _compose_command(
                    "logs",
                    "--follow",
                    "--tail",
                    "200",
                    *selected,
                    full_data=arguments.full_data,
                )
            )
        elif arguments.command == "collect":
            _collect(
                job_profile=arguments.job,
                profile=arguments.profile,
                wait=arguments.wait,
                timeout_seconds=arguments.timeout,
                base_url=arguments.base_url,
            )
        elif arguments.command == "test":
            _run(
                (
                    sys.executable,
                    "-m",
                    "pytest",
                    "examples/integration-test-feature/tests",
                    "student-1/tests",
                )
            )
        elif arguments.command == "check":
            _run((sys.executable, "scripts/check.py"))
        elif arguments.command == "ui":
            _run(
                (
                    sys.executable,
                    "-m",
                    "scripts.ui_fixture_server",
                    "--port",
                    str(_ui_fixture_port(arguments.port)),
                    "--scenario",
                    arguments.scenario,
                )
            )
        elif arguments.command == "ui-smoke":
            _run(
                (
                    sys.executable,
                    "-m",
                    "scripts.ui_smoke",
                    "--port",
                    str(_ui_fixture_port(arguments.port)),
                    "--scenario",
                    arguments.scenario,
                    *(("--all-routes",) if arguments.all_routes else ()),
                )
            )
        elif arguments.command in {"ui-audit-quick", "ui-audit-full"}:
            _run(
                (
                    sys.executable,
                    "-m",
                    "scripts.ui_audit",
                    arguments.ui_audit_profile,
                    "--port",
                    str(_ui_fixture_port(arguments.port)),
                    *(("--output", str(arguments.output)) if arguments.output else ()),
                    *(("--resume", str(arguments.resume)) if arguments.resume else ()),
                )
            )
        elif arguments.command == "sync-psi":
            current_year = datetime.now(UTC).year
            years = list(arguments.year)
            weeks: list[date] = []
            try:
                weeks.extend(date.fromisoformat(value) for value in arguments.week)
            except ValueError as exc:
                raise RuntimeError("--week must use YYYY-MM-DD") from exc
            if arguments.all:
                years.extend(range(1990, current_year))
                weeks.extend(_current_psi_weeks())
            elif arguments.current_weekly:
                weeks.extend(_current_psi_weeks())
            if any(year < 1990 or year > current_year for year in years):
                raise RuntimeError("--year must be between 1990 and the current year")
            if any(week.weekday() != 0 for week in weeks):
                raise RuntimeError("--week must be a Monday publication date")
            _sync_psi(years=years, weeks=weeks)
    except FileNotFoundError:
        print(
            "Docker or uv is not available on PATH. See README.md for prerequisites.",
            file=sys.stderr,
        )
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"Development command failed with exit code {exc.returncode}.", file=sys.stderr)
        return exc.returncode
    except httpx.HTTPError as exc:
        print(f"Development HTTP request failed: {exc}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
