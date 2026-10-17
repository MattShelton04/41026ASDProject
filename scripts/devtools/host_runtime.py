"""Managed host AI processes, exclusive state and Docker-to-host projections.

AI-mode, MCP, RAG and the Multi-Agent Server run only here, outside containers (ADR-043,
ADR-046, ADR-047). Compose services reach AI-mode and the Multi-Agent Server through
``host.docker.internal``; MCP and RAG bind loopback.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import IO

import httpx
import psutil
import yaml

from scripts.devtools.config import REPOSITORY_ROOT, RUNTIME_DIRECTORY, compose_project_name
from scripts.devtools.runtime_settings import AI_SERVICE_PORTS, validate_capability_mode
from scripts.devtools.service_auth import AI_SERVICE_TOKEN_HEADER, validate_service_token
from scripts.devtools.service_auth import protect_entry as protect_host_entry
from shared_contracts.deployment import DeploymentProjectionV1

HOST_DIRECTORY = RUNTIME_DIRECTORY / "host"
SERVICES = tuple(AI_SERVICE_PORTS)
PORTS = AI_SERVICE_PORTS
# Left behind by the retired Docker AI placement (ADR-044, superseded by ADR-046).
RETIRED_CONTAINER_SERVICES = ("shared-ai-mode", "mcp-server", "rag-server")
RETIRED_PROJECTION_DIRECTORY = RUNTIME_DIRECTORY / "docker-ai"
RETIRED_PLACEMENT_STATE = RUNTIME_DIRECTORY / "ai-runtime.json"
# Bounded first-start allowances. RAG verifies and loads a local ONNX embedding model before it
# listens, which on a cold Windows start (antivirus scanning onnxruntime) can exceed 30 s.
READY_TIMEOUT_VARIABLE = "PROPERTYSCOPE_HOST_READY_TIMEOUT"
DEFAULT_READY_TIMEOUTS = {"ai-mode": 60, "mcp": 60, "rag": 180, "multi-agent": 60}
MAXIMUM_READY_TIMEOUT = 1800
# Seconds of silence before the launcher says what it is waiting for.
WAIT_NOTICE_AFTER = 5.0
FAILURE_LOG_LINES = 15
# AI-mode and the Multi-Agent Server accept host-gateway traffic; MCP and RAG bind loopback.
WILDCARD_SERVICES = frozenset({"ai-mode", "multi-agent"})


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def port_for(service: str, environment: Mapping[str, str]) -> int:
    """Validate a managed service's configured local port."""
    variable, default = PORTS[service]
    raw = environment.get(variable, str(default))
    if not raw.isdecimal() or not 1 <= int(raw) <= 65535:
        raise RuntimeError(f"{variable} must be an integer between 1 and 65535")
    return int(raw)


def bind_host(service: str) -> str:
    """Return the interface a managed service listens on (ADR-046, ADR-047)."""
    if service in WILDCARD_SERVICES:
        return "0.0.0.0"  # noqa: S104 - containers reach AI-mode and Multi-Agent via the host gateway
    return "127.0.0.1"


def port_is_free(port: int) -> bool:
    """Report whether no process listens on ``port`` on loopback or any IPv4 address.

    Windows lets a loopback bind succeed beside another process's ``0.0.0.0`` listener, even
    with ``SO_EXCLUSIVEADDRUSE`` on the probe. A loopback-only probe therefore let a stale
    AI-mode or Multi-Agent Server from another checkout look free: it answered this checkout's
    liveness wait, and the new process then exited on its own bind failure. Probing the
    wildcard address as well catches that listener on every platform.
    """
    for host in ("127.0.0.1", "0.0.0.0"):  # noqa: S104 - bind probe only, never listens
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind((host, port))
            except OSError:
                return False
    return True


def port_owner(port: int) -> str:
    """Name the local process listening on ``port`` when the platform allows it."""
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if (
                connection.status == psutil.CONN_LISTEN
                and connection.laddr
                and connection.laddr.port == port
                and connection.pid
            ):
                process = psutil.Process(connection.pid)
                command = process.cmdline()
                if "scripts.devtools.host_runtime" in command and "serve" in command:
                    return (
                        f"PropertyScope host process PID {connection.pid}, which this checkout "
                        "does not manage (another checkout, or a foreground `ai serve`)"
                    )
                return f"{process.name()} (PID {connection.pid})"
    except (OSError, psutil.Error):
        pass
    return "another process"


