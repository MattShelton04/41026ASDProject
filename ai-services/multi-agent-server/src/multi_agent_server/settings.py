"""Validated environment settings and the composition root."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from shared_tool_runtime import ToolCatalog, build_http_executor, load_tool_catalogs

from multi_agent_server.agents import AgentSettings, StructuredCaller
from multi_agent_server.execution import BoundedExecutor, InlineExecutor, StageExecutor
from multi_agent_server.prompts import PromptRegistry
from multi_agent_server.providers import select_provider
from multi_agent_server.service import WorkflowService
from multi_agent_server.store import WorkflowStore
from multi_agent_server.templates import TemplateRegistry, discover_manifests
from multi_agent_server.tools import (
    CatalogToolGateway,
    FixtureToolGateway,
    ToolGateway,
    UnavailableToolGateway,
)

DEFAULT_PORT = 5013
DEFAULT_STATE_DIRECTORY = Path(".propertyscope-runtime/host/multi-agent")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{32,128}")
ProviderChoice = Literal["auto", "deterministic", "model"]
TransportChoice = Literal["auto", "mcp", "http", "none"]


class SettingsError(ValueError):
    """A setting is invalid before the server starts."""


def validate_token(token: str) -> None:
    """One credential format for issuance (host runtime) and the HTTP entrypoint."""
    if TOKEN_PATTERN.fullmatch(token) is None:
        raise SettingsError("MULTI_AGENT_SERVICE_TOKEN must contain 32-128 URL-safe characters")


@dataclass(frozen=True, slots=True)
class MultiAgentSettings:
    """Everything the server needs; defaults suit a local checkout."""

    token: str | None = field(default=None, repr=False)
    state_directory: Path = DEFAULT_STATE_DIRECTORY
    repository_root: Path = field(default_factory=Path.cwd)
    template_paths: tuple[Path, ...] = ()
    provider: ProviderChoice = "auto"
    model_attempts: int = 2
    model_timeout_seconds: float = 60.0
    model_fallback: Literal["deterministic", "fail"] = "deterministic"
    tool_transport: TransportChoice = "auto"
    tool_catalog_paths: tuple[Path, ...] = ()
    tool_fixture_path: Path | None = None
    mcp_enabled: bool = False
    mcp_server_url: str = "http://127.0.0.1:5011/mcp"
    mcp_service_token: str | None = field(default=None, repr=False)
    workers: int = 2
    queue_capacity: int = 20
    max_request_bytes: int = 65_536
    environment: Mapping[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.token is not None:
            validate_token(self.token)
        if self.provider not in {"auto", "deterministic", "model"}:
            raise SettingsError("MULTI_AGENT_PROVIDER must be auto, deterministic or model")
        if self.tool_transport not in {"auto", "mcp", "http", "none"}:
            raise SettingsError("MULTI_AGENT_TOOL_TRANSPORT must be auto, mcp, http or none")
        if self.model_fallback not in {"deterministic", "fail"}:
            raise SettingsError("MULTI_AGENT_MODEL_FALLBACK must be deterministic or fail")
        if not 1 <= self.model_attempts <= 3:
            raise SettingsError("MULTI_AGENT_MODEL_ATTEMPTS must be between 1 and 3")
        if not 1 <= self.model_timeout_seconds <= 600:
            raise SettingsError("MULTI_AGENT_MODEL_TIMEOUT_SECONDS must be between 1 and 600")
        if not 1 <= self.workers <= 16 or not self.workers <= self.queue_capacity <= 1_000:
            raise SettingsError("MULTI_AGENT_WORKERS must be 1-16 and not exceed the capacity")

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None, *, require_token: bool = True
    ) -> MultiAgentSettings:
        """Read ``MULTI_AGENT_*`` settings (plus the shared MCP and catalogue variables)."""
        values = dict(os.environ if environ is None else environ)
        token = values.get("MULTI_AGENT_SERVICE_TOKEN", "").strip() or None
        if require_token and token is None:
            raise SettingsError("MULTI_AGENT_SERVICE_TOKEN is required to serve the HTTP API")
        catalogs = (
            values.get("MULTI_AGENT_TOOL_CATALOG_PATHS")
            or values.get("MCP_TOOL_CATALOG_PATHS")
            or values.get("AI_MODE_TOOL_CATALOG_PATHS")
            or ""
        )
        fixture = values.get("MULTI_AGENT_TOOL_FIXTURES", "").strip()
        mcp_flag = values.get("MULTI_AGENT_MCP_ENABLED", values.get("AI_MODE_MCP_ENABLED", "false"))
        try:
            return cls(
                token=token,
                state_directory=Path(
                    values.get("MULTI_AGENT_STATE_DIR", str(DEFAULT_STATE_DIRECTORY))
                ),
                repository_root=Path(values.get("MULTI_AGENT_REPOSITORY_ROOT", str(Path.cwd()))),
                template_paths=_paths(values.get("MULTI_AGENT_TEMPLATE_PATHS", "")),
                provider=cast(ProviderChoice, values.get("MULTI_AGENT_PROVIDER", "auto")),
                model_attempts=int(values.get("MULTI_AGENT_MODEL_ATTEMPTS", "2")),
                model_timeout_seconds=float(values.get("MULTI_AGENT_MODEL_TIMEOUT_SECONDS", "60")),
                model_fallback=cast(
                    Literal["deterministic", "fail"],
                    values.get("MULTI_AGENT_MODEL_FALLBACK", "deterministic"),
                ),
                tool_transport=cast(
                    TransportChoice, values.get("MULTI_AGENT_TOOL_TRANSPORT", "auto")
                ),
                tool_catalog_paths=_paths(catalogs),
                tool_fixture_path=Path(fixture) if fixture else None,
                mcp_enabled=mcp_flag.strip().lower() in {"1", "true", "yes"},
                mcp_server_url=values.get("MCP_SERVER_URL", "http://127.0.0.1:5011/mcp"),
                mcp_service_token=values.get("MCP_SERVICE_TOKEN") or None,
                workers=int(values.get("MULTI_AGENT_WORKERS", "2")),
                queue_capacity=int(values.get("MULTI_AGENT_QUEUE_CAPACITY", "20")),
                environment=values,
            )
        except ValueError as exc:
            if isinstance(exc, SettingsError):
                raise
            raise SettingsError(f"Invalid multi-agent setting: {exc}") from exc


def _paths(value: str) -> tuple[Path, ...]:
    return tuple(Path(part.strip()) for part in value.split(",") if part.strip())


def build_gateway(settings: MultiAgentSettings) -> ToolGateway:
    """Choose the tool transport: fixture, MCP, direct HTTP, or none."""
    if settings.tool_fixture_path is not None:
        return FixtureToolGateway.from_file(settings.tool_fixture_path)
    explicit = bool(settings.tool_catalog_paths)
    catalog = load_tool_catalogs(settings.tool_catalog_paths) if explicit else _discovered(settings)
    transport = settings.tool_transport
    if transport == "auto":
        if settings.mcp_enabled and settings.mcp_service_token:
            transport = "mcp"
        elif explicit and catalog.tools:
            transport = "http"
        else:
            transport = "none"
    definitions = [registration.definition for registration in catalog.tools]
    if transport == "mcp":
        from ai_mode.adapters.mcp_tools import McpToolExecutor

        if not settings.mcp_service_token:
            raise SettingsError("MCP tool transport requires MCP_SERVICE_TOKEN")
        executor = McpToolExecutor(
            base_url=settings.mcp_server_url, service_token=settings.mcp_service_token
        )
        return CatalogToolGateway(catalog, executor, transport="mcp")
    if transport == "http":
        return CatalogToolGateway(catalog, build_http_executor(catalog), transport="http")
    return UnavailableToolGateway(
        definitions,
        reason="No tool transport is configured; start the host AI tier (MCP) or use fixtures",
    )


def _discovered(settings: MultiAgentSettings) -> ToolCatalog:
    """Definitions only, from enabled features' catalogues (container URLs are not used)."""
    projection = settings.repository_root / "deployment" / "enabled-features.v1.json"
    try:
        features = json.loads(projection.read_text(encoding="utf-8")).get("features", [])
    except (OSError, ValueError):
        return ToolCatalog()
    paths = [
        settings.repository_root / feature["ai"]["tool_catalog"]
        for feature in features
        if isinstance(feature, dict) and isinstance(feature.get("ai"), dict)
    ]
    try:
        return load_tool_catalogs(path for path in paths if path.is_file())
    except ValueError:
        return ToolCatalog()


