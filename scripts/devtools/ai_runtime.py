"""Select AI placement without duplicating durable stores or feature contracts."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from scripts.devtools import host_runtime
from scripts.devtools.config import REPOSITORY_ROOT, RUNTIME_DIRECTORY
from scripts.devtools.runtime_settings import (
    AI_CAPABILITY_MODES,
    AI_CONTAINER_SERVICES,
    AI_PLACEMENTS,
    AI_SERVICE_PORTS,
    validate_capability_mode,
)

OVERLAY = "docker-compose.ai.yml"
DOCKER_SERVICES = tuple(AI_CONTAINER_SERVICES.values())
STATE_PATH = RUNTIME_DIRECTORY / "ai-runtime.json"


@dataclass(frozen=True, slots=True)
class RuntimeState:
    """Validated selection; invalid state is never authority to switch database owners."""

    placement: str
    mode: str


def read_state() -> RuntimeState | None:
    """Read saved state with safe diagnostics; absence alone means a fresh setup."""
    try:
        raw = STATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(
            f"Cannot read AI runtime state at {STATE_PATH}; restore a readable file"
        ) from exc
    recovery = (
        f"Invalid saved AI runtime state at {STATE_PATH}; restore a JSON object with the "
        "known placement (host/docker) and mode (direct/mcp/rag/combined). "
        "Verify the active owner before repairing this file; do not delete it to guess a placement."
    )
    try:
        value = json.loads(raw)
    except ValueError as exc:
        raise RuntimeError(recovery) from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"placement", "mode"}
        or not isinstance(value["placement"], str)
        or value["placement"] not in AI_PLACEMENTS
    ):
        raise RuntimeError(recovery)
    if not isinstance(value["mode"], str) or value["mode"] not in AI_CAPABILITY_MODES:
        raise RuntimeError(f"Invalid saved AI capability mode. {recovery}")
    return RuntimeState(placement=value["placement"], mode=value["mode"])


def selection(environment: Mapping[str, str] | None = None) -> str:
    """Explicit environment wins; otherwise remember the last selection or use Docker."""
    values = os.environ if environment is None else environment
    state = read_state()
    selected = values.get("PROPERTYSCOPE_AI_RUNTIME", state.placement if state else "docker")
    if selected not in AI_PLACEMENTS:
        raise RuntimeError("PROPERTYSCOPE_AI_RUNTIME must be docker or host")
    return selected


def remember(placement: str, mode: str) -> None:
    if placement not in AI_PLACEMENTS or mode not in AI_CAPABILITY_MODES:
        raise RuntimeError("Invalid AI runtime selection")
    host_runtime._write_json(STATE_PATH, {"placement": placement, "mode": mode})


def capability_mode() -> str:
    state = read_state()
    return state.mode if state else "combined"


def has_container_configuration() -> bool:
    return (RUNTIME_DIRECTORY / "docker-ai/ai-mode.env").exists()


def require_same_placement() -> None:
    """Environment overrides must never bypass the integrated ownership transition."""
    state = read_state()
    if state is not None and state.placement != selection():
        raise RuntimeError("Change AI placement with stack up --ai-runtime docker|host first")


def services(mode: str = "combined") -> tuple[str, ...]:
    validate_capability_mode(mode)
    return (
        AI_CONTAINER_SERVICES["ai-mode"],
        *((AI_CONTAINER_SERVICES["mcp"],) if mode in {"mcp", "combined"} else ()),
        *((AI_CONTAINER_SERVICES["rag"],) if mode in {"rag", "combined"} else ()),
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
    validate_capability_mode(mode)
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
        MCP_SERVER_URL=f"http://{AI_CONTAINER_SERVICES['mcp']}:{AI_SERVICE_PORTS['mcp'][1]}/mcp",
        RAG_SERVER_URL=f"http://{AI_CONTAINER_SERVICES['rag']}:{AI_SERVICE_PORTS['rag'][1]}",
        RAG_DATABASE_PATH="/var/lib/rag/index.sqlite3",
        RAG_MODEL_CACHE_PATH="/var/lib/rag/models",
    )
    resolved.update({variable: str(default) for variable, default in AI_SERVICE_PORTS.values()})
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