def _owned_process(service: str) -> psutil.Process | None:
    """Never signal a reused PID or a process from a different checkout."""
    path = HOST_DIRECTORY / f"{service}.json"
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        process = psutil.Process(state["pid"])
        if (
            process.create_time() != state["created_at"]
            or state.get("checkout") != str(REPOSITORY_ROOT.resolve())
            or process.cmdline() != state["command"]
            or not process.is_running()
            or process.status() == psutil.STATUS_ZOMBIE
        ):
            return None
        return process
    except (OSError, ValueError, KeyError, TypeError, psutil.Error):
        return None


def foreground_process(
    service: str, environment: Mapping[str, str] | None = None
) -> psutil.Process | None:
    """The foreground ``ai serve SERVICE`` of this checkout, found by its listening port.

    ``ai serve`` keeps no state file, so it is recognised by its command and working directory:
    a ``host_runtime serve SERVICE`` process started in this checkout. One from another checkout
    is not this checkout's and stays reported as a port holder.
    """
    port = port_for(service, os.environ if environment is None else environment)
    try:
        for connection in psutil.net_connections(kind="tcp"):
            if not (
                connection.status == psutil.CONN_LISTEN
                and connection.laddr
                and connection.laddr.port == port
                and connection.pid
            ):
                continue
            process = psutil.Process(connection.pid)
            command = process.cmdline()
            serves = "scripts.devtools.host_runtime" in command and command[-2:] == [
                "serve",
                service,
            ]
            if serves and Path(process.cwd()).resolve() == REPOSITORY_ROOT.resolve():
                return process
            return None
    except (OSError, psutil.Error):
        pass
    return None


def is_managed(service: str) -> bool:
    """Whether this checkout launched the identity-verified process for ``service``."""
    return _owned_process(service) is not None


def stop(services: Sequence[str] = SERVICES) -> None:
    """Stop only identity-verified managed processes and retain all durable state."""
    for service in reversed(services):
        process = _owned_process(service)
        if process is not None:
            try:
                # Windows venv executables can supervise a child interpreter and change cwd.
                # Keep the fixed checkout identity in the launch record; stop its owned tree.
                children = [
                    (child, child.create_time()) for child in process.children(recursive=True)
                ]
                for child, created_at in reversed(children):
                    if child.is_running() and child.create_time() == created_at:
                        child.terminate()
                process.terminate()
                process.wait(timeout=10)
            except psutil.TimeoutExpired:
                # Recheck ownership before escalation in case a PID was reused.
                if (owned := _owned_process(service)) is not None:
                    owned.kill()
                    owned.wait(timeout=5)
            except psutil.NoSuchProcess:
                pass
        (HOST_DIRECTORY / f"{service}.json").unlink(missing_ok=True)


def local_url(service: str, environment: Mapping[str, str]) -> str:
    """Return the host URL a terminal check or ingestion client uses for one service."""
    return f"http://127.0.0.1:{port_for(service, environment)}" + (
        "/mcp" if service == "mcp" else ""
    )