def build_registry(settings: MultiAgentSettings) -> TemplateRegistry:
    """Explicit template paths win; otherwise discover enabled features' manifests."""
    root = settings.repository_root
    if settings.template_paths:
        return TemplateRegistry.from_paths(settings.template_paths, root=root)
    discovered = discover_manifests(root)
    return TemplateRegistry.from_paths(
        [path for path, _ in discovered],
        root=root,
        expected_features=dict(discovered),
    )


def build_service(
    settings: MultiAgentSettings, *, inline: bool = False, gateway: ToolGateway | None = None
) -> WorkflowService:
    """Compose the store, gateway, templates, provider and executor."""
    resolved_gateway = gateway or build_gateway(settings)
    selection = select_provider(settings.environment, requested=settings.provider)
    caller = StructuredCaller(
        selection.provider,
        mode=selection.mode,
        model_profile=selection.model_profile,
        settings=AgentSettings(
            model_attempts=settings.model_attempts,
            model_timeout_seconds=settings.model_timeout_seconds,
            fallback=settings.model_fallback,
        ),
        prompts=PromptRegistry(),
    )
    executor: StageExecutor = (
        InlineExecutor()
        if inline
        else BoundedExecutor(workers=settings.workers, capacity=settings.queue_capacity)
    )
    return WorkflowService(
        registry=build_registry(settings),
        store=WorkflowStore(settings.state_directory),
        gateway=resolved_gateway,
        caller=caller,
        executor=executor,
    )
