"""NSW parcel, planning-control and explicitly scoped hazard source facts."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx

from .arcgis import discover_arcgis_layer, iter_arcgis_features

_EPI = "https://mapprod1.environment.nsw.gov.au/arcgis/rest/services/Planning/"
_LAYERS: dict[str, tuple[tuple[str, str], ...]] = {
    "nsw-cadastre": (
        (
            "lot",
            "https://portal.spatial.nsw.gov.au/server/rest/services/NSW_Land_Parcel_Property_Theme_multiCRS/FeatureServer/8",
        ),
    ),
    "nsw-planning-controls": tuple(
        (name, f"{_EPI}EPI_Primary_Planning_Layers/MapServer/{layer}")
        for name, layer in (
            ("heritage", 0),
            ("floor-space-ratio", 1),
            ("land-zoning", 2),
            ("minimum-lot-size", 4),
            ("height-of-building", 5),
        )
    ),
    "nsw-bushfire-prone-land": (
        (
            "bushfire-prone-land",
            "https://portal.spatial.nsw.gov.au/server/rest/services/Hosted/NSW_BushFire_Prone_Land/FeatureServer/0",
        ),
    ),
    "nsw-flood-planning": (("flood-planning", f"{_EPI}EPI_Protection_Layers/MapServer/1"),),
}


def discover_spatial_sources(profile: str, client: httpx.Client) -> list[dict[str, Any]]:
    """Discover fixed publisher layers with per-layer coverage and source metadata."""
    objects = []
    for layer, url in _LAYERS[profile]:
        descriptor = discover_arcgis_layer(
            client,
            url,
            layer,
            workers=4 if profile == "nsw-cadastre" else 1,
            # Current Lot metadata defaults to 100 records but explicitly supports
            # standard queries up to 4000. Keep our live-benchmarked bound at 2000.
            standard_page_size=2000 if profile == "nsw-cadastre" else None,
        )
        if profile == "nsw-flood-planning":
            # Complex multipolygons: the publisher returns HTML for 622/1000
            # features but correctly serves pages of 100 (live verified).
            descriptor["page_size"] = min(100, descriptor["page_size"])
        if profile == "nsw-bushfire-prone-land":
            descriptor["empty_projection_fallback"] = "EPSG:3857"
        descriptor["coverage"]["interpretation"] = _coverage(profile)
        objects.append(descriptor)
    return sorted(objects, key=lambda item: item["logical_key"])


def _coverage(profile: str) -> str:
    if profile == "nsw-flood-planning":
        return (
            "Published EPI flood planning controls only; council mapping may be newer. "
            "No statewide inundation coverage or AEP is established. Absence is unknown."
        )
    if profile == "nsw-bushfire-prone-land":
        return (
            "Published bushfire prone land for development control; "
            "absence does not establish freedom from bushfire risk."
        )
    if profile == "nsw-cadastre":
        return (
            "Complete NSW publisher Lot layer, including source stratum/status fields; "
            "no address match or property ownership inference."
        )
    return (
        "Complete five published EPI control layers; applicability and legal effect "
        "require the referenced instrument. Absence is unknown."
    )


def _date(attributes: dict[str, Any], *keys: str, open_ended: bool = False) -> str | None:
    for key in keys:
        value = attributes.get(key)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Invalid publisher date in {key}")
            parsed = datetime.fromtimestamp(value / 1000, UTC)
            if open_ended and parsed.year == 3000:
                return None
            return parsed.isoformat()
    return None


def iter_spatial_records(
    profile: str, client: httpx.Client, objects: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """Preserve complete publisher attributes and source identifiers without joins."""
    expected = dict(_LAYERS[profile])
    actual = {item["logical_key"]: item["url"] for item in objects}
    if actual != expected or len(objects) != len(expected):
        raise ValueError("Spatial source inventory does not match the registered profile")
    for descriptor in sorted(objects, key=lambda item: item["logical_key"]):
        layer = descriptor["logical_key"]
        for feature in iter_arcgis_features(client, descriptor):
            attributes = dict(feature["properties"])
            source_id = attributes[descriptor["oid_field"]]
            name = (
                attributes.get("H_NAME")
                or attributes.get("lotidstring")
                or attributes.get("LAY_CLASS")
                or attributes.get("d_Category")
                or attributes.get("d_category")
            )
            geometry = feature.get("geometry")
            if geometry is not None and geometry.get("type") not in ("Polygon", "MultiPolygon"):
                raise ValueError("Spatial source returned an unexpected geometry type")
            if profile == "nsw-flood-planning":
                attributes["evidence_kind"] = "flood-planning-control"
                attributes["aep_percent"] = None
                attributes["flood_scenario"] = None
                attributes["study_extent"] = None
                attributes["absence_interpretation"] = "unknown"
            yield {
                "record_id": f"{layer}:{source_id}",
                "layer": layer,
                "name": str(name) if name is not None else None,
                "geometry": geometry,
                "attributes": attributes,
                "source_url": descriptor["url"],
                "source_crs": descriptor["source_crs"],
                "source_updated_at": _date(attributes, "CURRENCY_DATE", "LastUpdate", "lastupdate"),
                "valid_from": _date(attributes, "COMMENCED_DATE", "StartDate", "startdate"),
                "valid_to": _date(attributes, "EndDate", "enddate", open_ended=True),
            }
