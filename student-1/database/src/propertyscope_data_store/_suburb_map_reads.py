"""Accepted-generation suburb search, detail and map-context projections.

Every read resolves the accepted pointers once and then uses those release IDs explicitly, inside
one read-only repeatable-read snapshot supplied by the repository. Candidate, superseded and
rejected rows can therefore never enter a response, and one response never mixes two
generations of the same dataset. Precise source geometry answers every spatial predicate;
precomputed simplified geometry is used only for display.
"""

# SQL statements stay line-oriented so accepted-evidence policy remains reviewable.

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, Protocol

from propertyscope_data_store.errors import (
    ResponseLimitExceededError,
    SuburbBoundariesUnavailableError,
    SuburbNotFoundError,
    UnsupportedCategoryError,
    ValidationError,
)
from propertyscope_data_store.suburb_map_catalog import (
    AMENITY_DATASET,
    BOUNDARY_DATASET,
    BOUNDARY_LAYER,
    BOUNDARY_SCHEMA,
    BOUNDARY_TARGET_FEATURE,
    COORDINATE_DECIMALS,
    DECLINED_CATEGORIES,
    DEFAULT_CATEGORIES,
    DEFAULT_DETAIL,
    DEFAULT_LAYER_LIMIT,
    DETAIL_TOLERANCES,
    FRESHNESS_DAYS,
    MAP_CATEGORIES,
    MAP_CATEGORIES_BY_KEY,
    MAX_CATEGORIES,
    MAX_LAYER_LIMIT,
    MAX_RESPONSE_BYTES,
    MAX_RESPONSE_VERTICES,
    MAX_SEARCH_RESULTS,
    OPERATIONAL_STATUS_CODE,
    RESERVE_CLIP_MARGIN,
    SCHOOL_DATASET,
    SUBURB_DETAIL_SCHEMA,
    SUBURB_MAP_CONTEXT_SCHEMA,
    SUBURB_MAP_PROJECTION_VERSION,
    SUBURB_SEARCH_SCHEMA,
    DetailLevel,
    MapCategory,
    detail_for_zoom,
)

JsonObject = dict[str, Any]
Coverage = Literal["accepted", "partial", "stale", "unavailable"]
OperationalFilter = Literal["current", "all"]
_SUBURB_ID = re.compile(r"^[1-9][0-9]{0,11}$")
_POSTCODE = re.compile(r"^[0-9]{4}$")
# Accepted pointers that may contribute to any suburb-map response.
_POINTER_KEYS = (
    (BOUNDARY_DATASET, BOUNDARY_TARGET_FEATURE),
    *sorted({(category.dataset_id, category.target_feature) for category in MAP_CATEGORIES}),
)


class SnapshotReader(Protocol):
    """One read-only snapshot; every statement sees the same committed state."""

    def fetch_one(
        self, query: str, params: Sequence[Any] | Mapping[str, Any]
    ) -> JsonObject | None: ...

    def fetch_all(
        self, query: str, params: Sequence[Any] | Mapping[str, Any]
    ) -> list[JsonObject]: ...


@dataclass(frozen=True)
class LayerPage:
    """Bounded feature rows for one layer plus its untruncated totals."""

    features: list[JsonObject]
    totals: JsonObject


@dataclass(frozen=True)
class MapContextRequest:
    """A validated, normalised map-context request; also the cache-key input."""

    suburb_id: str
    categories: tuple[str, ...]
    detail: DetailLevel
    limit: int
    operational: OperationalFilter

    def cache_fields(self) -> JsonObject:
        return {
            "suburb_id": self.suburb_id,
            "categories": list(self.categories),
            "detail": self.detail,
            "limit": self.limit,
            "operational": self.operational,
        }


def normalise_suburb_name(value: str) -> str:
    """Upper-case, punctuation-neutral name matching the projection's ``name_normalised``."""
    return re.sub(r"[^A-Z0-9]+", " ", value.upper()).strip()


def validate_suburb_id(value: str) -> str:
    if not _SUBURB_ID.fullmatch(value):
        raise ValidationError("suburb_id must be the publisher cadid: 1 to 12 digits")
    return value


def parse_categories(raw: str | None) -> tuple[str, ...]:
    """Validate the requested categories, keeping first-seen order and removing duplicates."""
    if raw is None or not raw.strip():
        return DEFAULT_CATEGORIES
    requested: list[str] = []
    for token in raw.split(","):
        key = token.strip().lower()
        if not key:
            continue
        if key in DECLINED_CATEGORIES:
            raise UnsupportedCategoryError(
                f"category '{key}' is not published: {DECLINED_CATEGORIES[key]}"
            )
        if key not in MAP_CATEGORIES_BY_KEY:
            supported = ", ".join(category.key for category in MAP_CATEGORIES)
            raise UnsupportedCategoryError(
                f"category '{key[:60]}' is not supported; supported categories: {supported}"
            )
        if key not in requested:
            requested.append(key)
    if not requested:
        return DEFAULT_CATEGORIES
    if len(requested) > MAX_CATEGORIES:
        raise ValidationError(f"at most {MAX_CATEGORIES} categories may be requested at once")
    return tuple(requested)


