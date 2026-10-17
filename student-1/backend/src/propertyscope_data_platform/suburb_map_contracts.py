"""Versioned public contracts for the accepted suburb-map spatial projection.

The JSON Schemas generated from these models are checked into ``student-1/contracts`` and
distributed in the product-contract package. Any change to a closed shape needs a new version.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from propertyscope_data_platform.release_builders import SchoolPointRecord

SuburbId = str
CoverageState = Literal["accepted", "partial", "stale", "unavailable"]
DetailLevel = Literal["low", "medium", "high"]
LayerReason = Literal[
    "dataset_unavailable",
    "unsupported_schema",
    "layer_not_in_release",
    "boundary_geometry_unavailable",
]
_SUBURB_ID = r"^[1-9][0-9]{0,11}$"
_POSTCODE = r"^[0-9]{4}$"


class _Closed(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GeoJsonGeometry(_Closed):
    """WGS84 longitude/latitude geometry with at most six decimal places."""

    type: Literal["Point", "Polygon", "MultiPolygon"]
    coordinates: list[Any]


class ReleaseReference(_Closed):
    """The accepted release that answered one layer, with publisher provenance."""

    dataset_id: str
    target_feature: str
    dataset_release_id: uuid.UUID
    release_version: str
    schema_version: str
    accepted_at: str | None
    acquired_at: str | None
    source_updated_at: str | None
    publisher: str | None
    source_name: str | None
    source_url: str | None
    licence_id: str | None
    licence_url: str | None
    freshness_days: int | None


class SuburbSummary(_Closed):
    suburb_id: SuburbId = Field(pattern=_SUBURB_ID, description="Publisher cadid")
    name: str
    postcode: str | None = Field(pattern=_POSTCODE)
    state: Literal["NSW"]
    geometry_status: Literal["valid", "invalid", "not_provided"]
    centroid: tuple[float, float] | None = Field(
        description="ST_Centroid [longitude, latitude]; may fall outside a concave suburb"
    )
    label_point: tuple[float, float] | None = Field(
        description="ST_PointOnSurface [longitude, latitude]; always inside the suburb"
    )
    bbox: tuple[float, float, float, float] | None = Field(
        description="[min_longitude, min_latitude, max_longitude, max_latitude]"
    )


class SuburbSearchQuery(_Closed):
    q: str
    normalised: str
    postcode: str | None


class SuburbSearchAvailability(_Closed):
    status: Literal["available", "dataset_unavailable"]
    reason: str


class SuburbSearchV1(_Closed):
    schema_version: Literal["propertyscope.suburb-search.v1"]
    geography: Literal["nsw-gazetted-suburb"]
    query: SuburbSearchQuery
    availability: SuburbSearchAvailability
    match: Literal["none", "unique", "ambiguous"]
    items: list[SuburbSummary]
    count: int = Field(ge=0)
    has_more: bool
    release: ReleaseReference | None


class SuburbSourceDates(_Closed):
    record_id: str
    source_updated_at: str | None
    valid_from: str | None
    start_date: str | None
    last_update: str | None
    urbanity: str | None
    publisher_edition: str | None


class DisplayLevel(_Closed):
    tolerance_degrees: float
    vertex_count: int | None


class DisplaySummary(_Closed):
    source_vertex_count: int = Field(ge=0)
    levels: dict[DetailLevel, DisplayLevel]


class SuburbDetailV1(SuburbSummary):
    schema_version: Literal["propertyscope.suburb-detail.v1"]
    geography: Literal["nsw-gazetted-suburb"]
    source: SuburbSourceDates
    display: DisplaySummary
    coverage: CoverageState
    release: ReleaseReference


class BoundaryProperties(_Closed):
    suburb_id: SuburbId = Field(pattern=_SUBURB_ID)
    name: str
    postcode: str | None
    detail: DetailLevel
    tolerance_degrees: float
    source_vertex_count: int = Field(ge=0)
    display_vertex_count: int | None


class BoundaryFeature(_Closed):
    type: Literal["Feature"]
    id: SuburbId
    properties: BoundaryProperties
    geometry: GeoJsonGeometry | None = Field(
        description="Simplified display geometry; null when the source geometry is invalid"
    )


class SuburbWithBoundary(SuburbSummary):
    boundary: BoundaryFeature


class PointAmenityProperties(_Closed):
    amenity_id: str
    category: str
    name: str | None
    source_feature_id: str | None
    source_updated_at: str | None
    match: Literal["covers"]
    operational_status: Literal["operational", "non-operational"] | None
    operational_status_code: int | None


class ReserveProperties(_Closed):
    amenity_id: str
    category: Literal["protected-reserve"]
    name: str | None
    source_feature_id: str | None
    source_updated_at: str | None
    match: Literal["intersects"]
    reserve_type: str | None
    coverage_note: str | None
    display_clipped: bool


class MapFeature(_Closed):
    type: Literal["Feature"]
    id: str
    properties: SchoolPointRecord | PointAmenityProperties | ReserveProperties
    geometry: GeoJsonGeometry | None


class MapFeatureCollection(_Closed):
    type: Literal["FeatureCollection"]
    features: list[MapFeature]


class MapContextRequestEcho(_Closed):
    categories: list[str] = Field(min_length=1, max_length=12)
    detail: DetailLevel
    tolerance_degrees: float
    limit: int = Field(ge=1, le=1000)
    operational: Literal["current", "all"]


class LayerDetail(_Closed):
    category: str
    description: str
    dataset_id: str
    source_layer: str | None
    geometry: Literal["point", "polygon"]
    predicate: Literal["ST_Covers", "ST_Intersects"]
    limit: int
    operational_filter: Literal["current", "all"]
    matched_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    excluded_non_operational: int = Field(ge=0)
    excluded_invalid_geometry: int = Field(ge=0)
    excluded_missing_geometry: int = Field(ge=0)
    feature_count: int = Field(ge=0)
    truncated: bool
    reason: LayerReason | None
    stale: bool


class MapContextLimits(_Closed):
    max_categories: int
    default_layer_limit: int
    max_layer_limit: int
    max_response_vertices: int
    max_response_bytes: int
    coordinate_decimals: int


class SuburbMapContextV1(_Closed):
    schema_version: Literal["propertyscope.suburb-map-context.v1"]
    geography: Literal["nsw-gazetted-suburb"]
    suburb: SuburbWithBoundary
    request: MapContextRequestEcho
    layers: dict[str, MapFeatureCollection]
    coverage: dict[str, CoverageState] = Field(
        description="'boundary' plus one entry per requested category"
    )
    layer_details: dict[str, LayerDetail]
    releases: dict[str, ReleaseReference | None]
    truncated: bool
    limits: MapContextLimits
    response_vertices: int = Field(ge=0)


SUBURB_MAP_SCHEMA_MODELS: dict[str, type[BaseModel]] = {
    "suburb-search.v1.schema.json": SuburbSearchV1,
    "suburb-detail.v1.schema.json": SuburbDetailV1,
    "suburb-map-context.v1.schema.json": SuburbMapContextV1,
}
