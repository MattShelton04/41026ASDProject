"""Canonical-property read routes and bounded report evidence projection."""

from __future__ import annotations

import uuid

from flask import Blueprint, Response, jsonify, request

from propertyscope_data_platform.clients import DataStoreClient
from propertyscope_data_platform.http_support import forward


def register_property_routes(
    api: Blueprint,
    store: DataStoreClient,
    *,
    base: str,
    internal: str,
) -> None:
    """Register canonical property discovery and evidence routes."""

    @api.get(f"{base}/properties/search")
    def property_search() -> Response:
        return forward(
            store.request(
                "GET", f"{internal}/properties/search", headers=request.headers, params=request.args
            )
        )

    @api.get(f"{base}/properties/<uuid:property_ref>")
    def property_detail(property_ref: uuid.UUID) -> Response:
        return forward(
            store.request("GET", f"{internal}/properties/{property_ref}", headers=request.headers)
        )

    @api.get(f"{base}/properties/<uuid:property_ref>/map-context")
    def property_map(property_ref: uuid.UUID) -> Response:
        upstream = store.request(
            "GET", f"{internal}/properties/{property_ref}", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        item = upstream.json()["property"]
        return jsonify(
            {
                "property_ref": str(property_ref),
                "address_display": item["address_display"],
                "longitude": item["longitude"],
                "latitude": item["latitude"],
                "geometry": item["geometry"],
            }
        )

    @api.get(f"{base}/properties/<uuid:property_ref>/coverage")
    def property_coverage(property_ref: uuid.UUID) -> Response:
        return forward(
            store.request(
                "GET", f"{internal}/properties/{property_ref}/coverage", headers=request.headers
            )
        )

    @api.get(f"{base}/properties/<uuid:property_ref>/report-section")
    def property_report_section(property_ref: uuid.UUID) -> Response:
        """Return bounded canonical evidence for the Feature 5 report composer."""
        upstream = store.request(
            "GET", f"{internal}/properties/{property_ref}", headers=request.headers
        )
        if upstream.status_code >= 400:
            return forward(upstream)
        snapshot = upstream.json()
        property_item = snapshot["property"]
        gnaf_identifier = next(
            (
                item
                for item in snapshot.get("identifiers", [])
                if str(item.get("scheme", "")).lower() in {"gnaf_pid", "gnaf"}
            ),
            None,
        )
        release_evidence = [
            {
                "dataset_id": item["dataset_id"],
                "target_feature": item["target_feature"],
                "dataset_release_id": item.get("dataset_release_id"),
                "release_version": item.get("release_version"),
                "schema_version": item.get("schema_version"),
                "coverage_status": item["coverage_status"],
                "coverage_scope": item["coverage_scope"],
                "accepted_at": item.get("accepted_at"),
                "checked_at": item["checked_at"],
            }
            for item in snapshot.get("coverage", [])[:25]
        ]
        return jsonify(
            {
                "schema_version": "propertyscope.report-section.v1",
                "property_ref": str(property_ref),
                "address_display": property_item["address_display"],
                "identity": {
                    "gnaf_pid": gnaf_identifier.get("identifier_value")
                    if gnaf_identifier
                    else None,
                    "resolution_status": property_item["resolution_status"],
                    "locality": property_item["locality"],
                    "postcode": property_item["postcode"],
                    "state": property_item["state"],
                    "longitude": property_item.get("longitude"),
                    "latitude": property_item.get("latitude"),
                    "geometry": property_item.get("geometry"),
                },
                "release_evidence": release_evidence,
                "evidence_count": len(release_evidence),
            }
        )
