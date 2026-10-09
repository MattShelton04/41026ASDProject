"""Cross-platform workflow for the local integration stack.

Docker Compose runs the shared edge and the feature microservices. AI-mode (with the agent loop),
MCP and RAG run only as managed host processes, never as Compose services (ADR-043, ADR-046).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shlex
import shutil
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

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.devtools import host_runtime
from scripts.devtools.cli import build_parser
from scripts.devtools.config import (
    APPLICATION_SERVICES,
    BUILD_SERVICES,
    COMPOSE_FILES,
    DEFAULT_UI_FIXTURE_PORT,
    DISABLED_FEATURE_SERVICES,
    ENABLED_FEATURE_KEYS,
    FEATURE_FRONTEND_OWNERS,
    HOST_PORTS,
    JOB_PROFILE_DIRECTORY,
    OFFLINE_OPENAI_CREDENTIAL,
    PRODUCTION_BUILD_SERVICES,
    PRODUCTION_COMPOSE_FILES,
    PROFILES,
    PSI_WEEKLY_URL,
    PSI_YEARLY_URL,
    REPOSITORY_ROOT,
    RUNTIME_DIRECTORY,
    SUPPORTED_LLM_PROVIDERS,
    TERMINAL_COLLECTION_STATES,
    compose_project_name,
)
from scripts.devtools.operator_report import collect_operator_report, render_operator_report

FEATURE_1_KEY = "student-1-propertyscope-data-platform"
DEFAULT_ENV_FILE = REPOSITORY_ROOT / ".env"
STACK_UNREACHABLE_HINT = (
    "Is the stack running? Start it with `uv run scripts/dev.py stack up` (add --offline without "
    "a model key), or check `stack status`. Custom ports are read from .env or the shell."
)


def _compose_command(*arguments: str, reload: bool = True) -> tuple[str, ...]:
    command = ["docker", "compose"]
    if not reload:
        # The development overlay also supplies name: ps-dev. Omitting it must
        # retain the same containers/volumes rather than start the base "ps" project.
        command.extend(("--project-name", compose_project_name()))
    for filename in COMPOSE_FILES if reload else PRODUCTION_COMPOSE_FILES:
        command.extend(("--file", filename))
    for profile in PROFILES:
        command.extend(("--profile", profile))
    command.extend(arguments)
    return tuple(command)


LOCAL_VISUAL_ROOT = REPOSITORY_ROOT / ".propertyscope-visual" / "local"


def _run(command: Sequence[str], *, environment: Mapping[str, str] | None = None) -> None:
    print(f"> {shlex.join(command)}", flush=True)
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True, env=environment)  # noqa: S603 - argv built by this CLI, no shell


def _repeated_options(option: str, values: Sequence[str]) -> tuple[str, ...]:
    return tuple(part for value in values for part in (option, value))


def _visual_compare(
    *, provider: str, cases: Sequence[str], sections: Sequence[str], reset_baseline: bool
) -> None:
    """Save a screenshot baseline, or capture the working tree and compare it with the baseline."""
    root = LOCAL_VISUAL_ROOT / provider
    baseline, current, report = root / "baseline", root / "current", root / "report"
    capture = (
        sys.executable,
        "-m",
        "scripts.visual",
        "capture",
        "--provider",
        provider,
        *_repeated_options("--case", cases),
        *_repeated_options("--section", sections),
    )
    if reset_baseline:
        shutil.rmtree(baseline, ignore_errors=True)
    if not (baseline / f"capture-{provider}.json").is_file():
        _run((*capture, "--revision", "base", "--out", str(baseline)))
        print(
            f"\nBaseline saved in {baseline}.\nMake your change, then run this command again "
            "to compare it with the baseline.",
            flush=True,
        )
        return
    shutil.rmtree(current, ignore_errors=True)
    shutil.rmtree(report, ignore_errors=True)
    try:
        _run((*capture, "--revision", "head", "--out", str(current)))
    except subprocess.CalledProcessError:
        print("Some views were not captured; the comparison lists them as incomplete.", flush=True)
    _run(
        (
            sys.executable,
            "-m",
            "scripts.visual",
            "compare",
            "--base",
            str(baseline),
            "--head",
            str(current),
            "--out",
            str(report),
            "--title",
            f"Working tree against the saved {provider} baseline",
        )
    )


def _ensure_docker() -> None:
    _run(("docker", "info", "--format", "Docker Engine {{.ServerVersion}} is ready"))


def _validate_deployment_inputs() -> None:
    """Refuse stack mutation when explicit enablement and exposed topology have drifted."""
    _run((sys.executable, "scripts/generate_deployment.py", "--check"))
    _run((sys.executable, "scripts/validate_architecture.py"))
    _run((sys.executable, "scripts/validate_tool_catalogs.py"))


def _stop_disabled_feature_services() -> None:
    """Gracefully stop only generated, feature-labelled services that are now disabled."""
    if DISABLED_FEATURE_SERVICES:
        _run(_compose_command("stop", *DISABLED_FEATURE_SERVICES))


def _reload_shared_edge(*, environment: Mapping[str, str]) -> None:
    """Reparse bind-mounted route projections without recreating the edge container."""
    _run(
        _compose_command("exec", "--no-TTY", "shared-frontend", "nginx", "-s", "reload"),
        environment=environment,
    )


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
    completed = subprocess.run(  # noqa: S603 - argv built by this CLI, no shell
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


def _preflight_compose_host_ports(*, services: Sequence[str]) -> None:
    """Reject conflicting host ports before secrets, builds, or container mutation."""
    project = compose_project_name()
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


def _load_development_environment(explicit_path: Path | None) -> Path | None:
    """Load the selected dotenv file, defaulting to the optional root .env."""
    path = explicit_path if explicit_path is not None else DEFAULT_ENV_FILE
    if explicit_path is None and not path.is_file():
        return None
    _load_environment_file(path)
    return path


def _runtime_secret_path() -> Path:
    return RUNTIME_DIRECTORY / "openai_api_key"


def _write_openai_secret(credential: str) -> Path:
    """Materialise the provider credential file read by host AI-mode, outside process arguments."""
    RUNTIME_DIRECTORY.mkdir(parents=True, exist_ok=True)
    destination = _runtime_secret_path()
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


def _remove_openai_secret() -> None:
    _runtime_secret_path().unlink(missing_ok=True)
    with suppress(OSError):
        RUNTIME_DIRECTORY.rmdir()


def _source_cache_root() -> Path:
    """Return the host source cache mounted read-only into the Feature 1 runner.

    PROPERTYSCOPE_SOURCE_CACHE_DIR lets several checkouts share one verified cache instead of
    downloading G-NAF and PSI again. Relative values resolve from the repository root, exactly as
    Compose resolves the same variable in docker-compose.yml.
    """
    configured = os.environ.get("PROPERTYSCOPE_SOURCE_CACHE_DIR", "").strip()
    if not configured:
        return REPOSITORY_ROOT / ".propertyscope-source-cache"
    return (REPOSITORY_ROOT / Path(configured).expanduser()).resolve()


def _feature_1_api_url() -> str:
    """Resolve the direct Feature 1 API root from the same port setting Compose uses."""
    ports = _resolved_host_ports(APPLICATION_SERVICES)
    if "f1-frontend" not in ports:
        raise RuntimeError("Feature 1 is not enabled in the deployment projection")
    return f"http://127.0.0.1:{ports['f1-frontend'][1]}/api/data-platform/v1"


def _psi_cache_years() -> tuple[int, ...]:
    root = _source_cache_root() / "psi"
    if not root.is_dir():
        return ()
    return tuple(
        sorted(int(path.stem) for path in root.glob("[0-9][0-9][0-9][0-9].zip") if path.is_file())
    )


def _psi_cache_weeks() -> tuple[str, ...]:
    weekly = _source_cache_root() / "psi" / "weekly"
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
        return response.content
    chunks: list[bytes] = []
    offset = 0
    expected_total: int | None = None
    chunk_size = 4 * 1024 * 1024
    while expected_total is None or offset < expected_total:
        end = offset + chunk_size - 1
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
            raise RuntimeError("PSI publisher rejected Range acquisition")
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", ranged.headers.get("content-range", ""))
        if match is None or int(match.group(1)) != offset:
            raise RuntimeError("PSI publisher returned an invalid content range")
        range_end, total = int(match.group(2)), int(match.group(3))
        if len(ranged.content) != range_end - offset + 1:
            raise RuntimeError("PSI publisher returned an incomplete content range")
        if expected_total is not None and total != expected_total:
            raise RuntimeError("PSI archive changed during acquisition")
        expected_total = total
        chunks.append(ranged.content)
        offset = range_end + 1
    return b"".join(chunks)


def _sync_psi(*, years: Sequence[int], weeks: Sequence[date]) -> None:
    root = _source_cache_root() / "psi"
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
    # Bound connection set-up; a full PSI archive download may legitimately read for minutes.
    with httpx.Client(timeout=httpx.Timeout(None, connect=60.0), follow_redirects=False) as client:
        for url, destination in targets:
            if destination.is_file():
                try:
                    with ZipFile(destination) as archive:
                        valid_cache = bool(archive.namelist()) and archive.testzip() is None
                    if valid_cache:
                        print(
                            f"PSI cache retained: {destination}",
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
                f"PSI cached: {destination} "
                f"({len(content):,} bytes, sha256 {hashlib.sha256(content).hexdigest()})",
                flush=True,
            )


def _compose_environment(*, offline: bool) -> Mapping[str, str]:
    credential = _openai_credential(offline=offline)
    environment = os.environ.copy()
    environment["AI_MODE_SERVICE_TOKEN"] = host_runtime.ai_service_token(environment)
    environment.pop("OPENAI_API_KEY", None)
    environment.pop("GEMINI_API_KEY", None)
    secret_path = str(_write_openai_secret(credential))
    environment["OPENAI_API_KEY_FILE"] = secret_path
    environment["GEMINI_API_KEY_FILE"] = secret_path
    if offline:
        environment["AI_MODE_REQUIRE_PROVIDER_READY"] = "false"
    if FEATURE_1_KEY in ENABLED_FEATURE_KEYS:
        years = _psi_cache_years()
        weeks = _psi_cache_weeks()
        if years:
            environment.setdefault("PROPERTYSCOPE_PSI_CACHED_YEARS", ",".join(map(str, years)))
        if weeks:
            environment.setdefault("PROPERTYSCOPE_PSI_CACHED_WEEKS", ",".join(weeks))
    else:
        environment.pop("PROPERTYSCOPE_PSI_CACHED_YEARS", None)
        environment.pop("PROPERTYSCOPE_PSI_CACHED_WEEKS", None)
    return environment


def _start_host_ai(environment: Mapping[str, str], *, mode: str) -> None:
    """Start the host AI services after removing any owner the old Docker placement left."""
    host_runtime.retire_container_placement()
    host_runtime.migrate_legacy_state()
    host_runtime.start(environment, mode=mode)


def _up(*, offline: bool, build: bool = False, reload: bool = True) -> None:
    _openai_credential(offline=offline)
    _validate_deployment_inputs()
    _ensure_docker()
    _stop_disabled_feature_services()
    _preflight_compose_host_ports(services=APPLICATION_SERVICES)
    compose_environment = _compose_environment(offline=offline)
    mode = "direct" if offline else "combined"
    _start_host_ai(compose_environment, mode=mode)
    feature_1_enabled = FEATURE_1_KEY in ENABLED_FEATURE_KEYS
    if feature_1_enabled:
        print(f"Official PSI cache: {', '.join(map(str, _psi_cache_years()))}", flush=True)
    up_arguments = ["up"]
    if build:
        up_arguments.append("--build")
    up_arguments.extend(
        (
            "--detach",
            "--wait",
            "--wait-timeout",
            "180",
            *APPLICATION_SERVICES,
        )
    )
    _run(
        _compose_command(*up_arguments, reload=reload),
        environment=compose_environment,
    )
    _reload_shared_edge(environment=compose_environment)
    print(f"AI runtime:         host processes, {mode} mode (not containerised)", flush=True)
    print(
        "Source refresh:     "
        + ("development reload" if reload else "built images; use --build after edits"),
        flush=True,
    )
    ports = _resolved_host_ports(APPLICATION_SERVICES)
    shared_port = ports["shared-frontend"][1]
    print(f"\nCompose project:    {compose_project_name()}")
    print(f"AI-mode health:     http://localhost:{shared_port}/api/shared-health/ai-mode")
    print(f"PropertyScope home: http://localhost:{shared_port}")
    for service, owner in FEATURE_FRONTEND_OWNERS.items():
        if service in ports:
            print(f"{owner + ':':<20}http://localhost:{ports[service][1]}  ({service})")
    if feature_1_enabled:
        print(f"Source cache:       {_source_cache_root()}")
        print("Official sources:   enabled; nothing is downloaded until a data job starts")
    else:
        print("Official sources:   disabled (Feature 1 is not enabled)")
    if offline:
        print("AI provider:        offline (data workflows remain available)")


def _rebuild(services: Sequence[str], *, offline: bool) -> None:
    _openai_credential(offline=offline)
    _validate_deployment_inputs()
    _ensure_docker()
    _stop_disabled_feature_services()
    selected = tuple(services) or BUILD_SERVICES
    _preflight_compose_host_ports(services=selected)
    compose_environment = _compose_environment(offline=offline)
    _run(
        _compose_command("build", *selected),
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
        ),
        environment=compose_environment,
    )


def _production_build(services: Sequence[str]) -> None:
    """Build immutable Release 0 images without starting or changing a runtime."""
    _validate_deployment_inputs()
    _ensure_docker()
    selected = tuple(services) or PRODUCTION_BUILD_SERVICES
    command = ["docker", "compose"]
    for filename in PRODUCTION_COMPOSE_FILES:
        command.extend(("--file", filename))
    command.extend(("--profile", "release-0", "build", *selected))
    _run(tuple(command))


def _ai_status() -> None:
    print("AI runtime: host processes (not containerised; Compose defines no AI service)")
    print(json.dumps(host_runtime.status(), indent=2), flush=True)


def _down(*, remove_volumes: bool = False) -> None:
    host_runtime.stop()
    _ensure_docker()
    # --remove-orphans also removes containers from the retired Docker AI placement.
    arguments = ["down", "--remove-orphans"]
    if remove_volumes:
        arguments.append("--volumes")
    _run(_compose_command(*arguments))
    _remove_openai_secret()


def _reset() -> None:
    """Delete only volumes labelled for the selected Compose project."""
    _down(remove_volumes=True)
    project_name = compose_project_name()
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


def _doctor() -> None:
    """Validate local prerequisites and the selected merged Compose model."""
    _validate_deployment_inputs()
    _ensure_docker()
    _run(("docker", "compose", "version"))
    _run(_compose_command("config", "--quiet"))
    provider = os.environ.get("AI_MODE_LLM_PROVIDER", "openai").strip().lower()
    variable = "GEMINI_API_KEY" if provider == "gemini" else "OPENAI_API_KEY"
    credential_state = "available" if os.environ.get(variable, "").strip() else "missing"
    print(
        f"{provider.title()} credential: {credential_state} (--offline remains available)",
        flush=True,
    )
    print(f"Compose project: {compose_project_name()}", flush=True)
    print("AI runtime: host processes (Compose defines no AI-mode, MCP or RAG)", flush=True)
    for service in host_runtime.status():
        print(f"  {service['service']:<8} {service['state']:<8} {service['url']}", flush=True)
    if FEATURE_1_KEY in ENABLED_FEATURE_KEYS:
        cache = _source_cache_root()
        gnaf = "present" if (cache / "gnaf.zip").is_file() else "absent"
        print(f"Source cache: {cache} (G-NAF archive {gnaf})", flush=True)
        print(f"Cached PSI annual archives: {len(_psi_cache_years())}", flush=True)
        print(f"Cached PSI weekly archives: {len(_psi_cache_weeks())}", flush=True)
    else:
        print("Official sources: disabled (Feature 1 is not enabled)", flush=True)
    print("Host ports:", flush=True)
    for line in _host_port_report(tuple(HOST_PORTS)):
        print(f"  {line}", flush=True)


def _host_port_report(services: Sequence[str]) -> tuple[str, ...]:
    """Describe each configured loopback port as free, owned by this project, or occupied."""
    project = compose_project_name()
    lines: list[str] = []
    for service, (variable, port) in _resolved_host_ports(services).items():
        if _host_port_is_available(port):
            state = "free"
        else:
            owners = _published_port_owners(port)
            if owners and all(owner_project == project for owner_project, _ in owners):
                state = "in use by this project"
            elif owners:
                state = "in use by " + ", ".join(f"{p}/{s}" for p, s in owners)
            else:
                state = "in use by a non-Compose process (host AI runtime or another program)"
        lines.append(f"{service:<18} 127.0.0.1:{port:<6} {variable:<36} {state}")
    return tuple(lines)


def _json_response(response: httpx.Response) -> dict[str, Any]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise RuntimeError("PropertyScope returned a malformed JSON response")
    return value


def _collection_definition(job_profile: str) -> tuple[str, dict[str, Any]]:
    path = JOB_PROFILE_DIRECTORY / f"{job_profile}.yaml"
    if not path.is_file():
        raise RuntimeError(f"Unknown registered collection job: {job_profile}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("key"), str):
        raise RuntimeError(f"Registered job profile is malformed: {path.name}")
    scope = raw.get("scope")
    if not isinstance(scope, dict):
        raise RuntimeError(f"{job_profile} does not define its complete acquisition scope")
    return raw["key"], dict(scope)


def _collect_with_client(
    client: httpx.Client,
    *,
    job_profile: str,
    wait: bool,
    timeout_seconds: int,
    poll_seconds: float = 1.0,
) -> dict[str, Any]:
    """Plan and launch one registered Feature 1 collection over its public HTTP API."""
    profile_key, scope = _collection_definition(job_profile)
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
        f"{profile_key} (complete source); network_required={plan.get('network_required', False)}; "
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
            wait=wait,
            timeout_seconds=timeout_seconds,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one documented development action."""
    arguments = build_parser().parse_args(argv)
    try:
        command = (arguments.group, arguments.action)
        # Every command sees the same optional .env (the shell still wins), so a project name or
        # port chosen there applies to reset, logs and data commands exactly as it does to up.
        _load_development_environment(arguments.env_file)
        if command == ("stack", "up"):
            if arguments.ai_runtime not in {None, "host"}:
                raise RuntimeError(
                    "AI-mode, MCP and RAG no longer run in Docker (ADR-046); "
                    "`stack up` always starts them as host processes"
                )
            if arguments.ai_runtime == "host":
                print("--ai-runtime is no longer needed: AI services always run on the host.")
            _up(
                offline=arguments.offline,
                build=arguments.build,
                reload=not arguments.no_reload,
            )
        elif command == ("stack", "build"):
            _production_build(arguments.services)
        elif command == ("stack", "rebuild"):
            _rebuild(
                arguments.services,
                offline=arguments.offline,
            )
        elif command == ("stack", "restart"):
            _openai_credential(offline=arguments.offline)
            _validate_deployment_inputs()
            _ensure_docker()
            _stop_disabled_feature_services()
            selected = tuple(arguments.services) or APPLICATION_SERVICES
            _preflight_compose_host_ports(services=selected)
            compose_environment = _compose_environment(
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
                    *selected,
                ),
                environment=compose_environment,
            )
        elif command == ("stack", "down"):
            _down()
        elif command == ("stack", "reset"):
            _reset()
        elif command == ("stack", "doctor"):
            _doctor()
        elif command == ("stack", "status"):
            _ai_status()
            _ensure_docker()
            _run(_compose_command("ps"))
        elif command == ("stack", "config"):
            _validate_deployment_inputs()
            _ensure_docker()
            _run(_compose_command("config", "--quiet"))
        elif command == ("stack", "logs"):
            _ensure_docker()
            selected = tuple(arguments.services) or APPLICATION_SERVICES
            if arguments.tail < 0:
                raise RuntimeError("--tail must be zero or a positive number of lines")
            _run(
                _compose_command(
                    "logs",
                    *(("--follow",) if arguments.follow else ()),
                    "--tail",
                    str(arguments.tail),
                    *selected,
                )
            )
        elif command == ("data", "collect"):
            _collect(
                job_profile=arguments.job,
                wait=arguments.wait,
                timeout_seconds=arguments.timeout,
                base_url=arguments.base_url or _feature_1_api_url(),
            )
        elif command == ("operator", "report"):
            data_base_url = _feature_1_api_url()
            ports = _resolved_host_ports(APPLICATION_SERVICES)
            feature_port = ports["f1-frontend"][1]
            shared_port = ports["shared-frontend"][1]
            with httpx.Client(follow_redirects=False) as client:
                report = collect_operator_report(
                    client,
                    data_base_url=arguments.base_url or data_base_url,
                    feature_health_url=(
                        arguments.feature_health_url
                        or f"http://127.0.0.1:{feature_port}/health/ready"
                    ),
                    ai_health_url=(
                        arguments.ai_health_url
                        or f"http://127.0.0.1:{shared_port}/api/shared-health/ai-mode"
                    ),
                )
            print(render_operator_report(report), flush=True)
        elif command == ("ai", "start"):
            mode = "direct" if arguments.offline else arguments.mode
            _start_host_ai(_compose_environment(offline=arguments.offline), mode=mode)
            _ai_status()
        elif command == ("ai", "stop"):
            host_runtime.stop(tuple(arguments.services) or host_runtime.SERVICES)
        elif command == ("ai", "status"):
            _ai_status()
        elif command == ("ai", "logs"):
            print(host_runtime.logs(tuple(arguments.services) or host_runtime.SERVICES))
        elif command == ("ai", "serve"):
            host_runtime.serve(arguments.service)
        elif command == ("ai", "validate"):
            from scripts.release1_validation import FEATURE, QUERY, validate

            # Each flag applies to one mode only; a silent pass would report a
            # validation the user did not ask for.
            if arguments.mode == "mcp" and arguments.corpus is not None:
                raise RuntimeError("--corpus applies to rag mode only")
            if arguments.mode == "rag" and arguments.tool is not None:
                raise RuntimeError("--tool applies to mcp mode only")
            evidence = validate(
                arguments.mode,
                os.environ,
                output=arguments.output,
                query=arguments.query or QUERY,
                corpus=arguments.corpus,
                feature=arguments.feature or FEATURE,
                tool=arguments.tool,
            )
            print(json.dumps(evidence, indent=2))
            return 0 if evidence["passed"] else 1
        elif command == ("ai", "review"):
            from scripts.devtools.review.cli import run as run_review

            return run_review(arguments, os.environ)
        elif command == ("ai", "probe"):
            from scripts.release1_probe import probe, render

            observations = probe(os.environ, output=arguments.output)
            print(render(observations), flush=True)
            return 0 if observations["passed"] else 1
        elif command == ("ui", "serve"):
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
        elif command == ("ui", "smoke"):
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
        elif command == ("ui", "readme-screenshots"):
            _run(
                (
                    sys.executable,
                    "-m",
                    "scripts.readme_screenshots",
                    "--port",
                    str(_ui_fixture_port(arguments.port)),
                    *(("--output", str(arguments.output)) if arguments.output else ()),
                )
            )
        elif command == ("ui", "visual"):
            _visual_compare(
                provider=arguments.provider,
                cases=arguments.case,
                sections=arguments.section,
                reset_baseline=arguments.reset_baseline,
            )
        elif command == ("ui", "audit"):
            _run(
                (
                    sys.executable,
                    "-m",
                    "scripts.ui_audit",
                    arguments.profile,
                    "--port",
                    str(_ui_fixture_port(arguments.port)),
                    *(("--output", str(arguments.output)) if arguments.output else ()),
                    *(("--resume", str(arguments.resume)) if arguments.resume else ()),
                    *_repeated_options("--workspace", arguments.workspace),
                    *_repeated_options("--route-group", arguments.route_group),
                    *_repeated_options("--route", arguments.route),
                    *_repeated_options("--scenario", arguments.scenario),
                    *_repeated_options("--viewport", arguments.viewport),
                    "--shard-index",
                    str(arguments.shard_index),
                    "--shard-total",
                    str(arguments.shard_total),
                    *(("--allow-destructive",) if arguments.allow_destructive else ()),
                )
            )
        elif command == ("data", "sync-psi"):
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
        elif arguments.group == "security":
            from scripts.security.cli import main as security_main

            security_arguments = [arguments.action]
            if arguments.action == "report":
                if arguments.output_dir is not None:
                    security_arguments.extend(("--output-dir", str(arguments.output_dir)))
                if arguments.check:
                    security_arguments.append("--check")
            return security_main(security_arguments)
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
        if isinstance(exc, httpx.TransportError):
            print(STACK_UNREACHABLE_HINT, file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
