"""Tests for fail-fast declarative HTTP tool startup composition."""

from pathlib import Path

import pytest

from ai_mode.tool_catalog import (
    ToolCatalog,
    ToolCatalogError,
    build_tool_runtime,
    compose_tool_catalogs,
    load_tool_catalog,
    load_tool_catalogs,
)

PROPERTYSCOPE_CATALOG = Path(__file__).resolve().parents[3] / "student-1" / "tool-catalog.yaml"


def test_product_catalog_composes_scoped_tools() -> None:
    catalog = load_tool_catalog(PROPERTYSCOPE_CATALOG)

    registry, executor = build_tool_runtime(
        catalog,
        max_request_bytes=10_000,
        max_response_bytes=10_000,
    )

    assert [
        definition.name
        for definition in registry.definitions_for("student-1-propertyscope-data-platform")
    ] == [
        "platform.capabilities.v1",
        "data.sources.v1",
        "data.runs.v1",
        "data.release_inspect.v1",
        "data.run_inspect.v1",
        "data.release_compare.v1",
        "data.coverage.v1",
        "property.search.v1",
        "property.inspect.v1",
        "data.run_retry.v1",
        "data.release_publish.v1",
    ]
    assert registry.definitions_for("student-2-feature") == ()
    executor.close()


def test_catalog_rejects_unsafe_model_escaping_paths(tmp_path: Path) -> None:
    payload = PROPERTYSCOPE_CATALOG.read_text(encoding="utf-8").replace(
        "/api/data-platform/v1/tools/sources.list.v1",
        "//untrusted.example/tool",
    )
    path = tmp_path / "unsafe.yaml"
    path.write_text(payload, encoding="utf-8")

    catalog = load_tool_catalog(path)
    with pytest.raises(ToolCatalogError, match="unsafe"):
        build_tool_runtime(catalog, max_request_bytes=1_000, max_response_bytes=1_000)


def test_catalog_loader_composes_product_runtime() -> None:
    catalog = load_tool_catalogs((PROPERTYSCOPE_CATALOG,))
    registry, executor = build_tool_runtime(
        catalog,
        max_request_bytes=10_000,
        max_response_bytes=10_000,
    )

    assert registry.definitions_for("student-1-propertyscope-data-platform")
    executor.close()


def test_catalog_composition_rejects_duplicate_service_identity() -> None:
    catalog = load_tool_catalog(PROPERTYSCOPE_CATALOG)
    duplicate_service = ToolCatalog(services=(catalog.services[0],))

    with pytest.raises(ToolCatalogError, match="service identities must be unique"):
        compose_tool_catalogs((catalog, duplicate_service))


def test_catalog_composition_rejects_duplicate_tool_binding() -> None:
    catalog = load_tool_catalog(PROPERTYSCOPE_CATALOG)
    original = catalog.tools[0]
    second_service = catalog.services[0].model_copy(update={"service": "another-feature-backend"})
    duplicate_tool = ToolCatalog(
        services=(second_service,),
        tools=(original.model_copy(update={"service": second_service.service}),),
    )

    with pytest.raises(ToolCatalogError, match="tool bindings must be unique"):
        compose_tool_catalogs((catalog, duplicate_tool))