def status(
    environment: Mapping[str, str] | None = None,
    *,
    probe: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> list[dict[str, str]]:
    """Return process state and local URLs without exposing configuration or credentials.

    With ``probe`` each running process is asked for readiness, so a process that is alive
    but unusable (an unprepared RAG model, an unreachable provider, a stale token) is visible,
    and a stopped service whose port another process holds is reported before ``ai start``.
    """
    values = os.environ if environment is None else environment
    entries: list[dict[str, str]] = []
    for service in SERVICES:
        managed = _owned_process(service) is not None
        foreground = None if managed else foreground_process(service, values)
        entry = {
            "service": service,
            "state": "running" if managed or foreground else "stopped",
            "url": local_url(service, values),
        }
        if foreground is not None:
            entry["mode"] = "foreground"
            entry["pid"] = str(foreground.pid)
        entries.append(entry)
    if not probe:
        return entries
    authenticated = _with_existing_tokens(values)
    with httpx.Client(timeout=5, follow_redirects=False, transport=transport) as client:
        for entry in entries:
            service = entry["service"]
            port = port_for(service, values)
            if entry["state"] == "running":
                entry["health"], entry["detail"] = probe_health(service, authenticated, client)
                if entry.get("mode") == "foreground":
                    shown = f"foreground `ai serve`, PID {entry['pid']}"
                    entry["detail"] = f"{shown}; {entry['detail']}" if entry["detail"] else shown
            elif not port_is_free(port):
                entry["health"] = "port in use"
                entry["detail"] = (
                    f"{port_owner(port)} holds {PORTS[service][0]}={port}; `ai start` will "
                    "refuse it"
                )
            else:
                entry["health"], entry["detail"] = "-", ""
    return entries


READINESS_PATHS = {
    "ai-mode": "/health/ready",
    "mcp": "/health",
    "rag": "/health/ready",
    "multi-agent": "/health/ready",
}
TOKEN_VARIABLES = {
    "ai-mode": "AI_MODE_SERVICE_TOKEN",
    "mcp": "MCP_SERVICE_TOKEN",
    "rag": "RAG_SERVICE_TOKEN",
    "multi-agent": "MULTI_AGENT_SERVICE_TOKEN",
}


def _with_existing_tokens(environment: Mapping[str, str]) -> dict[str, str]:
    """Add the launcher's persisted tokens for probing; never create or print one."""
    values = dict(environment)
    for service, variable in TOKEN_VARIABLES.items():
        path = HOST_DIRECTORY / f"{service}.token"
        if not values.get(variable) and path.is_file():
            values[variable] = path.read_text(encoding="utf-8").strip()
    return values


def _unhealthy_checks(body: Mapping[str, object]) -> str:
    checks = body.get("checks")
    if not isinstance(checks, dict):
        return ""
    problems = [
        f"{name}: {check.get('detail') or check.get('status')}"
        for name, check in checks.items()
        if isinstance(check, dict) and check.get("status") != "healthy"
    ]
    text = "; ".join(problems)
    return text if len(text) <= 160 else text[:157] + "..."


def probe_health(
    service: str, environment: Mapping[str, str], client: httpx.Client
) -> tuple[str, str]:
    """Classify one running service as ready, degraded, not ready or not responding."""
    url = f"http://127.0.0.1:{port_for(service, environment)}{READINESS_PATHS[service]}"
    try:
        response = client.get(url, headers=_service_headers(service, environment))
    except httpx.HTTPError:
        return "not responding", f"no answer; see `uv run scripts/dev.py ai logs {service}`"
    if response.status_code in {401, 403}:
        return (
            "token mismatch",
            "the process rejects this checkout's service token; run `ai stop` then `ai start`",
        )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if response.status_code == 200:
        if str(body.get("status", "")).lower() == "degraded":
            return "degraded", _unhealthy_checks(body)
        if service == "mcp":
            return "ready", f"{body.get('registered_tools', '?')} tools registered"
        if service == "rag":
            model = str(body.get("embedding_model", "?")).split("@", 1)[0]
            return "ready", f"embedding model {model}"
        return "ready", ""
    if service == "rag" and body.get("embedding_model") == "unprepared-local-model":
        return (
            "not ready",
            "embedding model not prepared: run `uv run rag-server prepare-model`, "
            "then `ai stop rag` and `ai start`",
        )
    return "not ready", _unhealthy_checks(body) or f"HTTP {response.status_code}"


def render_status(entries: Sequence[Mapping[str, str]]) -> list[str]:
    """Format status entries as aligned terminal lines for logs and evidence."""
    lines = []
    for entry in entries:
        line = f"  {entry['service']:<12} {entry['state']:<8} "
        if "health" in entry:
            line += f"{entry['health']:<15} "
        line += entry["url"]
        if entry.get("detail"):
            line += f"  ({entry['detail']})"
        lines.append(line.rstrip())
    return lines


def logs(services: Sequence[str] = SERVICES, *, lines: int = 100) -> str:
    """Read bounded recent logs; provider keys are never included in process commands."""
    output: list[str] = []
    for service in services:
        path = HOST_DIRECTORY / f"{service}.log"
        output.append(f"--- {service} ---")
        if path.exists():
            with path.open("rb") as stream:
                stream.seek(max(0, path.stat().st_size - 131_072))
                output.extend(stream.read().decode("utf-8", errors="replace").splitlines()[-lines:])
        else:
            output.append("No managed log yet.")
    return "\n".join(output)


def _docker(*arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed docker/python argv, no shell
        ("docker", *arguments),  # noqa: S607 - docker is resolved from the developer PATH
        check=True,
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
    ).stdout.strip()


def retire_container_placement() -> None:
    """Remove what the retired Docker AI placement left in this checkout, once.

    Its containers opened the same SQLite stores and published the same host ports, so they
    must be gone before a host owner starts. Only a checkout that recorded that placement is
    inspected; a fresh setup needs no Docker call here. Durable history and the RAG index were
    always bind-mounted from ``HOST_DIRECTORY`` and are untouched.
    """
    if RETIRED_PROJECTION_DIRECTORY.exists():
        project = compose_project_name()
        containers = [
            container
            for service in RETIRED_CONTAINER_SERVICES
            for container in _docker(
                "ps",
                "--all",
                "--quiet",
                "--filter",
                f"label=com.docker.compose.project={project}",
                "--filter",
                f"label=com.docker.compose.service={service}",
            ).splitlines()
            if container.strip()
        ]
        if containers:
            _docker("stop", "--time", "35", *containers)
            _docker("rm", *containers)
        # The projection held copies of the service tokens; nothing reads it any more.
        shutil.rmtree(RETIRED_PROJECTION_DIRECTORY)
        print(
            "Retired the Docker AI placement: AI-mode, MCP and RAG now run only as host processes.",
            flush=True,
        )
    RETIRED_PLACEMENT_STATE.unlink(missing_ok=True)


def migrate_legacy_state() -> None:
    """Snapshot the old exclusive SQLite store before first host use, never overwrite."""
    destination = HOST_DIRECTORY / "ai-mode" / "agent-state.sqlite3"
    if destination.exists():
        return
    project = compose_project_name()
    volumes = _docker(
        "volume",
        "ls",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--filter",
        "label=com.docker.compose.volume=shared-ai-mode-state",
        "--format",
        "{{.Name}}",
    ).splitlines()
    if not volumes:
        return
    if len(volumes) != 1:
        raise RuntimeError("Multiple legacy AI state volumes found; resolve the owning stack first")
    # Stop the owning historical process before copying SQLite plus any WAL sidecars.
    containers = _docker(
        "ps",
        "--filter",
        f"volume={volumes[0]}",
        "--format",
        "{{.ID}}",
    ).splitlines()
    for container in containers:
        labels = json.loads(_docker("inspect", "--format", "{{json .Config.Labels}}", container))
        if labels.get("com.docker.compose.project") != project:
            raise RuntimeError("Legacy AI volume is used by another project; refusing migration")
        _docker("stop", "--time", "35", container)
    name = f"propertyscope-state-export-{secrets.token_hex(6)}"
    # The helper is never started. Its only purpose is copying a read-only volume.
    image = "propertyscope/shared-frontend:dev"
    _docker("image", "inspect", image)
    HOST_DIRECTORY.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="legacy-export-", dir=HOST_DIRECTORY) as temporary:
        created = False
        try:
            _docker(
                "create",
                "--name",
                name,
                "--entrypoint",
                "/bin/true",
                "--mount",
                f"type=volume,source={volumes[0]},target=/legacy,readonly",
                image,
            )
            created = True
            _docker("cp", f"{name}:/legacy/.", temporary)
        finally:
            if created:
                _docker("rm", name)
        source = Path(temporary) / "agent-state.sqlite3"
        if source.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            candidate = destination.with_suffix(".migration.sqlite3")
            with (
                closing(sqlite3.connect(source)) as old,
                closing(sqlite3.connect(candidate)) as new,
            ):
                old.backup(new)
                if new.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                    raise RuntimeError("Legacy AI state failed SQLite integrity validation")
            # Hard-link installation fails atomically if another launcher created state.
            os.link(candidate, destination)
            candidate.unlink()
            print("Preserved legacy AI run history in the exclusive host store.", flush=True)


