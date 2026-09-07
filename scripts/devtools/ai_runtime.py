"""Select AI placement without duplicating durable stores or feature contracts."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from pathlib import Path

from scripts.devtools import host_runtime
from scripts.devtools.config import REPOSITORY_ROOT, RUNTIME_DIRECTORY

OVERLAY = "docker-compose.ai.yml"
DOCKER_SERVICES = ("shared-ai-mode", "mcp-server", "rag-server")
STATE_PATH = RUNTIME_DIRECTORY / "ai-runtime.json"


def selection(environment: Mapping[str, str] | None = None) -> str:
    """Explicit environment wins; otherwise remember the last selection or use Docker."""
    values = os.environ if environment is None else environment
    selected = values.get("PROPERTYSCOPE_AI_RUNTIME")
    if selected is None and STATE_PATH.exists():
        selected = json.loads(STATE_PATH.read_text(encoding="utf-8"))["placement"]
    selected = selected or "docker"
    if selected not in {"host", "docker"}:
        raise RuntimeError("PROPERTYSCOPE_AI_RUNTIME must be docker or host")
    return selected


def remember(placement: str, mode: str) -> None:
    if placement not in {"host", "docker"} or mode not in {"direct", "mcp", "rag", "combined"}:
        raise RuntimeError("Invalid AI runtime selection")
    host_runtime._write_json(STATE_PATH, {"placement": placement, "mode": mode})


def capability_mode() -> str:
    if STATE_PATH.exists():
        mode = str(json.loads(STATE_PATH.read_text(encoding="utf-8"))["mode"])
        if mode not in {"direct", "mcp", "rag", "combined"}:
            raise RuntimeError("Invalid saved AI capability mode")
        return mode
    return "combined"


def has_container_configuration() -> bool:
    return (RUNTIME_DIRECTORY / "docker-ai/ai-mode.env").exists()


def require_same_placement() -> None:
    """Environment overrides must never bypass the integrated ownership transition."""
    if STATE_PATH.exists():
        saved = json.loads(STATE_PATH.read_text(encoding="utf-8"))["placement"]
        if saved != selection():
            raise RuntimeError("Change AI placement with stack up --ai-runtime docker|host first")


def services(mode: str = "combined") -> tuple[str, ...]:
    if mode not in {"direct", "mcp", "rag", "combined"}:
        raise RuntimeError("Invalid AI capability mode")
    return (
        "shared-ai-mode",
        *(("mcp-server",) if mode in {"mcp", "combined"} else ()),
        *(("rag-server",) if mode in {"rag", "combined"} else ()),
    )


def _write_environment(path: Path, values: Mapping[str, str]) -> None:
    # Compose single quotes retain literal dollars. Multiline values are unnecessary here.
    lines = []
    for key, value in sorted(values.items()):
        if any(character in value for character in "\r\n'"):
            raise RuntimeError(f"Unsupported multiline or quoted runtime setting: {key}")
        lines.append(f"{key}='{value}'")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def prepare(environment: Mapping[str, str], *, mode: str) -> dict[str, str]:
    """Project private container configuration; data remains in its existing owner directory."""
    for setting, expected in (
        ("RAG_DATABASE_PATH", host_runtime.HOST_DIRECTORY / "rag/index.sqlite3"),
        ("RAG_MODEL_CACHE_PATH", host_runtime.HOST_DIRECTORY / "rag/models"),
    ):
        if setting in environment and Path(environment[setting]).resolve() != expected.resolve():
            raise RuntimeError(
                f"Docker AI uses the canonical shared {setting}; "
                "keep host placement for custom paths"
            )
    for setting in ("AI_MODE_MODEL_REGISTRY_PATH", "AI_MODE_OPERATIONS_ASSETS_PATH"):
        if environment.get(setting):
            raise RuntimeError(f"Docker AI uses bundled assets; keep host placement for {setting}")
    resolved = host_runtime.prepare_environment(environment, mode=mode)
    directory = RUNTIME_DIRECTORY / "docker-ai"
    catalogues = directory / "catalogues"
    catalogues.mkdir(parents=True, exist_ok=True)
    projection = json.loads(
        (REPOSITORY_ROOT / "deployment/enabled-features.v1.json").read_text(encoding="utf-8")
    )
    paths = []
    for feature in projection["features"]:
        if ai := feature.get("ai"):
            filename = f"{feature['feature_key']}.yaml"
            shutil.copyfile(REPOSITORY_ROOT / ai["tool_catalog"], catalogues / filename)
            paths.append(f"/etc/propertyscope/catalogues/{filename}")
    for owner in ("ai-mode", "rag"):
        (host_runtime.HOST_DIRECTORY / owner).mkdir(parents=True, exist_ok=True)
    resolved.update(
        AI_MODE_ENVIRONMENT="compose",
        AI_MODE_DATABASE_PATH="/var/lib/ai-mode/agent-state.sqlite3",
        AI_MODE_TOOL_CATALOG_PATHS=",".join(paths),
        MCP_TOOL_CATALOG_PATHS=",".join(paths),
        MCP_SERVER_URL="http://mcp-server:5011/mcp",
        RAG_SERVER_URL="http://rag-server:5012",
        RAG_DATABASE_PATH="/var/lib/rag/index.sqlite3",
        RAG_MODEL_CACHE_PATH="/var/lib/rag/models",
        AI_MODE_PORT="5005",
        MCP_PORT="5011",
        RAG_PORT="5012",
    )
    for provider in ("OPENAI", "GEMINI"):
        resolved.pop(f"{provider}_API_KEY", None)
        resolved[f"{provider}_API_KEY_FILE"] = "/run/secrets/model_provider_key"
    # Only AI-mode receives provider settings. MCP and RAG get their own bounded configuration.
    prefixes = {
        "ai-mode": ("AI_MODE_", "OPENAI_", "GEMINI_", "MCP_", "RAG_"),
        "mcp": ("MCP_",),
        "rag": ("RAG_",),
    }
    for service, allowed in prefixes.items():
        values = {key: value for key, value in resolved.items() if key.startswith(allowed)}
        values["AI_MODE_ENVIRONMENT"] = "compose"
        if "CI" in resolved:
            values["CI"] = resolved["CI"]
        _write_environment(directory / f"{service}.env", values)
    result = dict(environment)
    result["AI_MODE_SERVICE_TOKEN"] = resolved["AI_MODE_SERVICE_TOKEN"]
    result["PROPERTYSCOPE_AI_UID"] = str(os.getuid() if hasattr(os, "getuid") else 10001)
    result["PROPERTYSCOPE_AI_GID"] = str(os.getgid() if hasattr(os, "getgid") else 10001)
    return result
