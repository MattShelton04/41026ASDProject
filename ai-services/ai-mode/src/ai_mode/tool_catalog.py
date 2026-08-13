"""Validated startup composition for feature-owned HTTP tools."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator

from agent_core import ToolRegistrationError, ToolRegistry
from ai_mode.adapters.http_tools import HttpToolBinding, HttpToolExecutor
from shared_contracts import ToolDefinition


class ToolCatalogError(ValueError):
    """The configured tool catalogue is unsafe or internally inconsistent."""


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServiceEndpoint(_CatalogModel):
    """One startup-allowlisted service identity and fixed origin."""

    service: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=100)
    base_url: HttpUrl


class ToolRegistration(_CatalogModel):
    """A tool definition paired with non-model-controlled HTTP transport metadata."""

    definition: ToolDefinition
    service: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$", max_length=100)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE"] = "POST"
    path: str = Field(min_length=2, max_length=300)


class ToolCatalog(_CatalogModel):
    """Versioned declarative catalogue loaded exactly once during startup."""

    schema_version: Literal[1] = 1
    services: tuple[ServiceEndpoint, ...] = ()
    tools: tuple[ToolRegistration, ...] = ()
    shared_tools: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> ToolCatalog:
        service_names = [endpoint.service for endpoint in self.services]
        if len(service_names) != len(set(service_names)):
            raise ValueError("service identities must be unique")
        registered_names = [registration.definition.name for registration in self.tools]
        if len(registered_names) != len(set(registered_names)):
            raise ValueError("tool bindings must be unique")
        unknown = {
            registration.service
            for registration in self.tools
            if registration.service not in service_names
        }
        if unknown:
            raise ValueError(
                f"tool bindings reference unknown services: {', '.join(sorted(unknown))}"
            )
        return self


def load_tool_catalog(path: Path) -> ToolCatalog:
    """Read and validate a YAML catalogue with path-aware startup errors."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ToolCatalogError(f"could not read tool catalogue {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ToolCatalogError(f"tool catalogue {path} must contain a YAML object")
    try:
        return ToolCatalog.model_validate(payload)
    except ValueError as exc:
        raise ToolCatalogError(f"invalid tool catalogue {path}: {exc}") from exc


def compose_tool_catalogs(catalogs: Iterable[ToolCatalog]) -> ToolCatalog:
    """Combine validated catalogues while rejecting all cross-file identity conflicts."""
    selected = tuple(catalogs)
    try:
        return ToolCatalog(
            services=tuple(endpoint for catalog in selected for endpoint in catalog.services),
            tools=tuple(registration for catalog in selected for registration in catalog.tools),
            shared_tools=tuple(
                tool_name for catalog in selected for tool_name in catalog.shared_tools
            ),
        )
    except ValueError as exc:
        raise ToolCatalogError(f"tool catalogue composition failed: {exc}") from exc


def load_tool_catalogs(paths: Iterable[Path]) -> ToolCatalog:
    """Load and compose an ordered set of feature-owned catalogue files."""
    return compose_tool_catalogs(load_tool_catalog(path) for path in paths)


def build_tool_runtime(
    catalog: ToolCatalog,
    *,
    max_request_bytes: int,
    max_response_bytes: int,
) -> tuple[ToolRegistry, HttpToolExecutor]:
    """Compose the registry and transport adapter from one validated source."""
    try:
        registry = ToolRegistry(
            (registration.definition for registration in catalog.tools),
            shared_tools=catalog.shared_tools,
        )
        executor = HttpToolExecutor(
            service_base_urls={
                endpoint.service: str(endpoint.base_url).rstrip("/")
                for endpoint in catalog.services
            },
            bindings=(
                HttpToolBinding(
                    tool_name=registration.definition.name,
                    tool_version=registration.definition.version,
                    service=registration.service,
                    method=registration.method,
                    path=registration.path,
                )
                for registration in catalog.tools
            ),
            max_request_bytes=max_request_bytes,
            max_response_bytes=max_response_bytes,
        )
    except (ToolRegistrationError, ValueError) as exc:
        raise ToolCatalogError(f"tool runtime composition failed: {exc}") from exc
    return registry, executor