def _catalogues(environment: Mapping[str, str]) -> tuple[str, ...]:
    projection = json.loads(
        (REPOSITORY_ROOT / "deployment/enabled-features.v1.json").read_text(encoding="utf-8")
    )
    paths: list[str] = []
    for feature in projection["features"]:
        ai, frontend = feature.get("ai"), feature.get("frontend")
        if ai is None:
            continue
        if frontend is None:
            raise RuntimeError("Host tool dispatch requires a published feature HTTP entrypoint")
        port = environment.get(frontend["host_port_variable"], str(frontend["host_port_default"]))
        if not port.isdecimal() or not 1 <= int(port) <= 65535:
            raise RuntimeError("Feature HTTP port must be an integer between 1 and 65535")
        catalogue = yaml.safe_load(
            (REPOSITORY_ROOT / ai["tool_catalog"]).read_text(encoding="utf-8")
        )
        for endpoint in catalogue.get("services", []):
            endpoint["base_url"] = f"http://127.0.0.1:{port}"
        path = HOST_DIRECTORY / "catalogues" / f"{feature['feature_key']}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(catalogue, sort_keys=False), encoding="utf-8")
        paths.append(str(path.resolve()))
    return tuple(paths)


def _corpus_scopes() -> tuple[str, ...]:
    """Derive registered RAG scopes from the validated enabled-feature projection.

    Owners register guidance in their own ``feature.yaml``; nothing here is per-feature.
    An empty result is returned as-is; callers that enable RAG must reject it rather than
    leaving the settings unset, because both services would then fall back to their own
    Feature 1 literal and scope a corpus nobody declared.
    """
    projection = DeploymentProjectionV1.model_validate_json(
        (REPOSITORY_ROOT / "deployment/enabled-features.v1.json").read_text(encoding="utf-8")
    )
    scopes = projection.corpus_scopes()
    for feature in projection.features:
        if feature.ai is None or feature.ai.rag_corpus is None:
            continue
        if not (REPOSITORY_ROOT / feature.ai.rag_corpus).is_file():
            raise RuntimeError(
                f"{feature.feature_key} declares a missing corpus manifest: {feature.ai.rag_corpus}"
            )
    return scopes