MAP_CONTEXT_QUERY_FIELDS = frozenset({"categories", "detail", "zoom", "limit", "operational"})


def build_map_context_request(suburb_id: str, args: Mapping[str, str]) -> MapContextRequest:
    """Validate query parameters; unsafe or unknown values are rejected, never clamped."""
    unknown = sorted(set(args) - MAP_CONTEXT_QUERY_FIELDS)
    if unknown:
        raise ValidationError(f"unsupported map-context query field: {unknown[0][:40]}")
    detail_text = args.get("detail", "").strip().lower()
    zoom_text = args.get("zoom", "").strip()
    if detail_text and zoom_text:
        raise ValidationError("supply either detail or zoom, not both")
    detail: DetailLevel = DEFAULT_DETAIL
    if detail_text:
        levels: dict[str, DetailLevel] = {level: level for level in DETAIL_TOLERANCES}
        if detail_text not in levels:
            raise ValidationError("detail must be one of low, medium, high")
        detail = levels[detail_text]
    elif zoom_text:
        if not re.fullmatch(r"[0-9]{1,2}", zoom_text) or int(zoom_text) > 22:
            raise ValidationError("zoom must be an integer between 0 and 22")
        detail = detail_for_zoom(int(zoom_text))
    limit_text = args.get("limit", "").strip()
    limit = DEFAULT_LAYER_LIMIT
    if limit_text:
        if not re.fullmatch(r"[0-9]{1,6}", limit_text) or not 1 <= int(limit_text) <= (
            MAX_LAYER_LIMIT
        ):
            raise ValidationError(f"limit must be an integer between 1 and {MAX_LAYER_LIMIT}")
        limit = int(limit_text)
    operational = args.get("operational", "current").strip().lower() or "current"
    if operational not in {"current", "all"}:
        raise ValidationError("operational must be current or all")
    return MapContextRequest(
        suburb_id=validate_suburb_id(suburb_id),
        categories=parse_categories(args.get("categories")),
        detail=detail,
        limit=limit,
        operational=operational,  # type: ignore[arg-type]
    )


