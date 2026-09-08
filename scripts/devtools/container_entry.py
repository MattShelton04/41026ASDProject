"""Foreground service entries for the optional local Docker AI topology."""

from __future__ import annotations

import argparse
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from urllib.request import Request, urlopen

from flask import Flask

from scripts.devtools.runtime_settings import AI_CONTAINER_SERVICES, AI_SERVICE_PORTS
from scripts.devtools.service_auth import protect_entry as protect_entry

PORTS = {service: default for service, (_, default) in AI_SERVICE_PORTS.items()}


def validate_environment(service: str, environment: Mapping[str, str]) -> None:
    """Keep this explicit development alternative separate from cloud and CI."""
    if service not in PORTS:
        raise ValueError("Unknown AI service")
    if environment.get("AI_MODE_ENVIRONMENT") != "compose":
        raise RuntimeError("Container AI services require the local compose environment")
    if environment.get("CI", "").lower() in {"true", "1"} and (
        service != "ai-mode"
        or any(
            environment.get(name, "false").lower() not in {"false", "0"}
            for name in ("AI_MODE_MCP_ENABLED", "AI_MODE_RAG_ENABLED")
        )
    ):
        raise RuntimeError("MCP and RAG must remain disabled in CI")


def create_wsgi_app(service: str) -> Flask:
    """Create one owning WSGI application inside the single Gunicorn worker."""
    validate_environment(service, os.environ)
    if service == "ai-mode":
        from ai_mode import create_app

        application = create_app()
        protect_entry(application, os.environ.get("AI_MODE_SERVICE_TOKEN", ""))
        return application
    if service == "rag":
        from rag_server import create_app as create_rag_app

        return create_rag_app()
    raise ValueError("MCP requires its ASGI entrypoint")


def serve(service: str) -> None:
    """Bind inside the container; Compose owns host exposure and persistent mounts."""
    validate_environment(service, os.environ)
    if service == "mcp":
        import uvicorn
        from mcp_server.server import create_app
        from shared_tool_runtime import load_tool_catalogs

        paths = tuple(
            Path(value.strip())
            for value in os.environ.get("MCP_TOOL_CATALOG_PATHS", "").split(",")
            if value.strip()
        )
        application = create_app(
            load_tool_catalogs(paths),
            service_token=os.environ["MCP_SERVICE_TOKEN"],
            allowed_hosts=(
                "127.0.0.1:*",
                "localhost:*",
                "[::1]:*",
                f"{AI_CONTAINER_SERVICES[service]}:{PORTS[service]}",
            ),
        )
        uvicorn.run(application, host="0.0.0.0", port=PORTS[service])
        return
    # Replacing the entry process lets Gunicorn receive Docker stop signals directly.
    # One worker preserves the AI queue's exclusive ownership of its SQLite store.
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            f"--bind=0.0.0.0:{PORTS[service]}",
            "--workers=1",
            "--threads=8",
            "--timeout=180",
            "--graceful-timeout=35",
            "--access-logfile=-",
            "--error-logfile=-",
            f"scripts.devtools.container_entry:create_wsgi_app('{service}')",
        ],
    )


def health(service: str) -> None:
    """Probe process liveness without requiring provider or embedding readiness."""
    path = "/health" if service == "mcp" else "/health/live"
    headers = (
        {}
        if service == "ai-mode"
        else {"Authorization": f"Bearer {os.environ[f'{service.upper()}_SERVICE_TOKEN']}"}
    )
    probe = Request(f"http://127.0.0.1:{PORTS[service]}{path}", headers=headers)
    with urlopen(probe, timeout=3) as response:
        if response.status != 200:
            raise RuntimeError("AI service liveness probe failed")


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=(*PORTS, "health"))
    parser.add_argument("service", choices=tuple(PORTS), nargs="?")
    args = parser.parse_args(arguments)
    if args.command == "health":
        if args.service is None:
            parser.error("health requires a service")
        health(args.service)
    else:
        if args.service is not None:
            parser.error("the service entry accepts no additional argument")
        serve(args.command)


if __name__ == "__main__":
    main()
