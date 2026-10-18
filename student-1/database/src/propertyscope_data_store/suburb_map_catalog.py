"""Registered public categories and limits for the accepted suburb-map projection.

One table maps every public map category to the accepted dataset, source layer and spatial
predicate that answers it. Migration 064 indexes the same amenity layers; a unit test keeps the
two in step, so a new category cannot silently fall off the generation-scoped spatial index.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SUBURB_MAP_CONTEXT_SCHEMA = "propertyscope.suburb-map-context.v1"
SUBURB_SEARCH_SCHEMA = "propertyscope.suburb-search.v1"
SUBURB_DETAIL_SCHEMA = "propertyscope.suburb-detail.v1"
# Bump when the projection SQL changes what a cached response would contain.
SUBURB_MAP_PROJECTION_VERSION = "1"

BOUNDARY_DATASET = "nsw-suburb-boundaries"
BOUNDARY_TARGET_FEATURE = "feature-1"
BOUNDARY_LAYER = "nsw-gazetted-suburb"
BOUNDARY_SCHEMA = "propertyscope.reference-feature.v1"
AMENITY_DATASET = "nsw-amenities"
SCHOOL_DATASET = "nsw-government-schools"
SCHOOL_SCHEMA = "propertyscope.school-points.v2"

GeometryKind = Literal["point", "polygon"]
Predicate = Literal["covers", "intersects"]
DetailLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class MapCategory:
    """One public map layer and the accepted source that answers it."""

    key: str
    dataset_id: str
    target_feature: str
    schema_version: str
    source_layer: str | None
    geometry: GeometryKind
    predicate: Predicate
    description: str


def _amenity(key: str, description: str) -> MapCategory:
    return MapCategory(
        key=key,
        dataset_id=AMENITY_DATASET,
        target_feature="feature-1",
        schema_version=BOUNDARY_SCHEMA,
        source_layer=key,
        geometry="point",
        predicate="covers",
        description=description,
    )


MAP_CATEGORIES: tuple[MapCategory, ...] = (
    MapCategory(
        key="schools",
        dataset_id=SCHOOL_DATASET,
        target_feature="feature-3",
        schema_version=SCHOOL_SCHEMA,
        source_layer=None,
        geometry="point",
        predicate="covers",
        description="NSW Department of Education government schools (school-points.v2)",
    ),
    _amenity("train-station", "NSW Spatial Services railway station points"),
    _amenity("bus-station", "NSW Spatial Services bus and coach station points"),
    _amenity("airport", "NSW Spatial Services airport points"),
    _amenity("library", "NSW Spatial Services public library points"),
    _amenity("hospital", "NSW Spatial Services hospital points"),
    _amenity("ambulance-station", "NSW Spatial Services ambulance station points"),
    _amenity("police-station", "NSW Spatial Services police station points"),
    _amenity("fire-and-rescue-station", "NSW Spatial Services Fire and Rescue station points"),
    _amenity("rural-fire-station", "NSW Spatial Services Rural Fire Service brigade points"),
    _amenity("ses-headquarters", "NSW Spatial Services SES unit points"),
    _amenity("preschool", "NSW Spatial Services preschool points (all providers)"),
    _amenity("primary-school", "NSW Spatial Services primary school points (all sectors)"),
    _amenity("high-school", "NSW Spatial Services high school points (all sectors)"),
    _amenity("combined-school", "NSW Spatial Services combined school points (all sectors)"),
    _amenity("technical-college", "NSW Spatial Services TAFE and technical college points"),
    _amenity("university", "NSW Spatial Services university points"),
    MapCategory(
        key="protected-reserve",
        dataset_id=AMENITY_DATASET,
        target_feature="feature-1",
        schema_version=BOUNDARY_SCHEMA,
        source_layer="protected-reserve",
        geometry="polygon",
        predicate="intersects",
        description=(
            "NPWS protected estate polygons only; not complete council or general park coverage"
        ),
    ),
)
MAP_CATEGORIES_BY_KEY = {category.key: category for category in MAP_CATEGORIES}
AMENITY_SOURCE_LAYERS = tuple(
    category.source_layer
    for category in MAP_CATEGORIES
    if category.dataset_id == AMENITY_DATASET and category.source_layer is not None
)
DEFAULT_CATEGORIES = ("schools", "train-station", "library", "protected-reserve")
# Names a consumer may reasonably try that Feature 1 deliberately does not publish.
DECLINED_CATEGORIES = {
    "parks": (
        "Feature 1 has no official source with complete park coverage; use "
        "'protected-reserve' for NPWS protected estate, which is not general park coverage"
    ),
    "park": (
        "Feature 1 has no official source with complete park coverage; use "
        "'protected-reserve' for NPWS protected estate, which is not general park coverage"
    ),
}

# Display tolerances in degrees (EPSG:4326). Measured on the 4,607 accepted boundaries:
# 50 m keeps every suburb under 900 vertices, 10 m under 2,400 and 2 m under 5,000.
DETAIL_TOLERANCES: dict[DetailLevel, float] = {"low": 0.0005, "medium": 0.0001, "high": 0.00002}
DEFAULT_DETAIL: DetailLevel = "medium"
COORDINATE_DECIMALS = 6

MAX_CATEGORIES = 12
DEFAULT_LAYER_LIMIT = 500
MAX_LAYER_LIMIT = 1000
MAX_RESPONSE_VERTICES = 60_000
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_SEARCH_RESULTS = 50
DEFAULT_SEARCH_RESULTS = 20
# Reserve display geometry is clipped to the suburb bbox grown by this fraction per side.
RESERVE_CLIP_MARGIN = 0.1
# Feature 1 freshness policy: an accepted layer acquired longer ago than this is ``stale``.
FRESHNESS_DAYS = {BOUNDARY_DATASET: 400, AMENITY_DATASET: 400, SCHOOL_DATASET: 400}
# Publisher ``operationalstatus`` 1 is an operating facility. The publisher exposes no code
# list; other codes (6 is observed on closed branch-line stations) are treated as not current.
OPERATIONAL_STATUS_CODE = 1


def detail_for_zoom(zoom: int) -> DetailLevel:
    """Map a web-map zoom level to a precomputed display detail."""
    if zoom <= 11:
        return "low"
    if zoom <= 14:
        return "medium"
    return "high"
