from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import httpx
import jsonschema
import pytest
import yaml

from ai_mode.tool_catalog import load_tool_catalog
from propertyscope_data_platform.api import public_receipt
from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient
from propertyscope_data_platform.release_builders import product_schema_documents
from shared_contracts.feature import load_feature_manifest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


def _json(name: str) -> dict[str, Any]:
    document = json.loads((CONTRACTS / name).read_text("utf-8"))
    assert isinstance(document, dict)
    return cast(dict[str, Any], document)


def test_openapi_document_is_versioned_and_parseable() -> None:
    document = yaml.safe_load((CONTRACTS / "data-platform-api.v1.openapi.yaml").read_text("utf-8"))
    assert document["openapi"] == "3.1.0"
    expected_paths = {
        "/overview",
        "/artifact-retention",
        "/runtime-capabilities",
        "/assistant/capabilities",
        "/assistant/turns",
        "/assistant/turns/{run_id}",
        "/assistant/turns/{run_id}/events",
        "/assistant/turns/{run_id}/cancel",
        "/data-products",
        "/data-products/{dataset_id}",
        "/data-products/{dataset_id}/accepted",
        "/data-products/{dataset_id}/source-records",
        "/sources",
        "/sources/{source_id}",
        "/jobs",
        "/jobs/{job_id}",
        "/jobs/{job_id}/capabilities",
        "/jobs/{job_id}/plans",
        "/jobs/{job_id}/runs",
        "/ingestion-runs",
        "/ingestion-runs/{run_id}",
        "/ingestion-runs/{run_id}/tasks",
        "/ingestion-runs/{run_id}/artifacts",
        "/ingestion-runs/{run_id}/quality-results",
        "/ingestion-runs/{run_id}/cancel",
        "/ingestion-runs/{run_id}/resume",
        "/ingestion-runs/{run_id}/retry",
        "/ingestion-runs/{run_id}/reprocess-cached",
        "/dataset-releases",
        "/dataset-releases/{release_id}",
        "/dataset-releases/{release_id}/manifest",
        "/dataset-releases/{release_id}/artifact",
        "/dataset-releases/{release_id}/records",
        "/dataset-releases/{release_id}/submit-review",
        "/dataset-releases/{release_id}/publish",
        "/dataset-releases/{release_id}/reject",
        "/dataset-releases/{release_id}/agent-runs",
        "/properties/search",
        "/properties/{property_ref}",
        "/properties/{property_ref}/map-context",
        "/properties/{property_ref}/coverage",
        "/properties/{property_ref}/report-section",
        "/agent-runs",
        "/agent-runs/{run_id}",
        "/agent-runs/{run_id}/events",
        "/tools/sources.list.v1",
        "/tools/releases.list.v1",
        "/tools/platform.capabilities.v1",
        "/tools/runs.list.v1",
        "/tools/runs.inspect.v1",
        "/tools/runs.explain.v1",
        "/tools/releases.inspect.v1",
        "/tools/releases.compare.v1",
        "/tools/coverage.inspect.v1",
        "/tools/properties.search.v1",
        "/tools/properties.inspect.v1",
        "/tools/runs.retry.v1",
        "/tools/releases.publish.v1",
    }
    assert set(document["paths"]) == expected_paths


def test_openapi_operations_exactly_match_public_runtime_routes() -> None:
    unavailable = httpx.MockTransport(lambda _: httpx.Response(503))
    app = create_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=unavailable)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=unavailable)),
    )
    base = "/api/data-platform/v1"

    def contract_path(rule: str) -> str:
        return re.sub(r"<(?:[^:>]+:)?([^>]+)>", r"{\1}", rule.removeprefix(base))

    runtime = {
        (contract_path(rule.rule), method.lower())
        for rule in app.url_map.iter_rules()
        if rule.rule.startswith(base)
        for method in rule.methods or set()
        if method not in {"HEAD", "OPTIONS"}
    }
    document = yaml.safe_load((CONTRACTS / "data-platform-api.v1.openapi.yaml").read_text("utf-8"))
    described = {
        (path, method)
        for path, operations in document["paths"].items()
        for method in operations
        if method in {"get", "post", "put", "delete", "patch"}
    }
    assert described == runtime


