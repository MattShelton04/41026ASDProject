"""Database-owned validation and materialisation of registered source reference facts."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

REFERENCE_PROFILES = frozenset(
    {
        "nsw-cadastre",
        "nsw-planning-controls",
        "nsw-bushfire-prone-land",
        "nsw-flood-planning",
        "abs-geography-2021",
        "nsw-suburb-boundaries",
        "nsw-school-catchments",
        "nsw-strata-schemes",
        "nsw-amenities",
        "abs-cpi",
    }
)
REFERENCE_FIELDS = (
    "record_id",
    "layer",
    "name",
    "geometry",
    "attributes",
    "source_url",
    "source_crs",
    "source_updated_at",
    "valid_from",
    "valid_to",
)


def validate_reference_row(
    row: object, index: int, *, profile: str | None = None
) -> dict[str, Any]:
    """Reject malformed records, preserving publisher nulls and geometry without repair."""
    if not isinstance(row, dict) or set(row) != set(REFERENCE_FIELDS):
        raise ValueError(f"reference record {index} has an invalid field set")
    result = dict(row)
    for field, maximum in (("record_id", 300), ("layer", 100), ("source_crs", 100)):
        value = row[field]
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ValueError(f"reference record {index} has invalid {field}")
    if row["name"] is not None and (not isinstance(row["name"], str) or len(row["name"]) > 1000):
        raise ValueError(f"reference record {index} has an invalid name")
    url = row["source_url"]
    if not isinstance(url, str) or len(url) > 4000:
        raise ValueError(f"reference record {index} has an invalid source URL")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError(f"reference record {index} requires a public HTTPS source URL")
    if not isinstance(row["attributes"], dict) or len(row["attributes"]) > 250:
        raise ValueError(f"reference record {index} has invalid publisher attributes")
    for field in ("source_updated_at", "valid_from", "valid_to"):
        value = row[field]
        if value is not None:
            if not isinstance(value, str) or len(value) > 50:
                raise ValueError(f"reference record {index} has an invalid {field}")
            datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Replay compatibility for the first canonical artifacts: Spatial Services uses
    # this exact end-date value as an open-ended sentinel. Retain the original field
    # in attributes, including its hash contribution, while exposing nullable validity.
    # Source dates without the matching publisher sentinel are never inferred.
    if (
        row["valid_to"] is not None
        and datetime.fromisoformat(row["valid_to"].replace("Z", "+00:00")).year == 3000
        and any(row["attributes"].get(key) == 32503680000000 for key in ("enddate", "EndDate"))
    ):
        result["valid_to"] = None
    geometry = row["geometry"]
    if geometry is not None:
        if not isinstance(geometry, dict) or set(geometry) != {"type", "coordinates"}:
            raise ValueError(f"reference record {index} has an invalid GeoJSON geometry")
        depths = {
            "Point": 0,
            "MultiPoint": 1,
            "LineString": 1,
            "MultiLineString": 2,
            "Polygon": 2,
            "MultiPolygon": 3,
        }
        depth = depths.get(geometry["type"])
        if depth is None:
            raise ValueError(f"reference record {index} has an unsupported geometry type")
        _coordinates(geometry["coordinates"], depth)
    # JSON encoding also rejects NaN/infinity in publisher attributes. Keep a bound on one
    # feature, independent of page size, while permitting complex official boundary polygons.
    encoded = json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    # The current official BFPL service contains a verified 47 MB polygon with
    # 1,176,284 positions. Preserve its full geometry within the same 64 MiB
    # ceiling as the source reader. The complete planning artifact also contains
    # one verified 19.6 MB zoning polygon; its allowance is separately capped.
    maximum_mib = {
        "nsw-bushfire-prone-land": 64,
        "nsw-planning-controls": 32,
    }.get(profile or "", 16)
    maximum_bytes = maximum_mib * 1024 * 1024
    if len(encoded) > maximum_bytes:
        raise ValueError(f"reference record {index} exceeds the per-feature byte bound")
    result["source_row_sha256"] = hashlib.sha256(encoded).hexdigest()
    return result


def _coordinates(value: object, depth: int) -> None:
    if not isinstance(value, (list, tuple)) or not value:
        raise ValueError("reference geometry has empty or malformed coordinates")
    if depth:
        for child in value:
            _coordinates(child, depth - 1)
        return
    if len(value) != 2 or any(
        isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item)
        for item in value
    ):
        raise ValueError("reference geometry requires finite two-dimensional positions")
    if not -180 <= value[0] <= 180 or not -90 <= value[1] <= 90:
        raise ValueError("reference geometry must use EPSG:4326 longitude and latitude")


REFERENCE_INSERT_SQL = """
    INSERT INTO warehouse.reference_feature (
        dataset_release_id,record_id,layer,name,geometry_json,geom,attributes,
        source_url,source_crs,source_updated_at,valid_from,valid_to,
        source_row_sha256,normalisation_version,artifact_record_id,ingestion_run_id
    ) SELECT %s,payload->>'record_id',payload->>'layer',payload->>'name',
        NULLIF(payload->'geometry','null'::jsonb),
        CASE WHEN payload->'geometry' <> 'null'::jsonb
          THEN ST_SetSRID(ST_GeomFromGeoJSON(payload->'geometry'),4326) END,
        payload->'attributes',payload->>'source_url',payload->>'source_crs',
        payload->>'source_updated_at',payload->>'valid_from',payload->>'valid_to',
        payload->>'source_row_sha256','1.0.0',%s,%s
    FROM propertyscope_import_stage ORDER BY ordinal
"""
REFERENCE_COUNT_SQL = """
    SELECT count(*) AS count FROM warehouse.reference_feature
    WHERE dataset_release_id=%s AND artifact_record_id=%s AND ingestion_run_id=%s
"""
REFERENCE_COLUMNS = (
    *REFERENCE_FIELDS,
    "geometry_status",
    "source_row_sha256",
    "normalisation_version",
)
REFERENCE_SELECT = """SELECT record_id,layer,name,geometry_json AS geometry,attributes,
    source_url,source_crs,source_updated_at,valid_from,valid_to,geometry_status,
    source_row_sha256,normalisation_version FROM warehouse.reference_feature"""
