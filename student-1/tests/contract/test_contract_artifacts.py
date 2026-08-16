from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import jsonschema
import pytest
import yaml

from ai_mode.tool_catalog import load_tool_catalog
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
        "/runtime-capabilities",
        "/data-products",
        "/data-products/{dataset_id}",
        "/data-products/{dataset_id}/accepted",
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
        "/agent-runs/{agent_run_id}",
        "/agent-runs/{agent_run_id}/events",
        "/tools/sources.list.v1",
        "/tools/runs.list.v1",
        "/tools/runs.inspect.v1",
        "/tools/releases.inspect.v1",
        "/tools/releases.compare.v1",
        "/tools/coverage.inspect.v1",
        "/tools/properties.search.v1",
        "/tools/properties.inspect.v1",
        "/tools/runs.retry.v1",
        "/tools/releases.publish.v1",
    }
    assert set(document["paths"]) == expected_paths


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
            "property-sales.v1.schema.json",
            "property-sales.valid.json",
            "property-sales.invalid-date.json",
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
