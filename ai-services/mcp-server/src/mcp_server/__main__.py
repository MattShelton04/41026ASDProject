"""Foreground entrypoint for the local shared MCP service."""

import os
from pathlib import Path

import uvicorn
from shared_tool_runtime import load_tool_catalogs

from mcp_server.server import create_app


def main() -> None:
    """Start the SDK ASGI transport with explicit startup-only catalogue paths."""
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("MCP_HOST must be loopback")
    paths = tuple(
        Path(value.strip())
        for value in os.environ.get("MCP_TOOL_CATALOG_PATHS", "").split(",")
        if value.strip()
    )
    app = create_app(load_tool_catalogs(paths), service_token=os.environ["MCP_SERVICE_TOKEN"])
    uvicorn.run(app, host=host, port=int(os.environ.get("MCP_PORT", "5011")))


if __name__ == "__main__":
    main()