def ai_service_token(environment: Mapping[str, str]) -> str:
    """Return the dedicated host entry credential shared only with backend proxies."""
    value = environment.get("AI_MODE_SERVICE_TOKEN", "")
    if not value:
        HOST_DIRECTORY.mkdir(parents=True, exist_ok=True)
        path = HOST_DIRECTORY / "ai-mode.token"
        if not path.exists():
            with path.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(32))
            os.chmod(path, 0o600)
        value = path.read_text(encoding="utf-8").strip()
    validate_service_token(value)
    return value


def multi_agent_service_token(environment: Mapping[str, str]) -> str:
    """Return the Multi-Agent Server credential shared only with feature backends."""
    value = environment.get("MULTI_AGENT_SERVICE_TOKEN", "")
    if not value:
        HOST_DIRECTORY.mkdir(parents=True, exist_ok=True)
        path = HOST_DIRECTORY / "multi-agent.token"
        if not path.exists():
            with path.open("x", encoding="utf-8") as stream:
                stream.write(secrets.token_urlsafe(32))
            os.chmod(path, 0o600)
        value = path.read_text(encoding="utf-8").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{32,128}", value) is None:
        raise RuntimeError("MULTI_AGENT_SERVICE_TOKEN must contain 32-128 URL-safe characters")
    return value


def _is_ci(environment: Mapping[str, str]) -> bool:
    return environment.get("CI", "").lower() in {"true", "1"}


