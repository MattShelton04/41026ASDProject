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
from flask import Flask
from pydantic import ValidationError as PydanticValidationError

from ai_mode.tool_catalog import load_tool_catalog
from propertyscope_data_platform.api import public_receipt
from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, DataStoreClient
from propertyscope_data_platform.domain import ConsumerImportAcknowledgement
from propertyscope_data_platform.release_builders import (
    data_product_catalogue,
    default_release_builders,
    product_contract_set_document,
    product_schema_documents,
)
from propertyscope_data_platform.release_publication import _catalog_publication_output
from shared_consumer_protocol import ImportReceipt
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
        "/notifications",
        "/health/live",
        "/health/ready",
        "/artifact-retention",
        "/runtime-capabilities",
        "/assistant/capabilities",
        "/assistant/turns",
        "/assistant/turns/{run_id}",
        "/assistant/turns/{run_id}/events",
        "/assistant/turns/{run_id}/cancel",
        "/product-contracts/v1",
        "/product-contracts/v1/sha256/{digest}.zip",
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
        "/ingestion-runs/{run_id}/activity",
        "/ingestion-runs/{run_id}/activity/download",
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
        "/dataset-releases/{release_id}/retry-delivery",
        "/dataset-releases/{release_id}/consumer-imports/{operation_id}",
        "/dataset-releases/{release_id}/reject",
        "/dataset-releases/{release_id}/agent-runs",
        "/properties/search",
        "/properties/locality-summary",
        "/properties/{property_ref}",
        "/properties/{property_ref}/map-context",
        "/properties/{property_ref}/coverage",
        "/properties/{property_ref}/sale-history",
        "/properties/{property_ref}/seifa",
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
        "/tools/properties.locality-summary.v1",
        "/tools/runs.retry.v1",
        "/tools/releases.publish.v1",
    }
    assert set(document["paths"]) == expected_paths
    assistant_request = document["components"]["schemas"]["AssistantTurnRequest"]
    assert assistant_request["properties"]["history"]["maxItems"] == 8
    context_schema = document["components"]["schemas"]["AssistantContext"]
    routes = {
        branch.get("properties", {}).get("route", {}).get("const")
        for branch in context_schema["oneOf"]
    }
    assert routes == {None, "releases/detail", "runs/detail", "properties/detail"}


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
        if rule.rule.startswith(base) or rule.rule in {"/health/live", "/health/ready"}
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

    for health_path in ("/health/live", "/health/ready"):
        operation = document["paths"][health_path]
        assert operation["servers"] == [{"url": "/"}]
        for response in operation["get"]["responses"].values():
            schema = response["content"]["application/json"]["schema"]
            assert schema == {"$ref": "#/components/schemas/TypedHealthProjection"}


def test_cancel_contract_preserves_conflict_and_documents_unconfirmed_reconciliation() -> None:
    document = yaml.safe_load((CONTRACTS / "data-platform-api.v1.openapi.yaml").read_text("utf-8"))
    responses = document["paths"]["/ingestion-runs/{run_id}/cancel"]["post"]["responses"]

    assert set(responses) == {"200", "409", "503"}
    assert responses["409"] == {"$ref": "#/components/responses/Problem"}
    unavailable = responses["503"]
    representation = unavailable["content"]["application/problem+json"]
    assert representation["schema"] == {"$ref": "#/components/schemas/Problem"}
    assert representation["example"]["status"] == 503
    assert representation["example"]["code"] == "cancellation_unconfirmed"


def test_release_manifest_revisions_preserve_legacy_and_constrain_current_transport() -> None:
    legacy_schema = _json("release-manifest.v1.schema.json")
    current_schema = _json("release-manifest.v2.schema.json")
    jsonschema.Draft202012Validator.check_schema(legacy_schema)
    jsonschema.Draft202012Validator.check_schema(current_schema)
    jsonschema.validate(_json("fixtures/release-manifest.valid.json"), legacy_schema)
    jsonschema.validate(_json("fixtures/release-manifest.v2.valid.json"), current_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            _json("fixtures/release-manifest.v2.invalid-transport.json"), current_schema
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_json("fixtures/release-manifest.invalid-checksum.json"), legacy_schema)
    for name in (
        "release-manifest.invalid-schema-version.json",
        "release-manifest.invalid-missing-field.json",
    ):
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(_json(f"fixtures/{name}"), legacy_schema)


