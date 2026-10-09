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
from collections.abc import Mapping, Sequence
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

import httpx
import psutil
import yaml

from scripts.devtools.config import REPOSITORY_ROOT, RUNTIME_DIRECTORY, compose_project_name
from scripts.devtools.runtime_settings import AI_SERVICE_PORTS, validate_capability_mode
from scripts.devtools.service_auth import protect_entry as protect_host_entry
from scripts.devtools.service_auth import validate_service_token
from shared_contracts.deployment import DeploymentProjectionV1

HOST_DIRECTORY = RUNTIME_DIRECTORY / "host"
SERVICES = tuple(AI_SERVICE_PORTS)
PORTS = AI_SERVICE_PORTS
# Left behind by the retired Docker AI placement (ADR-044, superseded by ADR-046).
RETIRED_CONTAINER_SERVICES = ("shared-ai-mode", "mcp-server", "rag-server")
RETIRED_PROJECTION_DIRECTORY = RUNTIME_DIRECTORY / "docker-ai"
RETIRED_PLACEMENT_STATE = RUNTIME_DIRECTORY / "ai-runtime.json"


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


def status(environment: Mapping[str, str] | None = None) -> list[dict[str, object]]:
    """Return process state and local URLs without exposing configuration or credentials."""
    values = os.environ if environment is None else environment
    return [
        {
            "service": service,
            "state": "running" if _owned_process(service) else "stopped",
            "url": local_url(service, values),
        }
        for service in SERVICES
    ]


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
    return subprocess.run(
        ("docker", *arguments),
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


def start(environment: Mapping[str, str], *, mode: str = "combined") -> None:
    """Start managed services, waiting for bounded health without implicit model downloads."""
    resolved = prepare_environment(environment, mode=mode)
    selected = selected_services(mode, resolved)
    # Capability changes must not accidentally reuse an older AI process configuration.
    fingerprint = hashlib.sha256(json.dumps(resolved, sort_keys=True).encode()).hexdigest()
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
            with socket.socket() as probe:
                try:
                    probe.bind(("127.0.0.1", port))
                except OSError as exc:
                    raise RuntimeError(
                        f"Host {service} port {port} is occupied by an unmanaged process"
                    ) from exc
            command = [sys.executable, "-m", "scripts.devtools.host_runtime", "serve", service]
            log_path = HOST_DIRECTORY / f"{service}.log"
            with log_path.open("ab") as log:
                process = subprocess.Popen(
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
            _wait_ready(service, resolved)
    except Exception:
        stop(started)
        raise


def _wait_ready(service: str, environment: Mapping[str, str]) -> None:
    port = port_for(service, environment)
    path = "/health" if service == "mcp" else "/health/live"
    headers = (
        {}
        if service == "ai-mode"
        else {
            "Authorization": "Bearer "
            + environment[f"{service.upper().replace('-', '_')}_SERVICE_TOKEN"]
        }
    )
    deadline = time.monotonic() + 30
    with httpx.Client(timeout=1, follow_redirects=False) as client:
        while time.monotonic() < deadline:
            if _owned_process(service) is None:
                raise RuntimeError(
                    f"Host {service} exited; inspect `uv run scripts/dev.py ai logs {service}`"
                )
            try:
                if client.get(f"http://127.0.0.1:{port}{path}", headers=headers).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
    raise RuntimeError(f"Host {service} did not become live within 30 seconds")


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
        host="0.0.0.0" if service in {"ai-mode", "multi-agent"} else "127.0.0.1",
        port=port_for(service, os.environ),
        threads=8,
    )


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "serve" or sys.argv[2] not in SERVICES:
        raise SystemExit(
            "Usage: python -m scripts.devtools.host_runtime serve " + "|".join(SERVICES)
        )
    serve(sys.argv[2])
