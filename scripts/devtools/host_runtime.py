"""Managed local AI processes, exclusive state and Docker-to-host projections."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
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

from scripts.devtools.config import DEFAULT_PROJECT_NAME, REPOSITORY_ROOT, RUNTIME_DIRECTORY

HOST_DIRECTORY = RUNTIME_DIRECTORY / "host"
SERVICES = ("ai-mode", "mcp", "rag")
PORTS = {"ai-mode": ("AI_MODE_PORT", 5005), "mcp": ("MCP_PORT", 5011), "rag": ("RAG_PORT", 5012)}


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


def status() -> list[dict[str, object]]:
    """Return process state without exposing configuration or credentials."""
    return [
        {"service": service, "state": "running" if _owned_process(service) else "stopped"}
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


def migrate_legacy_state() -> None:
    """Snapshot the old exclusive SQLite store before first host use, never overwrite."""
    destination = HOST_DIRECTORY / "ai-mode" / "agent-state.sqlite3"
    if destination.exists():
        return
    volumes = _docker(
        "volume",
        "ls",
        "--filter",
        f"label=com.docker.compose.project={DEFAULT_PROJECT_NAME}",
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
        if labels.get("com.docker.compose.project") != DEFAULT_PROJECT_NAME:
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


def prepare_environment(
    environment: Mapping[str, str], *, mode: str = "combined"
) -> dict[str, str]:
    """Build host-only paths/tokens and an explicit local capability selection."""
    if environment.get("CI", "").lower() in {"true", "1"} and mode != "direct":
        raise RuntimeError("MCP and RAG must remain disabled in CI; use direct mode")
    if environment.get("AI_MODE_ENVIRONMENT", "local") not in {"local", "development"}:
        raise RuntimeError("Managed host AI services are available only for the local deployment")
    result = dict(environment)
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
    result.setdefault("RAG_MODEL_CACHE_PATH", str(HOST_DIRECTORY / "models"))
    corpora = "student-1-propertyscope-data-platform:operator-guidance"
    result.setdefault("RAG_ALLOWED_CORPORA", corpora)
    result.setdefault("AI_MODE_RAG_CORPORA", corpora)
    return result


def start(environment: Mapping[str, str], *, mode: str = "combined") -> None:
    """Start managed services, waiting for bounded health without implicit model downloads."""
    resolved = prepare_environment(environment, mode=mode)
    selected = [
        *(["mcp"] if mode in {"mcp", "combined"} else []),
        *(["rag"] if mode in {"rag", "combined"} else []),
        "ai-mode",
    ]
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
        else {"Authorization": f"Bearer {environment[f'{service.upper()}_SERVICE_TOKEN']}"}
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
    """Foreground entrypoint; only AI-mode needs to accept Docker host-gateway traffic."""
    if os.environ.get("AI_MODE_ENVIRONMENT", "local") not in {"local", "development"}:
        raise RuntimeError("Managed AI services require local deployment")
    if service != "ai-mode" and os.environ.get("CI", "").lower() in {"true", "1"}:
        raise RuntimeError("MCP and RAG must remain disabled in CI")
    if service == "mcp":
        import runpy

        runpy.run_module("mcp_server", run_name="__main__")
        return
    from waitress import serve as serve_wsgi

    if service == "ai-mode":
        from ai_mode import create_app as create_ai_app

        application = create_ai_app()
    else:
        from rag_server import create_app as create_rag_app

        application = create_rag_app()
    serve_wsgi(
        application,
        host="0.0.0.0" if service == "ai-mode" else "127.0.0.1",
        port=port_for(service, os.environ),
        threads=8,
    )


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "serve" or sys.argv[2] not in SERVICES:
        raise SystemExit("Usage: python -m scripts.devtools.host_runtime serve ai-mode|mcp|rag")
    serve(sys.argv[2])
