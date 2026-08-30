"""Tests for feature-manifest ownership of enabled HTTP tool catalogues."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.validate_tool_catalogs import validate_catalog_ownership

from ai_mode.tool_catalog import ServiceEndpoint, ToolCatalog, load_tool_catalog
from shared_contracts import load_feature_manifest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = load_feature_manifest(ROOT / "student-1" / "feature.yaml")
CATALOG = load_tool_catalog(ROOT / "student-1" / "tool-catalog.yaml")


def test_current_catalogue_matches_its_feature_manifest() -> None:
    validate_catalog_ownership(CATALOG, MANIFEST)


def test_catalogue_rejects_mismatched_tool_feature_key() -> None:
    registration = CATALOG.tools[0]
    invalid = ToolCatalog(
        services=CATALOG.services,
        tools=(
            registration.model_copy(
                update={
                    "definition": registration.definition.evolve(
                        feature_key="student-2-unowned"
                    )
                }
            ),
        ),
    )

    with pytest.raises(ValueError, match="feature_key"):
        validate_catalog_ownership(invalid, MANIFEST)


@pytest.mark.parametrize("base_url", ["http://other-backend:5201", "http://f1-backend:9999"])
def test_catalogue_rejects_arbitrary_service_host_or_port(base_url: str) -> None:
    invalid_endpoint = ServiceEndpoint(
        service=CATALOG.services[0].service,
        base_url=base_url,
    )
    invalid = CATALOG.model_copy(update={"services": (invalid_endpoint,)})

    with pytest.raises(ValueError, match="exactly match"):
        validate_catalog_ownership(invalid, MANIFEST)


def test_catalogue_rejects_unowned_tool_path() -> None:
    registration = CATALOG.tools[0].model_copy(update={"path": "/api/another/v1/tool"})
    invalid = ToolCatalog(services=CATALOG.services, tools=(registration,))

    with pytest.raises(ValueError, match="owned backend route namespace"):
        validate_catalog_ownership(invalid, MANIFEST)


@pytest.mark.parametrize(
    "path",
    [
        "/api/data-platform/v1/%2e%2e/another/tool",
        "/api/data-platform/v1/../another/tool",
        "/api/data-platform/v1//tools/sources.list.v1",
        "/api/data-platform/v1/tools/sources.list.v1?mode=unsafe",
    ],
)
def test_catalogue_rejects_encoded_or_noncanonical_tool_path(path: str) -> None:
    registration = CATALOG.tools[0].model_copy(update={"path": path})
    invalid = ToolCatalog(services=CATALOG.services, tools=(registration,))

    with pytest.raises(ValueError, match="unencoded canonical"):
        validate_catalog_ownership(invalid, MANIFEST)


def test_catalogue_rejects_unused_service_endpoint() -> None:
    unused = ServiceEndpoint(service="unused-backend", base_url="http://f1-backend:5201")
    invalid = CATALOG.model_copy(update={"services": (*CATALOG.services, unused)})

    with pytest.raises(ValueError, match="used exactly"):
        validate_catalog_ownership(invalid, MANIFEST)
