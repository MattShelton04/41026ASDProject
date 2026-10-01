"""Validate Feature 3's reviewed guidance and official locality projection."""

import importlib.util
import json
from pathlib import Path
from typing import Any

from propertyscope_suburb_analytics.app import FEATURE_KEY
from shared_testkit import assert_corpus_manifest


def test_corpus_manifest_is_ingestible() -> None:
    assert_corpus_manifest(
        Path("student-3/config/rag/corpus.json"),
        feature_key=FEATURE_KEY,
        corpus_id="suburb-analytics-guidance",
    )


def _builder() -> Any:
    path = Path("student-3/config/rag/build_locality_corpus.py")
    spec = importlib.util.spec_from_file_location("feature3_locality_corpus", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _polygon(west: float, south: float, east: float, north: float) -> dict[str, Any]:
    return {
        "type": "Polygon",
        "coordinates": [
            [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]
        ],
    }


def test_geometry_free_projection_is_official_bounded_and_source_aware() -> None:
    builder = _builder()
    release = {
        "id": "release-1",
        "record_count": 2,
        "manifest_json": {"source_retrieved_at": "2026-10-01T00:00:00Z"},
    }
    geography = [
        {
            "layer": builder.SAL_LAYER,
            "name": "Parramatta",
            "geometry": _polygon(150.9, -33.9, 151.1, -33.7),
            "attributes": {"sal_code_2021": "13167"},
        },
        {
            "layer": builder.LGA_LAYER,
            "name": "Parramatta",
            "geometry": _polygon(150.8, -34.0, 151.2, -33.6),
            "attributes": {"lga_code_2021": "16260"},
        },
    ]
    amenities = [
        {
            "layer": "train-station",
            "name": "Parramatta Station",
            "geometry": {"type": "Point", "coordinates": [151.0, -33.8]},
        },
        {
            "layer": "hospital",
            "name": "Outside Hospital",
            "geometry": {"type": "Point", "coordinates": [152.0, -33.8]},
        },
    ]
    documents = builder.build_documents(
        localities=["Parramatta"],
        geography=geography,
        amenities=amenities,
        geography_release=release,
        amenity_release=release,
        base_url="http://127.0.0.1:5200/api/data-platform/v1",
    )
    assert len(documents) == 1
    document = documents[0]
    assert document["evidence_kind"] == "official"
    assert "Parramatta Station" in document["text"]
    assert "Outside Hospital" not in document["text"]
    assert "151.0" not in document["text"]
    assert "-33.8" not in document["text"]
    assert "not an official suburb-to-LGA crosswalk" in document["text"]


def test_supported_localities_are_unique_and_bounded() -> None:
    values = json.loads(
        Path("student-3/config/rag/supported-localities.json").read_text(encoding="utf-8")
    )
    assert 1 <= len(values) <= 25
    assert len({value.casefold() for value in values}) == len(values)