def prepare_environment(
    environment: Mapping[str, str], *, mode: str = "combined"
) -> dict[str, str]:
    """Build host-only paths/tokens and an explicit local capability selection."""
    validate_capability_mode(mode)
    if _is_ci(environment) and mode != "direct":
        raise RuntimeError("MCP and RAG must remain disabled in CI; use direct mode")
    if environment.get("AI_MODE_ENVIRONMENT", "local") not in {"local", "development"}:
        raise RuntimeError("Managed host AI services are available only for the local deployment")
    result = dict(environment)
    result["AI_MODE_SERVICE_TOKEN"] = ai_service_token(result)
    HOST_DIRECTORY.mkdir(parents=True, exist_ok=True)
    result["AI_MODE_ENVIRONMENT"] = "local"
    result["AI_MODE_DATABASE_PATH"] = str(HOST_DIRECTORY / "ai-mode" / "agent-state.sqlite3")
    result.setdefault("AI_MODE_OPERATIONS_ENABLED", "true")
    result.setdefault("AI_MODE_DEFAULT_MODEL_PROFILE", "remote-standard.v1")
    result["AI_MODE_MCP_ENABLED"] = str(mode in {"mcp", "combined"}).lower()
    result["AI_MODE_RAG_ENABLED"] = str(mode in {"rag", "combined"}).lower()
    result["AI_MODE_TOOL_CATALOG_PATHS"] = ",".join(_catalogues(result))
    result.pop("AI_MODE_TOOL_CATALOG_PATH", None)
    result["MCP_TOOL_CATALOG_PATHS"] = result["AI_MODE_TOOL_CATALOG_PATHS"]
    for service in ("MCP", "RAG"):
        token_path = HOST_DIRECTORY / f"{service.lower()}.token"
        variable = f"{service}_SERVICE_TOKEN"
        if variable not in result:
            if not token_path.exists():
                with token_path.open("x", encoding="utf-8") as stream:
                    stream.write(secrets.token_urlsafe(32))
                os.chmod(token_path, 0o600)
            result[variable] = token_path.read_text(encoding="utf-8").strip()
    result["MCP_SERVER_URL"] = f"http://127.0.0.1:{port_for('mcp', result)}/mcp"
    result["RAG_SERVER_URL"] = f"http://127.0.0.1:{port_for('rag', result)}"
    result.setdefault("RAG_DATABASE_PATH", str(HOST_DIRECTORY / "rag" / "index.sqlite3"))
    result.setdefault("RAG_MODEL_CACHE_PATH", str(HOST_DIRECTORY / "rag" / "models"))
    corpora = ",".join(_corpus_scopes())
    if corpora:
        result.setdefault("RAG_ALLOWED_CORPORA", corpora)
        result.setdefault("AI_MODE_RAG_CORPORA", corpora)
    elif mode in {"rag", "combined"} and not result.get("RAG_ALLOWED_CORPORA"):
        # Leaving these unset would let both services fall back to their own Feature 1
        # literal, scoping retrieval to a corpus no enabled feature declares.
        raise RuntimeError(
            "No enabled feature declares a RAG corpus; add ai.rag_corpus and "
            "ai.rag_corpus_id to a feature.yaml, or start AI in direct or mcp mode"
        )
    projection = DeploymentProjectionV1.model_validate_json(
        (REPOSITORY_ROOT / "deployment/enabled-features.v1.json").read_text(encoding="utf-8")
    )
    official_corpora = ",".join(projection.official_evidence_corpus_scopes())
    if official_corpora:
        result.setdefault("RAG_OFFICIAL_EVIDENCE_CORPORA", official_corpora)
    else:
        result.pop("RAG_OFFICIAL_EVIDENCE_CORPORA", None)
    # The Multi-Agent Server discovers enabled features' workflow manifests itself; its Worker
    # calls tools through MCP when MCP is enabled, otherwise directly from these catalogues.
    result["MULTI_AGENT_SERVICE_TOKEN"] = multi_agent_service_token(result)
    result["MULTI_AGENT_STATE_DIR"] = str(HOST_DIRECTORY / "multi-agent")
    result["MULTI_AGENT_REPOSITORY_ROOT"] = str(REPOSITORY_ROOT)
    result["MULTI_AGENT_TOOL_CATALOG_PATHS"] = result["AI_MODE_TOOL_CATALOG_PATHS"]
    result["MULTI_AGENT_MCP_ENABLED"] = result["AI_MODE_MCP_ENABLED"]
    if _is_ci(result):
        result.pop("AI_MODE_MULTI_AGENT_URL", None)
    else:
        # AI-mode only observes its readiness for the shared status page's capability snapshot.
        result["AI_MODE_MULTI_AGENT_URL"] = f"http://127.0.0.1:{port_for('multi-agent', result)}"
    return result


def selected_services(mode: str, environment: Mapping[str, str]) -> list[str]:
    """Services a capability mode starts, in dependency order (MCP before its clients)."""
    return [
        *(["mcp"] if mode in {"mcp", "combined"} else []),
        *(["rag"] if mode in {"rag", "combined"} else []),
        "ai-mode",
        # Host-only like MCP and RAG: never started in CI, where tests use the testkit fake.
        *([] if _is_ci(environment) else ["multi-agent"]),
    ]


def configuration_fingerprint(resolved: Mapping[str, str]) -> str:
    """Identify a process configuration so capability changes never reuse an old process.

    The launcher's own wait allowance is not service configuration: retrying with a longer
    wait keeps the processes that are already live.
    """
    relevant = {key: value for key, value in resolved.items() if key != READY_TIMEOUT_VARIABLE}
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode()).hexdigest()


