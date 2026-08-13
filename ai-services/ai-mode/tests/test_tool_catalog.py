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

EXAMPLE_CATALOG = (
    Path(__file__).resolve().parents[3]
    / "examples"
    / "integration-test-feature"
    / "tool-catalog.yaml"
)


def test_example_catalog_composes_scoped_immutable_tools() -> None:
    catalog = load_tool_catalog(EXAMPLE_CATALOG)

    registry, executor = build_tool_runtime(
        catalog,
        max_request_bytes=10_000,
        max_response_bytes=10_000,
    )

    assert [
        definition.name for definition in registry.definitions_for("student-1-integration-test")
    ] == [
        "integration_test.records.search.v1",
        "integration_test.records.inspect.v1",
        "integration_test.records.dependencies.v1",
        "integration_test.records.create.v1",
    ]
    assert registry.definitions_for("student-2-feature") == ()
    executor.close()


def test_catalog_rejects_unsafe_model_escaping_paths(tmp_path: Path) -> None:
    payload = EXAMPLE_CATALOG.read_text(encoding="utf-8").replace(
        "/api/v1/tools/records.search.v1",
        "//untrusted.example/tool",
    )
    path = tmp_path / "unsafe.yaml"
    path.write_text(payload, encoding="utf-8")

    catalog = load_tool_catalog(path)
    with pytest.raises(ToolCatalogError, match="unsafe"):
        build_tool_runtime(catalog, max_request_bytes=1_000, max_response_bytes=1_000)


def test_multiple_feature_catalogs_compose_into_one_runtime() -> None:
    propertyscope_catalog = EXAMPLE_CATALOG.parents[2] / "student-1" / "tool-catalog.yaml"

    catalog = load_tool_catalogs((EXAMPLE_CATALOG, propertyscope_catalog))
    registry, executor = build_tool_runtime(
        catalog,
        max_request_bytes=10_000,
        max_response_bytes=10_000,
    )

    assert registry.definitions_for("student-1-integration-test")
    assert registry.definitions_for("student-1-propertyscope-data-platform")
    executor.close()


def test_catalog_composition_rejects_duplicate_service_identity() -> None:
    catalog = load_tool_catalog(EXAMPLE_CATALOG)
    duplicate_service = ToolCatalog(services=(catalog.services[0],))

    with pytest.raises(ToolCatalogError, match="service identities must be unique"):
        compose_tool_catalogs((catalog, duplicate_service))


def test_catalog_composition_rejects_duplicate_tool_binding() -> None:
    catalog = load_tool_catalog(EXAMPLE_CATALOG)
    original = catalog.tools[0]
    second_service = catalog.services[0].model_copy(update={"service": "another-feature-backend"})
    duplicate_tool = ToolCatalog(
        services=(second_service,),
        tools=(original.model_copy(update={"service": second_service.service}),),
    )

    with pytest.raises(ToolCatalogError, match="tool bindings must be unique"):
        compose_tool_catalogs((catalog, duplicate_tool))