def test_openapi_describes_manifest_compatibility_and_failed_publication_envelopes() -> None:
    document = yaml.safe_load((CONTRACTS / "data-platform-api.v1.openapi.yaml").read_text("utf-8"))
    manifest_schema = document["paths"]["/dataset-releases/{release_id}/manifest"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert manifest_schema["oneOf"] == [
        {"$ref": "./release-manifest.v2.schema.json"},
        {"$ref": "./release-manifest.v1.schema.json"},
    ]

    failed = document["paths"]["/dataset-releases/{release_id}/publish"]["post"]["responses"][
        "424"
    ]["content"]
    assert failed == {
        "application/json": {"schema": {"$ref": "#/components/schemas/PublicationResult"}},
        "application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}},
    }


def test_release_detail_accepts_closed_legacy_and_current_manifest_evidence() -> None:
    schema = _json("release-detail.v1.schema.json")
    legacy = _json("fixtures/release-detail.valid.json")
    jsonschema.validate(legacy, schema)

    current = deepcopy(legacy)
    current_manifest = _json("fixtures/release-manifest.v2.valid.json")
    current.update(
        {
            "schema_version": current_manifest["product_schema_version"],
            "content_sha256": current_manifest["content_sha256"],
            "manifest_json": current_manifest,
        }
    )
    jsonschema.validate(current, schema)


def test_publication_request_accepts_legacy_evidence_but_fixture_uses_current_manifest() -> None:
    schema = _json("consumer-publication-request.v1.schema.json")
    current = _json("fixtures/consumer-publication-request.valid.json")
    jsonschema.validate(current, schema)
    assert current["manifest"]["manifest_schema_version"] == "propertyscope.release-manifest.v2"

    legacy_manifest = _json("fixtures/release-manifest.valid.json")
    legacy = {
        "release_id": legacy_manifest["release_id"],
        "dataset_id": legacy_manifest["dataset_id"],
        "schema_version": legacy_manifest["product_schema_version"],
        "content_sha256": legacy_manifest["content_sha256"],
        "record_count": legacy_manifest["record_count"],
        "manifest": legacy_manifest,
        "artifact_path": (
            f"/api/data-platform/v1/dataset-releases/{legacy_manifest['release_id']}/artifact"
        ),
        "idempotency_key": "legacy-release-replay-1",
    }
    jsonschema.validate(legacy, schema)


@pytest.mark.parametrize(
    ("schema_name", "valid_fixture", "invalid_fixture"),
    [
        (
            "property-snapshot.v1.schema.json",
            "property-snapshot.valid.json",
            "property-snapshot.invalid-coordinate.json",
        ),
        (
            "property-snapshot.v2.schema.json",
            "property-snapshot.v2.valid.json",
            "property-snapshot.v2.invalid-coordinate.json",
        ),
        (
            "property-sales.v2.schema.json",
            "property-sales.v2.valid.json",
            "property-sales.v2.invalid-postcode.json",
        ),
        (
            "property-sales.v3.schema.json",
            "property-sales.v3.valid.json",
            "property-sales.v3.invalid-postcode.json",
        ),
        (
            "crime-series.v1.schema.json",
            "crime-series.valid.json",
            "crime-series.invalid-coverage.json",
        ),
        (
            "crime-series.v2.schema.json",
            "crime-series.v2.valid.json",
            "crime-series.v2.invalid-coverage.json",
        ),
        (
            "school-points.v1.schema.json",
            "school-points.valid.json",
            "school-points.invalid-coordinate.json",
        ),
        (
            "school-points.v2.schema.json",
            "school-points.v2.valid.json",
            "school-points.v2.invalid-coordinate.json",
        ),
        (
            "seifa-area.v1.schema.json",
            "seifa-area.v1.valid.json",
            "seifa-area.v1.invalid-decile.json",
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
    "fixture_name",
    [
        "consumer-import-acknowledgement.valid-queued.json",
        "consumer-import-acknowledgement.valid-accepted.json",
    ],
)
def test_consumer_import_acknowledgement_fixtures_match_schema_and_runtime(
    fixture_name: str,
) -> None:
    payload = _json(f"fixtures/{fixture_name}")
    schema = _json("consumer-import-acknowledgement.v1.schema.json")

    jsonschema.validate(payload, schema)
    acknowledgement = ConsumerImportAcknowledgement.model_validate(payload)
    assert acknowledgement.consumer_operation_id == "consumer-issued-operation-17"
    if acknowledgement.status == "accepted":
        shared_receipt = ImportReceipt.model_validate(payload)
        assert shared_receipt.consumer_operation_id == acknowledgement.consumer_operation_id


def test_consumer_import_acknowledgement_rejects_incoherent_nonterminal_evidence() -> None:
    payload = _json("fixtures/consumer-import-acknowledgement.invalid-incoherent.json")
    schema = _json("consumer-import-acknowledgement.v1.schema.json")

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)
    with pytest.raises(PydanticValidationError, match="nonterminal consumer operation"):
        ConsumerImportAcknowledgement.model_validate(payload)


@pytest.mark.parametrize(
    ("schema_name", "valid_fixture"),
    [
        ("property-snapshot.v1.schema.json", "property-snapshot.valid.json"),
        ("property-snapshot.v2.schema.json", "property-snapshot.v2.valid.json"),
        ("property-sales.v2.schema.json", "property-sales.v2.valid.json"),
        ("property-sales.v3.schema.json", "property-sales.v3.valid.json"),
        ("crime-series.v1.schema.json", "crime-series.valid.json"),
        ("crime-series.v2.schema.json", "crime-series.v2.valid.json"),
        ("school-points.v1.schema.json", "school-points.valid.json"),
        ("school-points.v2.schema.json", "school-points.v2.valid.json"),
        ("seifa-area.v1.schema.json", "seifa-area.v1.valid.json"),
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
        (
            "consumer-import-acknowledgement.v1.schema.json",
            "consumer-import-acknowledgement.valid-accepted.json",
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
        "./release-manifest.v2.schema.json",
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


def test_supported_product_contract_set_matches_runtime_registry() -> None:
    contract_set = _json("product-contract-set.v1.json")
    jsonschema.validate(contract_set, _json("product-contract-set.v1.schema.json"))
    assert contract_set == product_contract_set_document()

    builders = default_release_builders()
    for item in contract_set["contracts"]:
        builder = builders[item["builder_key"]]
        assert item["builder_version"] == builder.spec.version
        assert item["schema_version"] == builder.spec.contract
        assert item["media_type"] == "application/x-ndjson"
        assert item["content_encoding"] == "gzip"
        assert item["record_framing"] == "one-json-object-per-line"
        schema_path = CONTRACTS / item["schema_path"]
        assert schema_path.parent == CONTRACTS
        assert schema_path.is_file()
    assert {
        (item["schema_version"], item["compatibility_status"])
        for item in contract_set["legacy_contracts"]
    } == {
        ("propertyscope.property-snapshot.v1", "accepted-release-read-only"),
        ("propertyscope.property-sales.v2", "accepted-release-read-only"),
        ("propertyscope.crime-series.v1", "accepted-release-read-only"),
        ("propertyscope.school-points.v1", "accepted-release-read-only"),
    }
    for item in contract_set["legacy_contracts"]:
        assert (CONTRACTS / item["schema_path"]).is_file()


def test_consumer_guide_catalogue_and_transport_match_runtime_registry() -> None:
    guide = (ROOT / "DATA_PRODUCT_CONSUMER_GUIDE.md").read_text("utf-8")
    for item in data_product_catalogue(ROOT):
        row_prefix = (
            f"| `{item.dataset_id}` | `{item.builder_key} {item.builder_version}` | "
            f"`{item.product_schema_version}` |"
        )
        assert row_prefix in guide
    assert "current v2/v3 builders uses media type `application/x-ndjson`" in guide
    assert "content encoding `gzip`" in guide
    assert "legacy releases" in guide
    assert "There is no outer product envelope." in guide
    assert "product-contract-set.v1.json" in guide


def test_consumer_guide_receipt_examples_match_runtime_contracts() -> None:
    guide = (ROOT / "DATA_PRODUCT_CONSUMER_GUIDE.md").read_text("utf-8")
    json_blocks = [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", guide, re.S)]
    receipts = [item for item in json_blocks if "consumer_operation_id" in item]
    assert len(receipts) == 2

    acknowledgement_schema = _json("consumer-import-acknowledgement.v1.schema.json")
    runtime_contracts = {builder.spec.contract for builder in default_release_builders().values()}
    for receipt in receipts:
        jsonschema.validate(receipt, acknowledgement_schema)
        assert receipt["schema_version"] in runtime_contracts
        assert re.fullmatch(r"[0-9a-f]{64}", receipt["content_sha256"])


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
        "consumer_imports",
        "publication_policy",
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


def test_release_inspection_response_matches_its_closed_tool_schema() -> None:
    release_id = "60000000-0000-4000-8000-000000000011"
    release = {
        "id": release_id,
        "dataset_id": "fixture-property",
        "target_feature": "feature-1",
        "ingestion_run_id": "30000000-0000-4000-8000-000000000011",
        "release_version": "fixture-2026-09",
        "schema_version": "propertyscope.property-snapshot.v2",
        "record_count": 3,
        "content_sha256": "a" * 64,
        "manifest_json": {},
        "status": "accepted",
        "supersedes_release_id": None,
        "version": 2,
    }

    def database(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/quality-results"):
            return httpx.Response(200, json={"items": []})
        return httpx.Response(
            200,
            json={
                "release": release,
                "receipts": [],
                "activations": [],
                "consumer_imports": [
                    {
                        "id": "70000000-0000-4000-8000-000000000011",
                        "dataset_release_id": release_id,
                        "status": "polling",
                        "phase_key": "status",
                        "attempt_number": 1,
                        "version": 2,
                    }
                ],
            },
        )

    app = create_app(
        store_client=DataStoreClient(
            "http://database",
            "secret",
            client=httpx.Client(transport=httpx.MockTransport(database)),
        ),
        ai_mode_client=AiModeClient(
            "http://ai",
            client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(503))),
        ),
    )
    response = app.test_client().post(
        "/api/data-platform/v1/tools/releases.inspect.v1",
        json={"release_id": release_id},
    )
    payload = response.get_json()
    catalog = load_tool_catalog(ROOT / "tool-catalog.yaml")
    registration = next(
        item for item in catalog.tools if item.definition.name == "data.release_inspect.v1"
    )

    assert response.status_code == 200
    jsonschema.validate(payload, registration.definition.output_schema)
    assert payload["consumer_imports"][0]["budgets"] == {
        "connect_timeout_seconds": 5,
        "status_timeout_seconds": 5,
        "maximum_response_bytes": 65536,
    }


def test_release_publication_tool_outputs_match_the_closed_catalog() -> None:
    catalog = load_tool_catalog(ROOT / "tool-catalog.yaml")
    registration = next(
        item for item in catalog.tools if item.definition.name == "data.release_publish.v1"
    )
    schema = cast(dict[str, Any], registration.definition.output_schema)
    receipt_id = "71000000-0000-4000-8000-000000000099"
    variants = (
        ("accepted", receipt_id, True, 200),
        ("accepted", None, True, 200),
        ("pending", receipt_id, False, 202),
        ("pending", None, False, 202),
        ("failed", receipt_id, True, 424),
        ("failed", None, False, 409),
    )

    app = Flask("publication-tool-contract-test")
    emitted_statuses: set[str] = set()
    with app.app_context():
        for status, variant_receipt_id, replayed, status_code in variants:
            response = _catalog_publication_output(
                status,
                receipt_id=variant_receipt_id,
                replayed=replayed,
                status_code=status_code,
            )
            payload = response.get_json()
            assert isinstance(payload, dict)
            jsonschema.validate(payload, schema)
            assert response.status_code == status_code
            emitted_statuses.add(status)

    status_schema = cast(dict[str, Any], schema["properties"])["status"]
    assert cast(dict[str, Any], status_schema)["enum"] == ["accepted", "failed", "pending"]
    assert emitted_statuses == {"accepted", "failed", "pending"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            {"status": "rejected", "receipt_id": receipt_id, "replayed": False},
            schema,
        )


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
        "sales_history",
    }


def test_feature_manifest_uses_the_canonical_shared_edge_route() -> None:
    manifest = load_feature_manifest(ROOT / "feature.yaml")

    assert manifest.frontend_base_path == "/features/data-platform/"
    assert manifest.backend_base_path == "/api/data-platform/v1"