def start(environment: Mapping[str, str], *, mode: str = "combined") -> None:
    """Start managed services, waiting for bounded health without implicit model downloads."""
    # Reject a malformed wait override before creating state or stopping anything.
    ready_timeout("ai-mode", environment)
    resolved = prepare_environment(environment, mode=mode)
    selected = selected_services(mode, resolved)
    fingerprint = configuration_fingerprint(resolved)
    stop(tuple(service for service in SERVICES if service not in selected))
    started: list[str] = []
    try:
        for service in selected:
            if _owned_process(service) is not None:
                state = json.loads((HOST_DIRECTORY / f"{service}.json").read_text(encoding="utf-8"))
                if state.get("configuration_hash") == fingerprint:
                    _wait_ready(service, resolved)
                    continue
                stop((service,))
            port = port_for(service, resolved)
            if not port_is_free(port):
                variable = PORTS[service][0]
                raise RuntimeError(
                    f"Host {service} port {port} ({variable}) is already in use by "
                    f"{port_owner(port)}. Stop that process (for another checkout, run "
                    f"`uv run scripts/dev.py ai stop` there) or set {variable} to a free port."
                )
            command = [sys.executable, "-m", "scripts.devtools.host_runtime", "serve", service]
            log_path = HOST_DIRECTORY / f"{service}.log"
            log_offset = log_path.stat().st_size if log_path.exists() else 0
            with log_path.open("ab") as log:
                process = subprocess.Popen(  # noqa: S603 - fixed docker/python argv, no shell
                    command,
                    cwd=REPOSITORY_ROOT,
                    env=resolved,
                    stdin=subprocess.DEVNULL,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    start_new_session=os.name != "nt",
                )
            owned = psutil.Process(process.pid)
            _write_json(
                HOST_DIRECTORY / f"{service}.json",
                {
                    "pid": process.pid,
                    "created_at": owned.create_time(),
                    "command": owned.cmdline(),
                    "configuration_hash": fingerprint,
                    "checkout": str(REPOSITORY_ROOT.resolve()),
                },
            )
            started.append(service)
            _wait_ready(service, resolved, log_offset=log_offset)
    except Exception:
        stop(started)
        raise


def ready_timeout(service: str, environment: Mapping[str, str]) -> int:
    """Seconds to wait for one service: the shared override, or that service's default."""
    raw = environment.get(READY_TIMEOUT_VARIABLE, "").strip()
    if not raw:
        return DEFAULT_READY_TIMEOUTS[service]
    if not raw.isdecimal() or not 1 <= int(raw) <= MAXIMUM_READY_TIMEOUT:
        raise RuntimeError(
            f"{READY_TIMEOUT_VARIABLE} must be a whole number of seconds between 1 and "
            f"{MAXIMUM_READY_TIMEOUT}"
        )
    return int(raw)


def _log_excerpt(service: str, offset: int | None) -> str:
    """Return the last lines this launch wrote, or the newest lines for a reused process."""
    path = HOST_DIRECTORY / f"{service}.log"
    if not path.exists():
        return ""
    size = path.stat().st_size
    start = max(size - 65_536, offset if offset is not None and offset <= size else 0)
    with path.open("rb") as stream:
        stream.seek(start)
        lines = stream.read().decode("utf-8", errors="replace").splitlines()
    tail = [line for line in lines if line.strip()][-FAILURE_LOG_LINES:]
    if not tail:
        return ""
    return f"\nLast {service} log lines ({path}):\n" + "\n".join(f"  {line}" for line in tail)


