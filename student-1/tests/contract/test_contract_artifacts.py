from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from ai_mode.tool_catalog import load_tool_catalog
from shared_contracts.feature import load_feature_manifest

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


def _json(name: str) -> object:
    return json.loads((CONTRACTS / name).read_text("utf-8"))


def test_openapi_document_is_versioned_and_parseable() -> None:
    document = yaml.safe_load((CONTRACTS / "data-platform-api.v1.openapi.yaml").read_text("utf-8"))
    assert document["openapi"] == "3.1.0"
    assert "/properties/search" in document["paths"]
    assert "/jobs/{job_id}/runs" in document["paths"]


def test_release_manifest_fixtures_encode_success_and_failure() -> None:
    schema = _json("release-manifest.v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.validate(_json("fixtures/release-manifest.valid.json"), schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_json("fixtures/release-manifest.invalid-checksum.json"), schema)


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
