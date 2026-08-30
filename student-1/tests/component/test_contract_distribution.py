"""Supported, content-addressed distribution for producer-owned consumer schemas."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from zipfile import ZipFile

import httpx
import pytest

from propertyscope_data_platform.app import create_app
from propertyscope_data_platform.clients import AiModeClient, ConsumerImportClient, DataStoreClient
from propertyscope_data_platform.configuration import ConfigurationError
from propertyscope_data_platform.contract_distribution import build_product_contract_package

FEATURE_ROOT = Path(__file__).resolve().parents[2]


def test_contract_package_is_deterministic_closed_and_registry_complete() -> None:
    first = build_product_contract_package(FEATURE_ROOT / "contracts")
    second = build_product_contract_package(FEATURE_ROOT / "contracts")

    assert first == second
    assert hashlib.sha256(first.content).hexdigest() == first.content_sha256
    with ZipFile(io.BytesIO(first.content)) as archive:
        assert tuple(archive.namelist()) == first.filenames
        contract_set = json.loads(archive.read("product-contract-set.v1.json"))
        for registration in (*contract_set["contracts"], *contract_set["legacy_contracts"]):
            assert registration["schema_path"] in first.filenames
        for required in (
            "consumer-publication-request.v1.schema.json",
            "consumer-import-acknowledgement.v1.schema.json",
            "consumer-publication-receipt.v1.schema.json",
            "release-manifest.v1.schema.json",
        ):
            assert required in first.filenames


def test_contract_package_rejects_registry_path_traversal(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / "product-contract-set.v1.json").write_text(
        json.dumps(
            {
                "contract_set_version": "propertyscope.product-contract-set.v1",
                "contracts": [{"schema_path": "../producer.py"}],
            }
        ),
        "utf-8",
    )

    with pytest.raises(ConfigurationError, match="unsafe schema path"):
        build_product_contract_package(contracts)


def test_contract_package_is_discovered_and_downloaded_over_fixed_http() -> None:
    unavailable = httpx.MockTransport(lambda _: httpx.Response(503))
    app = create_app(
        store_client=DataStoreClient(
            "http://database", "secret", client=httpx.Client(transport=unavailable)
        ),
        ai_mode_client=AiModeClient("http://ai", client=httpx.Client(transport=unavailable)),
        consumer_client=ConsumerImportClient({}),
    )
    client = app.test_client()

    metadata_response = client.get("/api/data-platform/v1/product-contracts/v1")
    assert metadata_response.status_code == 200
    metadata = metadata_response.get_json()
    assert metadata["media_type"] == "application/zip"
    assert metadata["artifact_path"].endswith(f"/{metadata['content_sha256']}.zip")

    artifact = client.get(metadata["artifact_path"])
    assert artifact.status_code == 200
    assert artifact.content_type == "application/zip"
    assert len(artifact.data) == metadata["byte_count"]
    assert hashlib.sha256(artifact.data).hexdigest() == metadata["content_sha256"]
    encoded_digest = base64.b64encode(bytes.fromhex(metadata["content_sha256"])).decode()
    assert artifact.headers["Digest"] == f"sha-256=:{encoded_digest}:"
    assert artifact.headers["Cache-Control"].endswith("immutable")

    assert client.get("/api/data-platform/v1/product-contracts/v1?path=secret").status_code == 422
    assert (
        client.get(
            "/api/data-platform/v1/product-contracts/v1/sha256/" + "0" * 64 + ".zip"
        ).status_code
        == 404
    )