def _service_headers(service: str, environment: Mapping[str, str]) -> dict[str, str]:
    """Authentication for a health request; MCP, RAG and Multi-Agent use bearer tokens."""
    if service == "ai-mode":
        token = environment.get("AI_MODE_SERVICE_TOKEN", "")
        return {AI_SERVICE_TOKEN_HEADER: token} if token else {}
    token = environment.get(f"{service.upper().replace('-', '_')}_SERVICE_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _wait_ready(
    service: str,
    environment: Mapping[str, str],
    *,
    log_offset: int | None = None,
    transport: httpx.BaseTransport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Wait for liveness, say what is slow, and show this launch's log when it fails."""
    port = port_for(service, environment)
    url = f"http://127.0.0.1:{port}" + ("/health" if service == "mcp" else "/health/live")
    headers = {} if service == "ai-mode" else _service_headers(service, environment)
    timeout = ready_timeout(service, environment)
    began = clock()
    deadline = began + timeout
    announced = False
    next_steps = (
        f"Inspect `uv run scripts/dev.py ai logs {service}`. Give a slow first start longer with "
        f"{READY_TIMEOUT_VARIABLE}=<seconds> (this wait was {timeout} s), then rerun the same "
        "command."
    )
    with httpx.Client(timeout=1, follow_redirects=False, transport=transport) as client:
        while True:
            if _owned_process(service) is None:
                raise RuntimeError(
                    f"Host {service} exited before it became live on 127.0.0.1:{port}."
                    + _log_excerpt(service, log_offset)
                    + f"\n{next_steps}"
                )
            try:
                if client.get(url, headers=headers).status_code == 200:
                    print(
                        f"Host {service:<11} live on 127.0.0.1:{port} after "
                        f"{clock() - began:.1f} s",
                        flush=True,
                    )
                    return
            except httpx.HTTPError:
                pass
            now = clock()
            if now >= deadline:
                break
            if not announced and now - began >= WAIT_NOTICE_AFTER:
                print(
                    f"Waiting for host {service} on 127.0.0.1:{port} (up to {timeout} s; "
                    f"follow it with `uv run scripts/dev.py ai logs {service}`)...",
                    flush=True,
                )
                announced = True
            sleep(0.2)
    raise RuntimeError(
        f"Host {service} did not become live on 127.0.0.1:{port} within {timeout} seconds."
        + _log_excerpt(service, log_offset)
        + f"\n{next_steps}"
    )


def serve(service: str) -> None:
    """Foreground entrypoint; AI-mode and the Multi-Agent Server accept host-gateway traffic.

    Both authenticate every non-liveness request with their own service token.
    """
    if os.environ.get("AI_MODE_ENVIRONMENT", "local") not in {"local", "development"}:
        raise RuntimeError("Managed AI services require local deployment")
    if service != "ai-mode" and os.environ.get("CI", "").lower() in {"true", "1"}:
        raise RuntimeError("MCP, RAG and the Multi-Agent Server must remain disabled in CI")
    if service == "mcp":
        import runpy

        runpy.run_module("mcp_server", run_name="__main__")
        return
    from waitress import serve as serve_wsgi

    if service == "ai-mode":
        from ai_mode import create_app as create_ai_app

        application = create_ai_app()
        protect_host_entry(application, os.environ.get("AI_MODE_SERVICE_TOKEN", ""))
    elif service == "multi-agent":
        from multi_agent_server import create_app as create_multi_agent_app

        application = create_multi_agent_app()
    else:
        from rag_server import create_app as create_rag_app

        application = create_rag_app()
    serve_wsgi(
        application,
        host=bind_host(service),
        port=port_for(service, os.environ),
        threads=8,
    )


def serve_in_terminal(
    service: str,
    *,
    environment: Mapping[str, str],
    log_path: Path | None = None,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
    out: IO[str] = sys.stdout,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Run one host service in this terminal (``dev.py ai serve``), teeing it to its host log.

    ``environment`` is the prepared environment ``start`` would give the service, so the
    existing tokens, state paths and catalogues apply and the containers reach it unchanged.
    Appending to the managed log keeps ``ai logs`` and the local deployment capture working
    whichever way the service was started.
    """
    port = port_for(service, environment)
    if not port_is_free(port):
        print(
            f"Port {port} is in use by {port_owner(port)}. Stop the managed "
            f"process first: uv run scripts/dev.py ai stop {service}",
            file=sys.stderr,
        )
        return 1
    log_path = log_path or HOST_DIRECTORY / f"{service}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    command = [sys.executable, "-m", "scripts.devtools.host_runtime", "serve", service]
    with log_path.open("ab") as log:
        process = popen(
            command,
            cwd=REPOSITORY_ROOT,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        banner = (
            f"=== {service} serving in the foreground on port {port}, PID {process.pid}, "
            f"started {clock().isoformat(timespec='seconds')} (Ctrl+C stops it) ===\n"
        )
        log.write(banner.encode("utf-8"))
        out.write(banner)
        try:
            for raw in process.stdout or ():
                log.write(raw)
                log.flush()
                out.write(raw.decode("utf-8", "replace"))
                out.flush()
        except KeyboardInterrupt:
            process.terminate()
        return process.wait(timeout=15)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "serve" or sys.argv[2] not in SERVICES:
        raise SystemExit(
            "Usage: python -m scripts.devtools.host_runtime serve " + "|".join(SERVICES)
        )
    serve(sys.argv[2])
