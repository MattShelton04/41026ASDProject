"""Deterministic, versioned distribution for producer-owned consumer contracts."""

from __future__ import annotations

import base64
import hashlib
import io
import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from flask import Blueprint, Response, jsonify, request

from propertyscope_data_platform.configuration import ConfigurationError
from propertyscope_data_platform.http_support import problem

CONTRACT_SET_VERSION = "propertyscope.product-contract-set.v1"
PROTOCOL_CONTRACTS = (
    "product-contract-set.v1.schema.json",
    "release-manifest.v1.schema.json",
    "consumer-publication-request.v1.schema.json",
    "consumer-import-acknowledgement.v1.schema.json",
    "consumer-publication-receipt.v1.schema.json",
)


@dataclass(frozen=True, slots=True)
class ProductContractPackage:
    """One immutable ZIP and its content-addressed public identity."""

    content: bytes
    content_sha256: str
    filenames: tuple[str, ...]


def build_product_contract_package(contracts_root: Path) -> ProductContractPackage:
    """Build one deterministic package from the validated fixed contract-set index."""
    contract_set_path = contracts_root / "product-contract-set.v1.json"
    try:
        contract_set = json.loads(contract_set_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError("product contract set is unavailable or invalid") from exc
    if contract_set.get("contract_set_version") != CONTRACT_SET_VERSION:
        raise ConfigurationError("product contract set version is unsupported")
    registrations = contract_set.get("contracts")
    legacy_registrations = contract_set.get("legacy_contracts", [])
    if not isinstance(registrations, list) or not registrations:
        raise ConfigurationError("product contract set has no registered schemas")
    if not isinstance(legacy_registrations, list):
        raise ConfigurationError("product contract set legacy schemas are invalid")

    filenames = {"product-contract-set.v1.json", *PROTOCOL_CONTRACTS}
    for registration in (*registrations, *legacy_registrations):
        schema_path = registration.get("schema_path") if isinstance(registration, dict) else None
        if not isinstance(schema_path, str) or not _fixed_schema_filename(schema_path):
            raise ConfigurationError("product contract set contains an unsafe schema path")
        filenames.add(schema_path)

    documents: dict[str, bytes] = {}
    for filename in sorted(filenames):
        path = contracts_root / filename
        try:
            document: Any = json.loads(path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"contract package document is invalid: {filename}") from exc
        documents[filename] = (
            json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode()

    output = io.BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for filename, content in documents.items():
            info = ZipInfo(filename, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, content, compress_type=ZIP_DEFLATED, compresslevel=9)
    content = output.getvalue()
    return ProductContractPackage(
        content=content,
        content_sha256=hashlib.sha256(content).hexdigest(),
        filenames=tuple(documents),
    )


def register_contract_distribution_routes(api: Blueprint, *, feature_root: Path, base: str) -> None:
    """Expose discovery plus one digest-bound immutable package; never arbitrary files."""
    package = build_product_contract_package(feature_root / "contracts")
    artifact_path = f"{base}/product-contracts/v1/sha256/{package.content_sha256}.zip"

    @api.get(f"{base}/product-contracts/v1")
    def product_contract_package_metadata() -> Response:
        if request.args:
            return problem(422, "invalid_query", "Product contract discovery takes no query fields")
        response = jsonify(
            {
                "contract_set_version": CONTRACT_SET_VERSION,
                "media_type": "application/zip",
                "content_sha256": package.content_sha256,
                "byte_count": len(package.content),
                "artifact_path": artifact_path,
            }
        )
        response.headers["Cache-Control"] = "no-cache"
        return response

    @api.get(f"{base}/product-contracts/v1/sha256/<digest>.zip")
    def product_contract_package_artifact(digest: str) -> Response:
        if request.args:
            return problem(422, "invalid_query", "Product contract artifacts take no query fields")
        if digest != package.content_sha256:
            return problem(404, "contract_package_not_found", "Contract package does not exist")
        response = Response(package.content, content_type="application/zip")
        encoded_digest = base64.b64encode(bytes.fromhex(package.content_sha256)).decode()
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        response.headers["Content-Disposition"] = (
            'attachment; filename="propertyscope-product-contracts-v1.zip"'
        )
        response.headers["Digest"] = f"sha-256=:{encoded_digest}:"
        response.headers["ETag"] = f'"sha256:{package.content_sha256}"'
        return response


def _fixed_schema_filename(value: str) -> bool:
    path = PurePosixPath(value)
    return (
        len(path.parts) == 1
        and path.name == value
        and value.endswith(".schema.json")
        and value not in {".", ".."}
        and "\\" not in value
    )
