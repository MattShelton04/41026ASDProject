"""Public catalogue and accepted-product HTTP routes."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

from propertyscope_data_platform.clients import DataStoreClient
from propertyscope_data_platform.http_support import forward, problem
from propertyscope_data_platform.release_builders import DataProductCatalogueEntry
from propertyscope_data_platform.release_projection import release_detail_contract


def register_data_product_routes(
    api: Blueprint,
    store: DataStoreClient,
    product_catalogue: Sequence[DataProductCatalogueEntry],
    *,
    base: str,
    internal: str,
) -> None:
    """Register catalogue and bounded accepted-record routes."""

    @api.get(f"{base}/data-products")
    def data_products() -> Response:
        if request.args:
            return problem(422, "invalid_query", "Data product catalogue takes no query fields")
        accepted_response = store.request(
            "GET",
            f"{internal}/releases",
            headers=request.headers,
            params={"status": "accepted", "limit": 100, "offset": 0},
        )
        if accepted_response.status_code >= 400:
            return forward(accepted_response)
        accepted = accepted_response.json().get("items", [])
        items = []
        for entry in product_catalogue:
            matching = next(
                (
                    item
                    for item in accepted
                    if item.get("dataset_id") == entry.dataset_id
                    and item.get("target_feature") == entry.target_feature
                ),
                None,
            )
            if matching is not None:
                try:
                    release_detail_contract(matching)
                except ValidationError:
                    matching = None
            payload = entry.model_dump(mode="json")
            payload["latest_accepted_release"] = (
                {
                    key: matching.get(key)
                    for key in (
                        "id",
                        "release_version",
                        "schema_version",
                        "content_sha256",
                        "record_count",
                        "accepted_at",
                    )
                }
                if matching
                else None
            )
            items.append(payload)
        return jsonify({"items": items, "count": len(items), "next_cursor": None})

    @api.get(f"{base}/data-products/<dataset_id>")
    def data_product(dataset_id: str) -> Response:
        if request.args:
            return problem(422, "invalid_query", "Data product detail takes no query fields")
        entry = next((item for item in product_catalogue if item.dataset_id == dataset_id), None)
        if entry is None:
            return problem(404, "data_product_not_found", "Data product is not registered")
        accepted_response = store.request(
            "GET",
            f"{internal}/releases",
            headers=request.headers,
            params={
                "status": "accepted",
                "dataset_id": dataset_id,
                "target_feature": entry.target_feature,
                "limit": 1,
                "offset": 0,
            },
        )
        if accepted_response.status_code >= 400:
            return forward(accepted_response)
        matching = next(iter(accepted_response.json().get("items", [])), None)
        if matching is not None:
            try:
                release_detail_contract(matching)
            except ValidationError:
                matching = None
        payload = entry.model_dump(mode="json")
        payload["latest_accepted_release"] = matching
        return jsonify(payload)

    @api.get(f"{base}/data-products/<dataset_id>/accepted")
    def accepted_data_product(dataset_id: str) -> Response:
        entry = next((item for item in product_catalogue if item.dataset_id == dataset_id), None)
        if entry is None:
            return problem(404, "data_product_not_found", "Data product is not registered")
        target = request.args.get("target_feature", entry.target_feature)
        if target != entry.target_feature or set(request.args) - {"target_feature"}:
            return problem(422, "invalid_query", "Accepted product query is invalid")
        upstream = store.request(
            "GET",
            f"{internal}/releases",
            headers=request.headers,
            params={
                "status": "accepted",
                "dataset_id": dataset_id,
                "target_feature": target,
                "limit": 1,
                "offset": 0,
            },
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        items = upstream.json().get("items", [])
        if not items:
            return problem(404, "accepted_release_not_found", "No accepted release is available")
        try:
            release_contract = release_detail_contract(items[0])
        except ValidationError:
            return problem(
                409, "release_contract_invalid", "Accepted release is not contract-valid"
            )
        return jsonify({"release": release_contract})

    @api.get(f"{base}/data-products/<dataset_id>/source-records")
    def data_product_source_records(dataset_id: str) -> Response:
        """Expose complete accepted PSI facts through stable, year-bounded pages."""
        entry = next((item for item in product_catalogue if item.dataset_id == dataset_id), None)
        if entry is None:
            return problem(404, "data_product_not_found", "Data product is not registered")
        if dataset_id != "nsw-psi-sales":
            return problem(
                409,
                "source_records_unsupported",
                "This data product does not expose a separate source-record feed",
            )
        allowed = {"year", "limit", "offset", "release_id"}
        if set(request.args) - allowed:
            return problem(422, "invalid_query", "Source-record query contains unknown fields")
        try:
            year = int(request.args["year"])
            limit = int(request.args.get("limit", "1000"))
            offset = int(request.args.get("offset", "0"))
            release_id = (
                uuid.UUID(request.args["release_id"]) if request.args.get("release_id") else None
            )
        except (KeyError, TypeError, ValueError):
            return problem(422, "invalid_query", "year and pagination fields must be integers")
        if not 1990 <= year <= 9999 or not 1 <= limit <= 5_000 or not 0 <= offset <= 1_000_000:
            return problem(422, "invalid_query", "Source-record query is outside its bounds")
        if release_id is None:
            accepted_response = store.request(
                "GET",
                f"{internal}/releases",
                headers=request.headers,
                params={
                    "status": "accepted",
                    "dataset_id": dataset_id,
                    "target_feature": entry.target_feature,
                    "limit": 1,
                    "offset": 0,
                },
            )
            if accepted_response.status_code >= 400:
                return forward(accepted_response)
            accepted = next(
                (
                    item
                    for item in accepted_response.json().get("items", [])
                    if item.get("schema_version") == entry.product_schema_version
                ),
                None,
            )
            if accepted is None:
                return problem(
                    404, "accepted_release_not_found", "No accepted release is available"
                )
            release_id = uuid.UUID(str(accepted["id"]))
        return forward(
            store.request(
                "GET",
                f"{internal}/releases/{release_id}/sales-source-records",
                headers=request.headers,
                params={"year": year, "limit": limit, "offset": offset},
            )
        )