def map_context_etag(request: MapContextRequest, release_ids: Mapping[str, str | None]) -> str:
    """Strong validator from the contract, normalised request and every accepted release used."""
    material = json.dumps(
        {
            "schema": SUBURB_MAP_CONTEXT_SCHEMA,
            "projection": SUBURB_MAP_PROJECTION_VERSION,
            "request": request.cache_fields(),
            "releases": dict(sorted(release_ids.items())),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f'"smc1-{hashlib.sha256(material.encode()).hexdigest()[:40]}"'


def suburb_detail_etag(suburb_id: str, boundary_release_id: str | None) -> str:
    material = f"{SUBURB_DETAIL_SCHEMA}|{SUBURB_MAP_PROJECTION_VERSION}|{suburb_id}|"
    material += boundary_release_id or "none"
    return f'"sd1-{hashlib.sha256(material.encode()).hexdigest()[:40]}"'


def relevant_datasets(categories: Iterable[str]) -> tuple[str, ...]:
    datasets = {BOUNDARY_DATASET}
    datasets.update(MAP_CATEGORIES_BY_KEY[key].dataset_id for key in categories)
    return tuple(sorted(datasets))


def coverage_state(*, available: bool, partial: bool, stale: bool) -> Coverage:
    """Collapse layer evidence into one state; ``layer_details`` keeps every flag."""
    if not available:
        return "unavailable"
    if partial:
        return "partial"
    if stale:
        return "stale"
    return "accepted"


class SuburbMapReads:
    """Suburb-map queries over one injected snapshot."""

    def __init__(self, reader: SnapshotReader) -> None:
        self._reader = reader

    # Accepted pointers -------------------------------------------------------------------

    def accepted_releases(self) -> tuple[dict[str, JsonObject], Any]:
        """Resolve every suburb-map pointer once, with publisher provenance."""
        pairs = [value for pair in _POINTER_KEYS for value in pair]
        placeholders = ",".join("(%s,%s)" for _ in _POINTER_KEYS)
        rows = self._reader.fetch_all(
            f"""/* suburb-map:releases */
            SELECT release.dataset_id,release.target_feature,
                   release.id::text AS dataset_release_id,release.release_version,
                   release.schema_version,release.accepted_at,
                   release.created_at AS acquired_at,source.publisher,
                   source.name AS source_name,source.source_url,source.licence_id,
                   source.licence_url,now() AS observed_at
            FROM serving.accepted_generation accepted
            JOIN ops.dataset_release release ON release.id=accepted.dataset_release_id
             AND release.status='accepted'
            JOIN ops.source_definition source ON source.id=release.source_definition_id
            WHERE (accepted.dataset_id,accepted.target_feature) IN ({placeholders})
            ORDER BY release.dataset_id""",  # noqa: S608 - placeholders only; values are bound
            pairs,
        )
        observed_at: Any = None
        releases: dict[str, JsonObject] = {}
        for row in rows:
            observed_at = row.pop("observed_at", None) or observed_at
            releases[str(row["dataset_id"])] = row
        return releases, observed_at

    def release_pointers(self, datasets: Iterable[str]) -> dict[str, str | None]:
        releases, _ = self.accepted_releases()
        return {
            dataset: (str(releases[dataset]["dataset_release_id"]) if dataset in releases else None)
            for dataset in datasets
        }

    # Search and detail ---------------------------------------------------------------------

    def search(self, query: str, *, postcode: str | None, limit: int) -> JsonObject:
        normalised = normalise_suburb_name(query)
        if not normalised or not re.search(r"[A-Z]", normalised):
            raise ValidationError("q must contain a suburb name")
        if len(query) > 100:
            raise ValidationError("q must be at most 100 characters")
        if postcode is not None and not _POSTCODE.fullmatch(postcode):
            raise ValidationError("postcode must contain four digits")
        if not 1 <= limit <= MAX_SEARCH_RESULTS:
            raise ValidationError(f"limit must be between 1 and {MAX_SEARCH_RESULTS}")
        releases, _ = self.accepted_releases()
        boundary = _compatible(releases.get(BOUNDARY_DATASET), BOUNDARY_SCHEMA)
        base: JsonObject = {
            "schema_version": SUBURB_SEARCH_SCHEMA,
            "geography": BOUNDARY_LAYER,
            "query": {"q": query, "normalised": normalised, "postcode": postcode},
        }
        if boundary is None:
            return {
                **base,
                "availability": {
                    "status": "dataset_unavailable",
                    "reason": "No compatible accepted NSW gazetted suburb release is available.",
                },
                "match": "none",
                "items": [],
                "count": 0,
                "has_more": False,
                "release": None,
            }
        rows = self._reader.fetch_all(
            """/* suburb-map:search */
            SELECT suburb_id,name,postcode,geometry_status,
                   ST_X(centroid) AS centroid_longitude,ST_Y(centroid) AS centroid_latitude,
                   ST_X(label_point) AS label_longitude,ST_Y(label_point) AS label_latitude,
                   min_longitude,min_latitude,max_longitude,max_latitude
            FROM serving.suburb_boundary_display
            WHERE dataset_release_id=%s AND name_normalised=%s
              AND (%s::text IS NULL OR postcode=%s)
            ORDER BY postcode NULLS LAST,suburb_id
            LIMIT %s""",
            (boundary["dataset_release_id"], normalised, postcode, postcode, limit + 1),
        )
        has_more = len(rows) > limit
        items = [_suburb_summary(row) for row in rows[:limit]]
        match = "none" if not items else "unique" if len(items) == 1 else "ambiguous"
        return {
            **base,
            "availability": {
                "status": "available",
                "reason": "Exact normalised name match within the accepted suburb release.",
            },
            "match": match,
            "items": items,
            "count": len(items),
            "has_more": has_more,
            "release": _release_ref(boundary, source_updated_at=None),
        }

    def detail(self, suburb_id: str) -> JsonObject:
        validate_suburb_id(suburb_id)
        releases, observed_at = self.accepted_releases()
        boundary_release = self._boundary_release(releases)
        row = self._suburb_row(boundary_release, suburb_id, detail=None)
        source = (
            self._reader.fetch_one(
                """/* suburb-map:source */
            SELECT attributes->>'urbanity' AS urbanity,
                   attributes->>'publisher_edition' AS publisher_edition,
                   CASE WHEN attributes->>'startdate' ~ '^-?[0-9]{1,15}$'
                        THEN to_timestamp((attributes->>'startdate')::bigint/1000.0) END
                        AS start_date,
                   CASE WHEN attributes->>'lastupdate' ~ '^-?[0-9]{1,15}$'
                        THEN to_timestamp((attributes->>'lastupdate')::bigint/1000.0) END
                        AS last_update
            FROM warehouse.reference_feature
            WHERE dataset_release_id=%s AND layer=%s AND record_id=%s""",
                (boundary_release["dataset_release_id"], BOUNDARY_LAYER, row["record_id"]),
            )
            or {}
        )
        stale = _is_stale(boundary_release, observed_at)
        return {
            "schema_version": SUBURB_DETAIL_SCHEMA,
            "geography": BOUNDARY_LAYER,
            **_suburb_summary(row),
            "source": {
                "record_id": row["record_id"],
                "source_updated_at": row.get("source_updated_at"),
                "valid_from": row.get("valid_from"),
                "start_date": source.get("start_date"),
                "last_update": source.get("last_update"),
                "urbanity": source.get("urbanity"),
                "publisher_edition": source.get("publisher_edition"),
            },
            "display": {
                "source_vertex_count": row["source_vertex_count"],
                "levels": {
                    level: {
                        "tolerance_degrees": DETAIL_TOLERANCES[level],
                        "vertex_count": row.get(f"display_{level}_vertices"),
                    }
                    for level in DETAIL_TOLERANCES
                },
            },
            "coverage": "unavailable"
            if row["geometry_status"] != "valid"
            else ("stale" if stale else "accepted"),
            "release": _release_ref(
                boundary_release, source_updated_at=row.get("source_updated_at")
            ),
        }

    # Map context ---------------------------------------------------------------------------

    def map_context(self, request: MapContextRequest) -> JsonObject:
        releases, observed_at = self.accepted_releases()
        boundary_release = self._boundary_release(releases)
        row = self._suburb_row(boundary_release, request.suburb_id, detail=request.detail)
        valid_boundary = row["geometry_status"] == "valid"
        boundary_stale = _is_stale(boundary_release, observed_at)
        boundary_feature = {
            "type": "Feature",
            "id": row["suburb_id"],
            "properties": {
                "suburb_id": row["suburb_id"],
                "name": row["name"],
                "postcode": row.get("postcode"),
                "detail": request.detail,
                "tolerance_degrees": DETAIL_TOLERANCES[request.detail],
                "source_vertex_count": row["source_vertex_count"],
                "display_vertex_count": row.get("display_vertices"),
            },
            "geometry": row.get("display_geometry") if valid_boundary else None,
        }
        layers: dict[str, JsonObject] = {}
        details: dict[str, JsonObject] = {}
        coverage: dict[str, Coverage] = {
            "boundary": coverage_state(
                available=valid_boundary, partial=False, stale=boundary_stale
            )
        }
        release_refs: dict[str, JsonObject | None] = {
            "boundary": _release_ref(
                boundary_release, source_updated_at=row.get("source_updated_at")
            )
        }
        bbox = _bbox(row)
        clip_box = _expanded(bbox) if bbox else None
        amenity_keys = [
            key
            for key in request.categories
            if MAP_CATEGORIES_BY_KEY[key].dataset_id == AMENITY_DATASET
        ]
        amenity_release = _compatible(releases.get(AMENITY_DATASET), BOUNDARY_SCHEMA)
        school_release = _compatible(
            releases.get(SCHOOL_DATASET), MAP_CATEGORIES_BY_KEY["schools"].schema_version
        )
        amenity_stats: dict[str, JsonObject] = {}
        amenity_pages: dict[str, LayerPage] = {}
        if valid_boundary and amenity_keys and amenity_release is not None and clip_box:
            amenity_stats = self._amenity_layer_stats(
                amenity_release, boundary_release, row["record_id"], amenity_keys
            )
            amenity_pages = self._amenity_features(
                amenity_release,
                boundary_release,
                row["record_id"],
                [key for key in amenity_keys if key in amenity_stats],
                request,
                clip_box,
            )
        school_page: tuple[list[JsonObject], JsonObject] | None = None
        if valid_boundary and "schools" in request.categories and school_release is not None:
            school_page = self._school_features(
                school_release, boundary_release, row["record_id"], request
            )
        for key in request.categories:
            category = MAP_CATEGORIES_BY_KEY[key]
            accepted = releases.get(category.dataset_id)
            compatible = _compatible(accepted, category.schema_version)
            detail = _base_layer_detail(category, request)
            features: list[JsonObject] = []
            reason: str | None = None
            source_updated_at: str | None = None
            if not valid_boundary:
                reason = "boundary_geometry_unavailable"
            elif accepted is None:
                reason = "dataset_unavailable"
            elif compatible is None:
                reason = "unsupported_schema"
            elif category.dataset_id == SCHOOL_DATASET and school_page is not None:
                features, counts = school_page
                detail.update(counts)
            elif category.dataset_id == AMENITY_DATASET:
                stats = amenity_stats.get(key)
                if stats is None:
                    reason = "layer_not_in_release"
                else:
                    source_updated_at = stats.get("source_updated_at")
                    page = amenity_pages.get(key)
                    features = [
                        _amenity_feature(category, item) for item in (page.features if page else [])
                    ]
                    matched = page.totals if page else {}
                    detail.update(
                        {
                            "matched_count": int(matched.get("matched_total") or 0),
                            "eligible_count": int(matched.get("eligible_total") or 0),
                            "excluded_non_operational": int(matched.get("non_operational") or 0)
                            if request.operational == "current"
                            else 0,
                            "excluded_invalid_geometry": int(stats.get("invalid_near") or 0),
                            "excluded_missing_geometry": int(stats.get("missing_geometry") or 0),
                        }
                    )
            detail["feature_count"] = len(features)
            detail["truncated"] = detail.get("eligible_count", 0) > len(features)
            detail["reason"] = reason
            stale = compatible is not None and _is_stale(compatible, observed_at)
            detail["stale"] = stale
            partial = bool(
                detail["truncated"]
                or detail.get("excluded_invalid_geometry")
                or detail.get("excluded_missing_geometry")
            )
            coverage[key] = coverage_state(available=reason is None, partial=partial, stale=stale)
            layers[key] = {"type": "FeatureCollection", "features": features}
            details[key] = detail
            release_refs[key] = (
                _release_ref(compatible, source_updated_at=source_updated_at)
                if compatible is not None
                else None
            )
        vertices = (
            int(row.get("display_vertices") or 0)
            + sum(
                int(item.get("vertices") or 0)
                for page in amenity_pages.values()
                for item in page.features
            )
            + (len(school_page[0]) if school_page else 0)
        )
        if vertices > MAX_RESPONSE_VERTICES:
            raise ResponseLimitExceededError(
                f"the response would contain {vertices} coordinates, above the "
                f"{MAX_RESPONSE_VERTICES} limit; request fewer categories, a lower limit "
                "or a lower detail"
            )
        return {
            "schema_version": SUBURB_MAP_CONTEXT_SCHEMA,
            "geography": BOUNDARY_LAYER,
            "suburb": {**_suburb_summary(row), "boundary": boundary_feature},
            "request": {
                "categories": list(request.categories),
                "detail": request.detail,
                "tolerance_degrees": DETAIL_TOLERANCES[request.detail],
                "limit": request.limit,
                "operational": request.operational,
            },
            "layers": layers,
            "coverage": coverage,
            "layer_details": details,
            "releases": release_refs,
            "truncated": any(item["truncated"] for item in details.values()),
            "limits": map_context_limits(),
            "response_vertices": vertices,
        }

    # Internals -----------------------------------------------------------------------------

    def _boundary_release(self, releases: Mapping[str, JsonObject]) -> JsonObject:
        boundary = _compatible(releases.get(BOUNDARY_DATASET), BOUNDARY_SCHEMA)
        if boundary is None:
            raise SuburbBoundariesUnavailableError(
                "No compatible accepted NSW gazetted suburb release is available"
            )
        return boundary

    def _suburb_row(
        self, boundary_release: Mapping[str, Any], suburb_id: str, *, detail: DetailLevel | None
    ) -> JsonObject:
        display_columns = (
            f""",ST_AsGeoJSON(display_{detail},{COORDINATE_DECIMALS})::jsonb AS display_geometry,
                   display_{detail}_vertices AS display_vertices"""
            if detail in DETAIL_TOLERANCES
            else ""
        )
        row = self._reader.fetch_one(
            f"""/* suburb-map:suburb */
            SELECT suburb_id,record_id,name,postcode,geometry_status,
                   ST_X(centroid) AS centroid_longitude,ST_Y(centroid) AS centroid_latitude,
                   ST_X(label_point) AS label_longitude,ST_Y(label_point) AS label_latitude,
                   min_longitude,min_latitude,max_longitude,max_latitude,source_vertex_count,
                   display_low_vertices,display_medium_vertices,display_high_vertices,
                   source_updated_at,valid_from{display_columns}
            FROM serving.suburb_boundary_display
            WHERE dataset_release_id=%s AND suburb_id=%s""",  # noqa: S608 - fixed column names
            (boundary_release["dataset_release_id"], suburb_id),
        )
        if row is not None:
            return row
        projected = self._reader.fetch_one(
            """/* suburb-map:projection-present */
            SELECT EXISTS (SELECT 1 FROM serving.suburb_boundary_display
                           WHERE dataset_release_id=%s) AS present""",
            (boundary_release["dataset_release_id"],),
        )
        if not (projected or {}).get("present"):
            raise SuburbBoundariesUnavailableError(
                "The accepted suburb release has no display projection yet"
            )
        raise SuburbNotFoundError(
            f"suburb {suburb_id} is not in the accepted NSW gazetted suburb release"
        )

    def _amenity_layer_stats(
        self,
        amenity_release: Mapping[str, Any],
        boundary_release: Mapping[str, Any],
        record_id: str,
        layers: Sequence[str],
    ) -> dict[str, JsonObject]:
        rows = self._reader.fetch_all(
            """/* suburb-map:amenity-stats */
            WITH boundary AS MATERIALIZED (
                SELECT geom FROM warehouse.reference_feature
                WHERE dataset_release_id=%s AND layer=%s AND record_id=%s
                  AND geometry_status='valid'
            )
            SELECT feature.layer,count(*) AS layer_rows,
                   max(feature.source_updated_at) AS source_updated_at,
                   count(*) FILTER (WHERE feature.geom IS NULL) AS missing_geometry,
                   count(*) FILTER (
                       WHERE feature.geometry_status='invalid' AND feature.geom && boundary.geom
                   ) AS invalid_near
            FROM warehouse.reference_feature feature CROSS JOIN boundary
            WHERE feature.dataset_release_id=%s AND feature.layer = ANY(%s)
            GROUP BY feature.layer""",
            (
                boundary_release["dataset_release_id"],
                BOUNDARY_LAYER,
                record_id,
                amenity_release["dataset_release_id"],
                list(layers),
            ),
        )
        return {str(row["layer"]): row for row in rows}

    def _amenity_features(
        self,
        amenity_release: Mapping[str, Any],
        boundary_release: Mapping[str, Any],
        record_id: str,
        layers: Sequence[str],
        request: MapContextRequest,
        clip_box: tuple[float, float, float, float],
    ) -> dict[str, LayerPage]:
        if not layers:
            return {}
        polygon_layers = [key for key in layers if MAP_CATEGORIES_BY_KEY[key].geometry == "polygon"]
        tolerance = DETAIL_TOLERANCES[request.detail]
        rows = self._reader.fetch_all(
            f"""/* suburb-map:amenity-features */
            WITH boundary AS MATERIALIZED (
                SELECT geom FROM warehouse.reference_feature
                WHERE dataset_release_id=%(boundary_release)s AND layer=%(boundary_layer)s
                  AND record_id=%(record_id)s AND geometry_status='valid'
            ), matched AS MATERIALIZED (
                SELECT feature.layer,feature.record_id,feature.name,feature.attributes,
                       feature.source_updated_at,feature.geom,
                       CASE WHEN feature.attributes->>'operationalstatus' ~ '^[0-9]{{1,4}}$'
                            THEN (feature.attributes->>'operationalstatus')::integer
                       END AS status_code
                FROM warehouse.reference_feature feature CROSS JOIN boundary
                WHERE feature.dataset_release_id=%(amenity_release)s
                  AND feature.layer = ANY(%(layers)s)
                  AND feature.geometry_status='valid'
                  AND feature.geom && boundary.geom
                  AND CASE WHEN feature.layer = ANY(%(polygon_layers)s)
                           THEN ST_Intersects(boundary.geom,feature.geom)
                           ELSE ST_Covers(boundary.geom,feature.geom) END
            ), totals AS (
                SELECT layer,count(*) AS matched_total,
                       count(*) FILTER (
                           WHERE status_code IS NOT NULL AND status_code<>%(operational_code)s
                       ) AS non_operational
                FROM matched GROUP BY layer
            ), eligible AS (
                SELECT matched.*,
                       row_number() OVER (
                           PARTITION BY layer ORDER BY name NULLS LAST,record_id
                       ) AS rank,
                       count(*) OVER (PARTITION BY layer) AS eligible_total
                FROM matched
                WHERE %(include_all)s OR status_code IS NULL
                   OR status_code=%(operational_code)s
            ), clip AS MATERIALIZED (
                SELECT ST_MakeEnvelope(%(xmin)s,%(ymin)s,%(xmax)s,%(ymax)s,4326) AS box
            ), page AS (
                SELECT eligible.*,
                       CASE WHEN eligible.layer = ANY(%(polygon_layers)s)
                            THEN ST_SimplifyPreserveTopology(ST_CollectionExtract(
                                ST_Intersection(eligible.geom,clip.box),3),%(tolerance)s)
                            ELSE eligible.geom END AS display_geom,
                       eligible.layer = ANY(%(polygon_layers)s)
                           AND NOT ST_CoveredBy(eligible.geom,clip.box) AS display_clipped
                FROM eligible CROSS JOIN clip
                WHERE eligible.rank <= %(limit)s
            )
            SELECT totals.layer,totals.matched_total,totals.non_operational,
                   COALESCE(page.eligible_total,
                            (SELECT count(*) FROM eligible WHERE eligible.layer=totals.layer))
                       AS eligible_total,
                   page.record_id,page.name,page.status_code,
                   page.attributes->>'topoid' AS topoid,
                   page.attributes->>'cadid' AS cadid,
                   page.attributes->>'reservetype' AS reserve_type,
                   page.attributes->>'coverage_note' AS coverage_note,
                   page.source_updated_at,page.display_clipped,
                   ST_AsGeoJSON(page.display_geom,{COORDINATE_DECIMALS})::jsonb AS geometry,
                   ST_NPoints(page.display_geom) AS vertices
            FROM totals LEFT JOIN page ON page.layer=totals.layer
            ORDER BY totals.layer,page.rank""",  # noqa: S608 - fixed integer precision only
            {
                "boundary_release": boundary_release["dataset_release_id"],
                "boundary_layer": BOUNDARY_LAYER,
                "record_id": record_id,
                "amenity_release": amenity_release["dataset_release_id"],
                "layers": list(layers),
                "polygon_layers": polygon_layers,
                "operational_code": OPERATIONAL_STATUS_CODE,
                "include_all": request.operational == "all",
                "xmin": clip_box[0],
                "ymin": clip_box[1],
                "xmax": clip_box[2],
                "ymax": clip_box[3],
                "tolerance": tolerance,
                "limit": request.limit,
            },
        )
        pages: dict[str, LayerPage] = {}
        for row in rows:
            layer = str(row["layer"])
            page = pages.setdefault(layer, LayerPage(features=[], totals=row))
            # A layer whose matches were all filtered out still reports its totals.
            if row.get("record_id") is not None:
                page.features.append(row)
        return pages

    def _school_features(
        self,
        school_release: Mapping[str, Any],
        boundary_release: Mapping[str, Any],
        record_id: str,
        request: MapContextRequest,
    ) -> tuple[list[JsonObject], JsonObject]:
        rows = self._reader.fetch_all(
            """/* suburb-map:school-features */
            WITH boundary AS MATERIALIZED (
                SELECT geom FROM warehouse.reference_feature
                WHERE dataset_release_id=%(boundary_release)s AND layer=%(boundary_layer)s
                  AND record_id=%(record_id)s AND geometry_status='valid'
            ), matched AS MATERIALIZED (
                SELECT school.*,lower(school.status)='open' AS is_current
                FROM warehouse.school school CROSS JOIN boundary
                WHERE school.dataset_release_id=%(school_release)s
                  AND school.geom && boundary.geom
                  AND ST_Covers(boundary.geom,school.geom)
            ), eligible AS (
                SELECT matched.*,
                       row_number() OVER (ORDER BY school_name,school_code) AS rank,
                       count(*) OVER () AS eligible_total
                FROM matched WHERE %(include_all)s OR is_current
            ), totals AS (
                SELECT count(*) AS matched_total,
                       count(*) FILTER (WHERE NOT is_current) AS non_operational
                FROM matched
            )
            SELECT totals.matched_total,totals.non_operational,
                   COALESCE(page.eligible_total,0) AS eligible_total,page.school_code,
                   page.school_name,page.school_type,page.status,page.locality_original,
                   page.locality_normalised,page.lga_name,
                   ST_X(page.geom) AS longitude,ST_Y(page.geom) AS latitude,
                   page.source_row_sha256,page.normalisation_version
            FROM totals LEFT JOIN (
                SELECT * FROM eligible WHERE rank <= %(limit)s
            ) page ON true
            ORDER BY page.rank""",
            {
                "boundary_release": boundary_release["dataset_release_id"],
                "boundary_layer": BOUNDARY_LAYER,
                "record_id": record_id,
                "school_release": school_release["dataset_release_id"],
                "include_all": request.operational == "all",
                "limit": request.limit,
            },
        )
        first = rows[0] if rows else {}
        features = [
            _school_feature(school_release, row)
            for row in rows
            if row.get("school_code") is not None
        ]
        counts = {
            "matched_count": int(first.get("matched_total") or 0),
            "eligible_count": int(first.get("eligible_total") or 0),
            "excluded_non_operational": int(first.get("non_operational") or 0)
            if request.operational == "current"
            else 0,
            "excluded_invalid_geometry": 0,
            "excluded_missing_geometry": 0,
        }
        return features, counts


def map_context_limits() -> JsonObject:
    return {
        "max_categories": MAX_CATEGORIES,
        "default_layer_limit": DEFAULT_LAYER_LIMIT,
        "max_layer_limit": MAX_LAYER_LIMIT,
        "max_response_vertices": MAX_RESPONSE_VERTICES,
        "max_response_bytes": MAX_RESPONSE_BYTES,
        "coordinate_decimals": COORDINATE_DECIMALS,
    }


def _compatible(release: JsonObject | None, schema_version: str) -> JsonObject | None:
    if release is None or release.get("schema_version") != schema_version:
        return None
    return release


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _is_stale(release: Mapping[str, Any], observed_at: Any) -> bool:
    """Apply Feature 1's per-dataset freshness window to the release acquisition time."""
    acquired_at = _timestamp(release.get("acquired_at"))
    observed = _timestamp(observed_at)
    window = FRESHNESS_DAYS.get(str(release.get("dataset_id")))
    if observed is None or acquired_at is None or window is None:
        return False
    return observed - acquired_at > timedelta(days=window)


def _release_ref(release: Mapping[str, Any], *, source_updated_at: str | None) -> JsonObject:
    return {
        "dataset_id": release["dataset_id"],
        "target_feature": release["target_feature"],
        "dataset_release_id": str(release["dataset_release_id"]),
        "release_version": release["release_version"],
        "schema_version": release["schema_version"],
        "accepted_at": release.get("accepted_at"),
        "acquired_at": release.get("acquired_at"),
        "source_updated_at": source_updated_at,
        "publisher": release.get("publisher"),
        "source_name": release.get("source_name"),
        "source_url": release.get("source_url"),
        "licence_id": release.get("licence_id"),
        "licence_url": release.get("licence_url"),
        "freshness_days": FRESHNESS_DAYS.get(str(release["dataset_id"])),
    }


def _point(longitude: Any, latitude: Any) -> list[float] | None:
    if longitude is None or latitude is None:
        return None
    return [
        round(float(longitude), COORDINATE_DECIMALS),
        round(float(latitude), COORDINATE_DECIMALS),
    ]


def _bbox(row: Mapping[str, Any]) -> list[float] | None:
    values = [
        row.get(key) for key in ("min_longitude", "min_latitude", "max_longitude", "max_latitude")
    ]
    numbers = [float(value) for value in values if value is not None]
    if len(numbers) != len(values):
        return None
    return [round(value, COORDINATE_DECIMALS) for value in numbers]


def _expanded(bbox: Sequence[float]) -> tuple[float, float, float, float]:
    width = (bbox[2] - bbox[0]) * RESERVE_CLIP_MARGIN
    height = (bbox[3] - bbox[1]) * RESERVE_CLIP_MARGIN
    return (bbox[0] - width, bbox[1] - height, bbox[2] + width, bbox[3] + height)


def _suburb_summary(row: Mapping[str, Any]) -> JsonObject:
    return {
        "suburb_id": str(row["suburb_id"]),
        "name": row["name"],
        "postcode": row.get("postcode"),
        "state": "NSW",
        "geometry_status": row["geometry_status"],
        "centroid": _point(row.get("centroid_longitude"), row.get("centroid_latitude")),
        "label_point": _point(row.get("label_longitude"), row.get("label_latitude")),
        "bbox": _bbox(row),
    }


def _base_layer_detail(category: MapCategory, request: MapContextRequest) -> JsonObject:
    return {
        "category": category.key,
        "description": category.description,
        "dataset_id": category.dataset_id,
        "source_layer": category.source_layer,
        "geometry": category.geometry,
        "predicate": "ST_Covers" if category.predicate == "covers" else "ST_Intersects",
        "limit": request.limit,
        "operational_filter": request.operational,
        "matched_count": 0,
        "eligible_count": 0,
        "excluded_non_operational": 0,
        "excluded_invalid_geometry": 0,
        "excluded_missing_geometry": 0,
    }


def _operational_label(code: Any) -> str | None:
    if code is None:
        return None
    return "operational" if int(code) == OPERATIONAL_STATUS_CODE else "non-operational"


def _amenity_feature(category: MapCategory, row: Mapping[str, Any]) -> JsonObject:
    properties: JsonObject = {
        "amenity_id": row["record_id"],
        "category": category.key,
        "name": row.get("name"),
        "source_feature_id": row.get("topoid") or row.get("cadid"),
        "source_updated_at": row.get("source_updated_at"),
        "match": "covers" if category.predicate == "covers" else "intersects",
    }
    if category.geometry == "point":
        properties["operational_status"] = _operational_label(row.get("status_code"))
        properties["operational_status_code"] = row.get("status_code")
    else:
        properties["reserve_type"] = row.get("reserve_type")
        properties["coverage_note"] = row.get("coverage_note")
        properties["display_clipped"] = bool(row.get("display_clipped"))
    return {
        "type": "Feature",
        "id": row["record_id"],
        "properties": properties,
        "geometry": row.get("geometry"),
    }


def _school_feature(release: Mapping[str, Any], row: Mapping[str, Any]) -> JsonObject:
    """Project one school with exactly the ``propertyscope.school-points.v2`` record shape."""
    record = {
        "school_code": str(row["school_code"]),
        "school_name": row["school_name"],
        "school_type": row["school_type"],
        "operational_status": row["status"],
        "locality_original": row["locality_original"],
        "locality_normalised": row["locality_normalised"],
        "state": "NSW",
        "lga": row.get("lga_name"),
        "latitude": float(row["latitude"]),
        "longitude": float(row["longitude"]),
        "provenance": {
            "release_id": str(release["dataset_release_id"]),
            "release_version": release["release_version"],
            "candidate_generation_id": str(release["dataset_release_id"]),
            "source_record_sha256": row["source_row_sha256"],
            "normalisation_version": row["normalisation_version"],
        },
    }
    return {
        "type": "Feature",
        "id": f"school:{record['school_code']}",
        "properties": record,
        "geometry": {"type": "Point", "coordinates": [record["longitude"], record["latitude"]]},
    }
