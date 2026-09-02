"""Pure builders for bounded due-diligence map GeoJSON.

No Flask or network here, so these are unit-tested directly. Hazard polygons are
deterministic, small rectangles offset from the property point; a hazard layer is only
drawn when its evidence actually intersects the property (confirmed or partial coverage),
so the map never implies exposure that the evidence does not support.
"""

from __future__ import annotations

from typing import Any

# Hazard layers we surface, with a deterministic offset and size (in degrees) from the
# property point so flood and bushfire zones are visually distinct.
_HAZARD_LAYERS: dict[str, dict[str, Any]] = {
    "flood": {"label": "Flood planning area", "dx": 0.0016, "dy": -0.0012, "radius": 0.0011},
    "bushfire": {"label": "Bushfire prone land", "dx": -0.0018, "dy": 0.0013, "radius": 0.0012},
}

# Evidence states that mean the hazard actually applies to the property.
_PRESENT_STATES = frozenset({"confirmed", "partial_coverage"})


def _feature_collection(feature: dict[str, Any]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": [feature]}


def property_point(longitude: float, latitude: float, properties: dict[str, Any]) -> dict[str, Any]:
    """Return a FeatureCollection holding the single verified property point."""
    return _feature_collection(
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [longitude, latitude]},
            "properties": properties,
        }
    )


def _closed_ring(
    longitude: float, latitude: float, dx: float, dy: float, radius: float
) -> list[list[float]]:
    center_x = longitude + dx
    center_y = latitude + dy
    return [
        [center_x - radius, center_y - radius],
        [center_x + radius, center_y - radius],
        [center_x + radius, center_y + radius],
        [center_x - radius, center_y + radius],
        [center_x - radius, center_y - radius],
    ]


def hazard_polygon(
    longitude: float, latitude: float, hazard: str, properties: dict[str, Any]
) -> dict[str, Any]:
    """Return a FeatureCollection with one closed polygon for the given hazard."""
    spec = _HAZARD_LAYERS[hazard]
    ring = _closed_ring(longitude, latitude, spec["dx"], spec["dy"], spec["radius"])
    return _feature_collection(
        {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": properties,
        }
    )


def build_map(
    longitude: float,
    latitude: float,
    review: dict[str, Any],
    constraints: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the bounded map payload: the property point plus any applicable hazard layers."""
    by_type: dict[str, dict[str, Any]] = {}
    for item in constraints:
        constraint_type = item.get("constraint_type")
        if constraint_type in _HAZARD_LAYERS and constraint_type not in by_type:
            by_type[constraint_type] = item

    layers: list[dict[str, Any]] = []
    for hazard, spec in _HAZARD_LAYERS.items():
        observation = by_type.get(hazard)
        state = observation.get("evidence_state") if observation else "unavailable"
        if state not in _PRESENT_STATES:
            continue
        layers.append(
            {
                "id": hazard,
                "label": spec["label"],
                "hazard": hazard,
                "evidence_state": state,
                "data": hazard_polygon(
                    longitude,
                    latitude,
                    hazard,
                    {
                        "hazard": spec["label"],
                        "evidence_state": state,
                        "summary": (observation or {}).get("summary", ""),
                    },
                ),
            }
        )

    return {
        "available": True,
        "center": [longitude, latitude],
        "property": property_point(
            longitude,
            latitude,
            {
                "address": review.get("address_display", ""),
                "property_ref": review.get("property_ref", ""),
            },
        ),
        "layers": layers,
    }