def test_release_manifest_fixtures_encode_success_and_failure() -> None:
    schema = _json("release-manifest.v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_json("fixtures/release-manifest.valid.json"), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_json("fixtures/release-manifest.invalid-checksum.json"), schema)
    for name in (
        "release-manifest.invalid-schema-version.json",
        "release-manifest.invalid-missing-field.json",
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_json(f"fixtures/{name}"), schema)


@pytest.mark.parametrize(
    ("schema_name", "valid_fixture", "invalid_fixture"),
    [
        (
            "property-snapshot.v1.schema.json",
            "property-snapshot.valid.json",
            "property-snapshot.invalid-coordinate.json",
        ),
        (
            "property-sales.v2.schema.json",
            "property-sales.v2.valid.json",
            "property-sales.v2.invalid-postcode.json",
        ),
        (
            "crime-series.v1.schema.json",
            "crime-series.valid.json",
            "crime-series.invalid-coverage.json",
        ),
        (
            "school-points.v1.schema.json",
            "school-points.valid.json",
            "school-points.invalid-coordinate.json",
        ),
    ],
)
def test_data_product_contracts_have_valid_and_invalid_redistributable_fixtures(
    schema_name: str, valid_fixture: str, invalid_fixture: str
) -> None:
    schema = _json(schema_name)
    jsonschema.validate(_json(f"fixtures/{valid_fixture}"), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_json(f"fixtures/{invalid_fixture}"), schema)


@pytest.mark.parametrize(
    ("schema_name", "valid_fixture", "invalid_fixture"),
    [
        (
            "data-product-catalogue-entry.v1.schema.json",
            "data-product-catalogue-entry.valid.json",
            "data-product-catalogue-entry.invalid-missing-field.json",
        ),
        (
            "consumer-publication-request.v1.schema.json",
            "consumer-publication-request.valid.json",
            "consumer-publication-request.invalid-checksum.json",
        ),
        (
            "consumer-publication-receipt.v1.schema.json",
            "consumer-publication-receipt.valid.json",
            "consumer-publication-receipt.invalid-checksum.json",
        ),
        (
            "release-detail.v1.schema.json",
            "release-detail.valid.json",
            "release-detail.invalid-checksum.json",
        ),
    ],
)
def test_discovery_and_publication_contracts_have_representative_fixtures(
    schema_name: str, valid_fixture: str, invalid_fixture: str
) -> None:
    schema = _json(schema_name)
    jsonschema.validate(_json(f"fixtures/{valid_fixture}"), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_json(f"fixtures/{invalid_fixture}"), schema)


@pytest.mark.parametrize(
    ("schema_name", "valid_fixture"),
    [
        ("property-snapshot.v1.schema.json", "property-snapshot.valid.json"),
        ("property-sales.v2.schema.json", "property-sales.v2.valid.json"),
        ("crime-series.v1.schema.json", "crime-series.valid.json"),
        ("school-points.v1.schema.json", "school-points.valid.json"),
        (
            "data-product-catalogue-entry.v1.schema.json",
            "data-product-catalogue-entry.valid.json",
        ),
        (
            "consumer-publication-request.v1.schema.json",
            "consumer-publication-request.valid.json",
        ),
        (
            "consumer-publication-receipt.v1.schema.json",
            "consumer-publication-receipt.valid.json",
        ),
        ("release-detail.v1.schema.json", "release-detail.valid.json"),
    ],
)
def test_public_contract_matrix_rejects_missing_and_additive_fields(
    schema_name: str, valid_fixture: str
) -> None:
    schema = _json(schema_name)
    valid = _json(f"fixtures/{valid_fixture}")
    missing = deepcopy(valid)
    missing.pop(schema["required"][0])
    additive = {**valid, "undeclared_future_field": True}

    for invalid in (missing, additive):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(invalid, schema)


def test_openapi_references_checked_in_discovery_and_release_contracts() -> None:
    document = (CONTRACTS / "data-platform-api.v1.openapi.yaml").read_text("utf-8")

    for reference in (
        "./data-product-catalogue-entry.v1.schema.json",
        "./release-detail.v1.schema.json",
        "./release-manifest.v1.schema.json",
        "./consumer-publication-receipt.v1.schema.json",
    ):
        assert reference in document


def test_datastore_receipt_is_projected_to_the_closed_public_schema() -> None:
    projected = public_receipt(
        {
            "id": "private-receipt-id",
            "dataset_release_id": "60000000-0000-0000-0000-000000000099",
            "target_feature": "feature-2",
            "consumer_operation_id": "publish-fixture",
            "status": "accepted",
            "schema_version": "propertyscope.property-sales.v2",
            "content_sha256": "a" * 64,
            "rows_received": 1,
            "rows_accepted": 1,
            "rows_rejected": 0,
            "error_json": None,
            "request_id": "private-request-id",
        }
    )

    jsonschema.validate(projected, _json("consumer-publication-receipt.v1.schema.json"))
    assert "id" not in projected
    assert "request_id" not in projected


def test_generated_release_contracts_do_not_drift() -> None:
    for filename, expected in product_schema_documents().items():
        assert _json(filename) == expected


def test_checked_in_job_profiles_match_published_schema() -> None:
    schema = _json("job-profile.v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    for path in sorted((ROOT / "config" / "job-profiles").glob("*.yaml")):
        jsonschema.validate(yaml.safe_load(path.read_text("utf-8")), schema)


def test_adapter_descriptors_match_published_schema() -> None:
    schema = _json("adapter-descriptor.v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    register = yaml.safe_load((ROOT / "config" / "adapter-register.yaml").read_text("utf-8"))
    for descriptor in register["adapters"]:
        jsonschema.validate(descriptor, schema)


def test_tool_catalog_exactly_covers_declared_ai_capabilities() -> None:
    manifest = load_feature_manifest(ROOT / "feature.yaml")
    catalog = load_tool_catalog(ROOT / "tool-catalog.yaml")
    names = {registration.definition.name for registration in catalog.tools}
    assert names == set(manifest.ai_capabilities)


def test_release_inspection_tool_declares_all_composed_evidence() -> None:
    catalog = load_tool_catalog(ROOT / "tool-catalog.yaml")
    registration = next(
        item for item in catalog.tools if item.definition.name == "data.release_inspect.v1"
    )
    schema = registration.definition.output_schema

    expected = {
        "release",
        "quality_results",
        "quality_summary",
        "receipts",
        "activations",
        "accepted_predecessor",
        "release_contract",
    }
    properties = schema["properties"]
    required = schema["required"]
    assert isinstance(properties, dict)
    assert isinstance(required, list)
    required_names = {item for item in required if isinstance(item, str)}
    assert len(required_names) == len(required)
    assert set(properties) == expected
    assert required_names == expected


def test_release_discovery_uses_real_statuses_and_source_metadata_is_not_load_evidence() -> None:
    catalog = load_tool_catalog(ROOT / "tool-catalog.yaml")
    registrations = {item.definition.name: item.definition for item in catalog.tools}

    release_tool = registrations["data.releases.v1"]
    input_schema = cast(dict[str, Any], release_tool.input_schema)
    properties = cast(dict[str, Any], input_schema["properties"])
    status_schema = cast(dict[str, Any], properties["status"])
    statuses = status_schema["enum"]
    assert statuses == [
        "draft",
        "candidate",
        "awaiting_review",
        "accepted",
        "rejected",
        "superseded",
        "abandoned",
    ]
    assert release_tool.side_effect.value == "read_only"
    assert "does not prove" in registrations["data.sources.v1"].description

    property_schema = cast(dict[str, Any], registrations["property.inspect.v1"].output_schema)
    required = property_schema["required"]
    assert isinstance(required, list)
    assert set(required) == {
        "property",
        "identifiers",
        "aliases",
        "coverage",
    }


def test_feature_manifest_uses_the_canonical_shared_edge_route() -> None:
    manifest = load_feature_manifest(ROOT / "feature.yaml")

    assert manifest.frontend_base_path == "/features/data-platform/"
    assert manifest.backend_base_path == "/api/data-platform/v1"
