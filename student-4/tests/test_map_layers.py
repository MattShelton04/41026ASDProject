"""Tests for the pure map GeoJSON builders (no Flask, no network)."""

from __future__ import annotations

from propertyscope_due_diligence.map_layers import build_map, hazard_polygon, property_point


def test_property_point_is_a_valid_feature_collection():
    collection = property_point(151.0, -33.9, {"address": "11 Example Street"})
    assert collection["type"] == "FeatureCollection"
    feature = collection["features"][0]
    assert feature["geometry"]["type"] == "Point"
    assert feature["geometry"]["coordinates"] == [151.0, -33.9]
    assert feature["properties"]["address"] == "11 Example Street"


def test_hazard_polygon_ring_is_closed_and_bounded():
    collection = hazard_polygon(151.0, -33.9, "flood", {"hazard": "Flood planning area"})
    ring = collection["features"][0]["geometry"]["coordinates"][0]
    assert len(ring) == 5
    assert ring[0] == ring[-1]
    assert all(-180 <= lng <= 180 and -90 <= lat <= 90 for lng, lat in ring)


def test_build_map_only_draws_hazards_that_apply():
    review = {"address_display": "11 Example Street", "property_ref": "a0"}
    constraints = [
        {"constraint_type": "flood", "evidence_state": "confirmed", "summary": "In flood area"},
        {"constraint_type": "bushfire", "evidence_state": "non_intersection", "summary": "Clear"},
        {"constraint_type": "zoning", "evidence_state": "confirmed", "summary": "R2"},
    ]
    result = build_map(151.0, -33.9, review, constraints)
    assert result["available"] is True
    assert result["center"] == [151.0, -33.9]
    assert result["property"]["features"][0]["geometry"]["type"] == "Point"
    hazards = {layer["hazard"] for layer in result["layers"]}
    assert hazards == {"flood"}
    assert result["layers"][0]["evidence_state"] == "confirmed"
    assert result["layers"][0]["data"]["features"][0]["geometry"]["type"] == "Polygon"


def test_build_map_with_no_applicable_hazards_has_only_the_point():
    review = {"address_display": "x", "property_ref": "a0"}
    constraints = [
        {"constraint_type": "flood", "evidence_state": "unavailable"},
        {"constraint_type": "bushfire", "evidence_state": "non_intersection"},
    ]
    result = build_map(151.0, -33.9, review, constraints)
    assert result["layers"] == []
