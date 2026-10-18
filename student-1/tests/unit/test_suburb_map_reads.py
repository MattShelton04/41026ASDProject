"""Deterministic tests for the accepted suburb-map projection reads.

A scripted snapshot reader answers each statement by its ``/* suburb-map:<tag> */`` comment with
rows shaped as the repository returns them (timestamps as ISO strings), so every coverage,
truncation and provenance rule is exercised without PostgreSQL.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from propertyscope_data_store._suburb_map_reads import (
    MapContextRequest,
    SuburbMapReads,
    build_map_context_request,
    coverage_state,
    map_context_etag,
    normalise_suburb_name,
    parse_categories,
    relevant_datasets,
    suburb_detail_etag,
    validate_suburb_id,
)
from propertyscope_data_store.errors import (
    ResponseLimitExceededError,
    SuburbBoundariesUnavailableError,
    SuburbNotFoundError,
    UnsupportedCategoryError,
    ValidationError,
)
from propertyscope_data_store.repository import PropertyScopeStore
from propertyscope_data_store.suburb_map_catalog import (
    AMENITY_DATASET,
    AMENITY_SOURCE_LAYERS,
    BOUNDARY_DATASET,
    BOUNDARY_LAYER,
    BOUNDARY_SCHEMA,
    DEFAULT_CATEGORIES,
    DEFAULT_LAYER_LIMIT,
    DETAIL_TOLERANCES,
    MAP_CATEGORIES,
    MAX_CATEGORIES,
    MAX_LAYER_LIMIT,
    MAX_RESPONSE_VERTICES,
    SCHOOL_DATASET,
    SCHOOL_SCHEMA,
)

JsonObject = dict[str, Any]
Scripted = JsonObject | list[JsonObject] | None

STUDENT_ROOT = Path(__file__).resolve().parents[2]
MIGRATION = (
    STUDENT_ROOT
    / "database"
    / "src"
    / "propertyscope_data_store"
    / "sql"
    / "064_suburb_map_projection.sql"
)
SCHOOL_POINTS_SCHEMA = STUDENT_ROOT / "contracts" / "school-points.v2.schema.json"

BOUNDARY_RELEASE = "10000000-0000-4000-8000-000000000001"
AMENITY_RELEASE = "20000000-0000-4000-8000-000000000002"
SCHOOL_RELEASE = "30000000-0000-4000-8000-000000000003"
OBSERVED_AT = "2026-10-17T00:00:00+00:00"
FRESH = "2026-09-01T00:00:00+00:00"
EXACTLY_400_DAYS = "2025-09-12T00:00:00+00:00"
STALE_401_DAYS = "2025-09-11T00:00:00+00:00"
SUBURB_ID = "108502"
SUBURB_RECORD = "nsw-gazetted-suburb:108502"
_TAG = re.compile(r"/\* suburb-map:([a-z-]+) \*/")


class ScriptedReader:
    """Answers each tagged statement with a deep copy of its scripted rows."""

    def __init__(self, responses: Mapping[str, Scripted]) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, Any]] = []

    def _answer(self, query: str, params: Sequence[Any] | Mapping[str, Any]) -> Scripted:
        match = _TAG.search(query)
        assert match is not None, "every suburb-map statement carries a tag comment"
        tag = match.group(1)
        self.calls.append((tag, params))
        if tag not in self.responses:
            raise AssertionError(f"unscripted suburb-map statement: {tag}")
        return copy.deepcopy(self.responses[tag])

    def fetch_one(self, query: str, params: Sequence[Any] | Mapping[str, Any]) -> JsonObject | None:
        value = self._answer(query, params)
        assert value is None or isinstance(value, dict)
        return value

    def fetch_all(self, query: str, params: Sequence[Any] | Mapping[str, Any]) -> list[JsonObject]:
        value = self._answer(query, params)
        assert isinstance(value, list)
        return value

    def tags(self) -> list[str]:
        return [tag for tag, _ in self.calls]

    def params(self, tag: str) -> Any:
        return next(params for called, params in self.calls if called == tag)


# Row builders ------------------------------------------------------------------------------


def release_row(
    dataset_id: str,
    release_id: str,
    *,
    schema_version: str | None = None,
    acquired_at: str = FRESH,
) -> JsonObject:
    schemas = {
        BOUNDARY_DATASET: BOUNDARY_SCHEMA,
        AMENITY_DATASET: BOUNDARY_SCHEMA,
        SCHOOL_DATASET: SCHOOL_SCHEMA,
    }
    return {
        "dataset_id": dataset_id,
        "target_feature": "feature-3" if dataset_id == SCHOOL_DATASET else "feature-1",
        "dataset_release_id": release_id,
        "release_version": f"{dataset_id}-2026.09",
        "schema_version": schema_version or schemas[dataset_id],
        "accepted_at": "2026-09-02T00:00:00+00:00",
        "acquired_at": acquired_at,
        "publisher": "NSW Government",
        "source_name": f"{dataset_id} source",
        "source_url": f"https://example.nsw.gov.au/{dataset_id}",
        "licence_id": "CC-BY-4.0",
        "licence_url": "https://creativecommons.org/licenses/by/4.0/",
        "observed_at": OBSERVED_AT,
    }


def all_releases(**overrides: JsonObject | None) -> list[JsonObject]:
    rows: dict[str, JsonObject | None] = {
        "boundary": release_row(BOUNDARY_DATASET, BOUNDARY_RELEASE),
        "amenity": release_row(AMENITY_DATASET, AMENITY_RELEASE),
        "school": release_row(SCHOOL_DATASET, SCHOOL_RELEASE),
    }
    rows.update(overrides)
    return [row for row in rows.values() if row is not None]


def suburb_row(*, valid: bool = True, **overrides: Any) -> JsonObject:
    row: JsonObject = {
        "suburb_id": SUBURB_ID,
        "record_id": SUBURB_RECORD,
        "name": "Ashfield",
        "postcode": "2131",
        "geometry_status": "valid",
        "centroid_longitude": 151.1234567,
        "centroid_latitude": -33.8876543,
        "label_longitude": 151.124,
        "label_latitude": -33.888,
        "min_longitude": 151.11,
        "min_latitude": -33.9,
        "max_longitude": 151.14,
        "max_latitude": -33.87,
        "source_vertex_count": 1200,
        "display_low_vertices": 80,
        "display_medium_vertices": 300,
        "display_high_vertices": 900,
        "source_updated_at": "2026-08-01T00:00:00+00:00",
        "valid_from": "2026-08-01",
        "display_geometry": {
            "type": "Polygon",
            "coordinates": [[[151.11, -33.9], [151.14, -33.9], [151.14, -33.87], [151.11, -33.9]]],
        },
        "display_vertices": 300,
    }
    if not valid:
        row.update(
            {
                "geometry_status": "invalid",
                "centroid_longitude": None,
                "centroid_latitude": None,
                "label_longitude": None,
                "label_latitude": None,
                "display_low_vertices": None,
                "display_medium_vertices": None,
                "display_high_vertices": None,
                "display_geometry": None,
                "display_vertices": None,
            }
        )
    row.update(overrides)
    return row


def stats_row(layer: str, **overrides: Any) -> JsonObject:
    row: JsonObject = {
        "layer": layer,
        "layer_rows": 300,
        "source_updated_at": "2026-07-01T00:00:00+00:00",
        "missing_geometry": 0,
        "invalid_near": 0,
    }
    row.update(overrides)
    return row


def amenity_row(layer: str, number: int, **overrides: Any) -> JsonObject:
    row: JsonObject = {
        "layer": layer,
        "matched_total": 1,
        "non_operational": 0,
        "eligible_total": 1,
        "record_id": f"{layer}:{number}",
        "name": f"{layer} {number}",
        "status_code": 1,
        "topoid": f"T{number}",
        "cadid": None,
        "reserve_type": None,
        "coverage_note": None,
        "source_updated_at": "2026-07-01T00:00:00+00:00",
        "display_clipped": None,
        "geometry": {"type": "Point", "coordinates": [151.12, -33.888]},
        "vertices": 1,
    }
    row.update(overrides)
    return row


def school_row(code: str, **overrides: Any) -> JsonObject:
    row: JsonObject = {
        "matched_total": 1,
        "non_operational": 0,
        "eligible_total": 1,
        "school_code": code,
        "school_name": f"School {code}",
        "school_type": "Primary School",
        "status": "Open",
        "locality_original": "Ashfield",
        "locality_normalised": "ASHFIELD",
        "lga_name": "Inner West",
        "longitude": 151.125,
        "latitude": -33.889,
        "source_row_sha256": "a" * 64,
        "normalisation_version": "1.0.0",
    }
    row.update(overrides)
    return row


def scenario(**responses: Scripted) -> ScriptedReader:
    """A fully accepted suburb with empty layers unless a test overrides a statement."""
    scripted: dict[str, Scripted] = {
        "releases": all_releases(),
        "suburb": suburb_row(),
        "projection-present": {"present": True},
        "source": None,
        "amenity-stats": [],
        "amenity-features": [],
        "school-features": [{"matched_total": 0, "non_operational": 0, "eligible_total": 0}],
    }
    scripted.update({key.replace("_", "-"): value for key, value in responses.items()})
    return ScriptedReader(scripted)


def context_request(categories: str, **fields: str) -> MapContextRequest:
    return build_map_context_request(SUBURB_ID, {"categories": categories, **fields})


# Request parsing ---------------------------------------------------------------------------


def test_map_context_request_defaults() -> None:
    request = build_map_context_request(SUBURB_ID, {})

    assert request == MapContextRequest(
        suburb_id=SUBURB_ID,
        categories=DEFAULT_CATEGORIES,
        detail="medium",
        limit=DEFAULT_LAYER_LIMIT,
        operational="current",
    )


@pytest.mark.parametrize(
    ("zoom", "detail"),
    [
        ("0", "low"),
        ("11", "low"),
        ("12", "medium"),
        ("14", "medium"),
        ("15", "high"),
        ("22", "high"),
    ],
)
def test_zoom_maps_to_precomputed_detail(zoom: str, detail: str) -> None:
    assert build_map_context_request(SUBURB_ID, {"zoom": zoom}).detail == detail


@pytest.mark.parametrize(
    ("raw", "detail"), [("low", "low"), (" HIGH ", "high"), ("Medium", "medium")]
)
def test_explicit_detail_is_case_insensitive(raw: str, detail: str) -> None:
    assert build_map_context_request(SUBURB_ID, {"detail": raw}).detail == detail


def test_detail_and_zoom_together_are_rejected() -> None:
    with pytest.raises(ValidationError, match="either detail or zoom"):
        build_map_context_request(SUBURB_ID, {"detail": "low", "zoom": "10"})


@pytest.mark.parametrize(
    "fields",
    [
        {"zoom": "23"},
        {"zoom": "-1"},
        {"zoom": "1.5"},
        {"zoom": "abc"},
        {"zoom": "100"},
        {"detail": "ultra"},
        {"limit": "0"},
        {"limit": str(MAX_LAYER_LIMIT + 1)},
        {"limit": "-5"},
        {"limit": "1e3"},
        {"limit": "ten"},
        {"operational": "closed"},
        {"bbox": "151,-34,152,-33"},
    ],
    ids=[
        "zoom-23",
        "zoom-negative",
        "zoom-fraction",
        "zoom-text",
        "zoom-100",
        "detail-unknown",
        "limit-zero",
        "limit-over-max",
        "limit-negative",
        "limit-exponent",
        "limit-text",
        "operational-unknown",
        "unknown-field",
    ],
)
def test_invalid_map_context_fields_are_rejected_not_clamped(fields: dict[str, str]) -> None:
    with pytest.raises(ValidationError):
        build_map_context_request(SUBURB_ID, fields)


def test_unknown_query_field_is_named() -> None:
    with pytest.raises(ValidationError, match="unsupported map-context query field: bbox"):
        build_map_context_request(SUBURB_ID, {"bbox": "1", "limit": "5"})


@pytest.mark.parametrize(
    ("raw", "limit"), [("1", 1), (str(MAX_LAYER_LIMIT), MAX_LAYER_LIMIT), (" 25 ", 25)]
)
def test_limit_bounds_are_inclusive(raw: str, limit: int) -> None:
    assert build_map_context_request(SUBURB_ID, {"limit": raw}).limit == limit


@pytest.mark.parametrize(
    ("raw", "operational"), [("", "current"), ("ALL", "all"), (" current ", "current")]
)
def test_operational_filter_is_normalised(raw: str, operational: str) -> None:
    assert build_map_context_request(SUBURB_ID, {"operational": raw}).operational == operational


def test_categories_are_deduplicated_in_first_seen_order_ignoring_case_and_empty_tokens() -> None:
    parsed = parse_categories("Library, schools,,library , TRAIN-STATION,")

    assert parsed == ("library", "schools", "train-station")


@pytest.mark.parametrize("raw", [None, "", "   ", ",, ,"])
def test_absent_or_empty_categories_use_the_defaults(raw: str | None) -> None:
    assert parse_categories(raw) == DEFAULT_CATEGORIES


@pytest.mark.parametrize("raw", ["parks", "Parks", "library,park"])
def test_parks_are_declined_with_a_pointer_to_protected_reserve(raw: str) -> None:
    with pytest.raises(UnsupportedCategoryError, match="protected-reserve"):
        parse_categories(raw)


def test_unknown_category_lists_every_supported_category() -> None:
    with pytest.raises(UnsupportedCategoryError) as raised:
        parse_categories("library,cafes")

    message = str(raised.value)
    assert "'cafes'" in message
    supported = message.split("supported categories: ", 1)[1]
    assert supported.split(", ") == [category.key for category in MAP_CATEGORIES]


def test_unknown_category_echo_is_bounded() -> None:
    with pytest.raises(UnsupportedCategoryError) as raised:
        parse_categories("x" * 500)

    assert "x" * 61 not in str(raised.value)


def test_more_than_max_categories_is_rejected() -> None:
    keys = [category.key for category in MAP_CATEGORIES]
    assert parse_categories(",".join(keys[:MAX_CATEGORIES])) == tuple(keys[:MAX_CATEGORIES])

    with pytest.raises(ValidationError, match=f"at most {MAX_CATEGORIES}") as raised:
        parse_categories(",".join(keys[: MAX_CATEGORIES + 1]))
    assert not isinstance(raised.value, UnsupportedCategoryError)


def test_duplicates_do_not_count_towards_the_category_ceiling() -> None:
    keys = [category.key for category in MAP_CATEGORIES][:MAX_CATEGORIES]

    assert len(parse_categories(",".join(keys + keys))) == MAX_CATEGORIES


@pytest.mark.parametrize("suburb_id", ["1", "108502", "123456789012"])
def test_valid_suburb_ids(suburb_id: str) -> None:
    assert validate_suburb_id(suburb_id) == suburb_id


@pytest.mark.parametrize(
    "suburb_id",
    ["", "0", "0123", "1234567890123", "12a", " 1", "1 ", "1\n", "-1", "1.0", "..", chr(0xFF11)],
    ids=[
        "empty",
        "zero",
        "leading-zero",
        "thirteen-digits",
        "letter",
        "leading-space",
        "trailing-space",
        "trailing-newline",
        "negative",
        "decimal",
        "dot-dot",
        "fullwidth-digit",
    ],
)
def test_invalid_suburb_ids_are_rejected(suburb_id: str) -> None:
    with pytest.raises(ValidationError, match="cadid"):
        validate_suburb_id(suburb_id)


def test_map_context_request_validates_the_suburb_id() -> None:
    with pytest.raises(ValidationError, match="cadid"):
        build_map_context_request("abc", {})


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        ("St. Ives", "ST IVES"),
        ("O'Connor", "O CONNOR"),
        (f"O{chr(0x2019)}Connor", "O CONNOR"),
        ("  surry   hills ", "SURRY HILLS"),
        ("Bangor-Menai", "BANGOR MENAI"),
        ("Mount Druitt (NSW)", "MOUNT DRUITT NSW"),
        ("ashfield", "ASHFIELD"),
        ("2000", "2000"),
        ("...", ""),
    ],
)
def test_normalise_suburb_name(raw: str, normalised: str) -> None:
    assert normalise_suburb_name(raw) == normalised


# ETag and coverage -------------------------------------------------------------------------

_POINTERS: dict[str, str | None] = {
    BOUNDARY_DATASET: BOUNDARY_RELEASE,
    AMENITY_DATASET: AMENITY_RELEASE,
    SCHOOL_DATASET: SCHOOL_RELEASE,
}


def test_map_context_etag_is_stable_quoted_and_order_independent() -> None:
    request = context_request("library,schools")
    reordered = dict(reversed(list(_POINTERS.items())))

    first = map_context_etag(request, _POINTERS)

    assert first == map_context_etag(context_request("library,schools"), dict(_POINTERS))
    assert first == map_context_etag(request, reordered)
    assert re.fullmatch(r'"smc1-[0-9a-f]{40}"', first)


@pytest.mark.parametrize("dataset", [BOUNDARY_DATASET, AMENITY_DATASET, SCHOOL_DATASET])
def test_map_context_etag_changes_with_any_release(dataset: str) -> None:
    request = context_request("library,schools")
    changed = {**_POINTERS, dataset: "40000000-0000-4000-8000-000000000004"}

    assert map_context_etag(request, changed) != map_context_etag(request, _POINTERS)


def test_map_context_etag_changes_when_a_dataset_becomes_available() -> None:
    request = context_request("library")
    unavailable = {**_POINTERS, AMENITY_DATASET: None}

    assert map_context_etag(request, unavailable) != map_context_etag(request, _POINTERS)


@pytest.mark.parametrize(
    "fields",
    [
        {"categories": "schools,library"},
        {"categories": "library"},
        {"categories": "library,schools", "detail": "high"},
        {"categories": "library,schools", "limit": "10"},
        {"categories": "library,schools", "operational": "all"},
    ],
    ids=["category-order", "categories", "detail", "limit", "operational"],
)
def test_map_context_etag_changes_with_the_request(fields: dict[str, str]) -> None:
    base = context_request("library,schools")
    other = build_map_context_request(SUBURB_ID, fields)

    assert map_context_etag(other, _POINTERS) != map_context_etag(base, _POINTERS)


def test_map_context_etag_changes_with_the_suburb() -> None:
    other = build_map_context_request("108503", {"categories": "library"})

    assert map_context_etag(other, _POINTERS) != map_context_etag(
        context_request("library"), _POINTERS
    )


def test_suburb_detail_etag_is_quoted_and_tracks_suburb_and_release() -> None:
    etag = suburb_detail_etag(SUBURB_ID, BOUNDARY_RELEASE)

    assert re.fullmatch(r'"sd1-[0-9a-f]{40}"', etag)
    assert etag == suburb_detail_etag(SUBURB_ID, BOUNDARY_RELEASE)
    assert etag != suburb_detail_etag("108503", BOUNDARY_RELEASE)
    assert etag != suburb_detail_etag(SUBURB_ID, AMENITY_RELEASE)
    assert etag != suburb_detail_etag(SUBURB_ID, None)


@pytest.mark.parametrize(
    ("available", "partial", "stale", "expected"),
    [
        (False, False, False, "unavailable"),
        (False, True, False, "unavailable"),
        (False, False, True, "unavailable"),
        (False, True, True, "unavailable"),
        (True, True, True, "partial"),
        (True, True, False, "partial"),
        (True, False, True, "stale"),
        (True, False, False, "accepted"),
    ],
)
def test_coverage_state_precedence(
    available: bool, partial: bool, stale: bool, expected: str
) -> None:
    assert coverage_state(available=available, partial=partial, stale=stale) == expected


def test_relevant_datasets_always_include_the_boundary() -> None:
    assert relevant_datasets(["schools"]) == (SCHOOL_DATASET, BOUNDARY_DATASET)
    assert relevant_datasets(["library", "protected-reserve"]) == (
        AMENITY_DATASET,
        BOUNDARY_DATASET,
    )
    assert relevant_datasets([]) == (BOUNDARY_DATASET,)


# Search ------------------------------------------------------------------------------------


def _search_row(suburb_id: str, postcode: str | None) -> JsonObject:
    row = suburb_row(suburb_id=suburb_id, postcode=postcode)
    return {
        key: row[key]
        for key in (
            "suburb_id",
            "name",
            "postcode",
            "geometry_status",
            "centroid_longitude",
            "centroid_latitude",
            "label_longitude",
            "label_latitude",
            "min_longitude",
            "min_latitude",
            "max_longitude",
            "max_latitude",
        )
    }


@pytest.mark.parametrize(
    "releases",
    [
        [],
        all_releases(boundary=None),
        all_releases(
            boundary=release_row(
                BOUNDARY_DATASET, BOUNDARY_RELEASE, schema_version="propertyscope.other.v9"
            )
        ),
    ],
    ids=["no-releases", "no-boundary-release", "incompatible-schema"],
)
def test_search_without_a_compatible_boundary_release_is_dataset_unavailable(
    releases: list[JsonObject],
) -> None:
    reader = scenario(releases=releases)

    result = SuburbMapReads(reader).search("Ashfield", postcode=None, limit=20)

    assert result["availability"]["status"] == "dataset_unavailable"
    assert result["match"] == "none"
    assert result["items"] == []
    assert result["count"] == 0
    assert result["has_more"] is False
    assert result["release"] is None
    assert reader.tags() == ["releases"]


def test_search_with_no_match() -> None:
    reader = scenario(search=[])

    result = SuburbMapReads(reader).search("Nowhere", postcode=None, limit=20)

    assert result["availability"]["status"] == "available"
    assert result["match"] == "none"
    assert result["count"] == 0
    assert result["release"]["dataset_release_id"] == BOUNDARY_RELEASE


def test_search_with_a_unique_match_projects_the_summary() -> None:
    reader = scenario(search=[_search_row(SUBURB_ID, "2131")])

    result = SuburbMapReads(reader).search("  ashfield ", postcode="2131", limit=20)

    assert result["schema_version"] == "propertyscope.suburb-search.v1"
    assert result["geography"] == BOUNDARY_LAYER
    assert result["query"] == {"q": "  ashfield ", "normalised": "ASHFIELD", "postcode": "2131"}
    assert result["match"] == "unique"
    assert result["items"] == [
        {
            "suburb_id": SUBURB_ID,
            "name": "Ashfield",
            "postcode": "2131",
            "state": "NSW",
            "geometry_status": "valid",
            "centroid": [151.123457, -33.887654],
            "label_point": [151.124, -33.888],
            "bbox": [151.11, -33.9, 151.14, -33.87],
        }
    ]
    assert result["release"]["source_updated_at"] is None
    assert reader.params("search") == (BOUNDARY_RELEASE, "ASHFIELD", "2131", "2131", 21)


def test_search_with_an_ambiguous_match() -> None:
    reader = scenario(search=[_search_row("1", "2000"), _search_row("2", None)])

    result = SuburbMapReads(reader).search("Ashfield", postcode=None, limit=20)

    assert result["match"] == "ambiguous"
    assert [item["suburb_id"] for item in result["items"]] == ["1", "2"]
    assert result["has_more"] is False


def test_search_reports_has_more_from_the_extra_row() -> None:
    reader = scenario(search=[_search_row(str(n), "2000") for n in (1, 2, 3)])

    result = SuburbMapReads(reader).search("Ashfield", postcode=None, limit=2)

    assert result["count"] == 2
    assert result["has_more"] is True
    assert reader.params("search")[-1] == 3


@pytest.mark.parametrize(
    ("query", "postcode", "limit"),
    [
        ("Ashfield", "213", 20),
        ("Ashfield", "21311", 20),
        ("Ashfield", "abcd", 20),
        ("1234", None, 20),
        ("!!!", None, 20),
        ("   ", None, 20),
        ("A" * 101, None, 20),
        ("Ashfield", None, 0),
        ("Ashfield", None, 51),
    ],
    ids=[
        "postcode-short",
        "postcode-long",
        "postcode-letters",
        "q-digits-only",
        "q-punctuation-only",
        "q-blank",
        "q-too-long",
        "limit-zero",
        "limit-over-max",
    ],
)
def test_search_rejects_invalid_input_before_reading(
    query: str, postcode: str | None, limit: int
) -> None:
    reader = scenario()

    with pytest.raises(ValidationError):
        SuburbMapReads(reader).search(query, postcode=postcode, limit=limit)
    assert reader.calls == []


# Detail ------------------------------------------------------------------------------------


def test_detail_projects_source_display_and_release() -> None:
    reader = scenario(
        source={
            "urbanity": "U",
            "publisher_edition": "2026-08",
            "start_date": "2001-01-01T00:00:00+00:00",
            "last_update": "2026-07-30T00:00:00+00:00",
        }
    )

    detail = SuburbMapReads(reader).detail(SUBURB_ID)

    assert detail["schema_version"] == "propertyscope.suburb-detail.v1"
    assert detail["suburb_id"] == SUBURB_ID
    assert detail["coverage"] == "accepted"
    assert detail["source"] == {
        "record_id": SUBURB_RECORD,
        "source_updated_at": "2026-08-01T00:00:00+00:00",
        "valid_from": "2026-08-01",
        "start_date": "2001-01-01T00:00:00+00:00",
        "last_update": "2026-07-30T00:00:00+00:00",
        "urbanity": "U",
        "publisher_edition": "2026-08",
    }
    assert detail["display"] == {
        "source_vertex_count": 1200,
        "levels": {
            "low": {"tolerance_degrees": DETAIL_TOLERANCES["low"], "vertex_count": 80},
            "medium": {"tolerance_degrees": DETAIL_TOLERANCES["medium"], "vertex_count": 300},
            "high": {"tolerance_degrees": DETAIL_TOLERANCES["high"], "vertex_count": 900},
        },
    }
    assert detail["release"]["dataset_release_id"] == BOUNDARY_RELEASE
    assert detail["release"]["source_updated_at"] == "2026-08-01T00:00:00+00:00"
    assert detail["release"]["freshness_days"] == 400
    assert reader.params("source") == (BOUNDARY_RELEASE, BOUNDARY_LAYER, SUBURB_RECORD)


def test_detail_without_a_source_row_keeps_null_source_fields() -> None:
    detail = SuburbMapReads(scenario(source=None)).detail(SUBURB_ID)

    assert detail["source"]["urbanity"] is None
    assert detail["source"]["last_update"] is None


@pytest.mark.parametrize(
    "releases",
    [
        [],
        all_releases(
            boundary=release_row(BOUNDARY_DATASET, BOUNDARY_RELEASE, schema_version="x.v0")
        ),
    ],
    ids=["no-release", "incompatible-schema"],
)
def test_detail_without_a_boundary_release_is_unavailable(releases: list[JsonObject]) -> None:
    with pytest.raises(SuburbBoundariesUnavailableError):
        SuburbMapReads(scenario(releases=releases)).detail(SUBURB_ID)


def test_detail_for_a_missing_suburb_in_a_projected_release_is_not_found() -> None:
    reader = scenario(suburb=None, projection_present={"present": True})

    with pytest.raises(SuburbNotFoundError):
        SuburbMapReads(reader).detail(SUBURB_ID)
    assert reader.params("projection-present") == (BOUNDARY_RELEASE,)


@pytest.mark.parametrize("present", [{"present": False}, None], ids=["projection-empty", "no-row"])
def test_detail_without_a_projection_is_boundaries_unavailable(present: JsonObject | None) -> None:
    reader = scenario(suburb=None, projection_present=present)

    with pytest.raises(SuburbBoundariesUnavailableError, match="projection"):
        SuburbMapReads(reader).detail(SUBURB_ID)


@pytest.mark.parametrize(
    ("acquired_at", "coverage"),
    [(FRESH, "accepted"), (EXACTLY_400_DAYS, "accepted"), (STALE_401_DAYS, "stale")],
    ids=["fresh", "exactly-400-days", "401-days"],
)
def test_detail_staleness_uses_the_freshness_window(acquired_at: str, coverage: str) -> None:
    releases = all_releases(
        boundary=release_row(BOUNDARY_DATASET, BOUNDARY_RELEASE, acquired_at=acquired_at)
    )

    assert SuburbMapReads(scenario(releases=releases)).detail(SUBURB_ID)["coverage"] == coverage


def test_detail_with_invalid_geometry_is_coverage_unavailable() -> None:
    reader = scenario(suburb=suburb_row(valid=False))

    detail = SuburbMapReads(reader).detail(SUBURB_ID)

    assert detail["coverage"] == "unavailable"
    assert detail["centroid"] is None
    assert detail["geometry_status"] == "invalid"


def test_detail_rejects_an_invalid_suburb_id_before_reading() -> None:
    reader = scenario()

    with pytest.raises(ValidationError):
        SuburbMapReads(reader).detail("0123")
    assert reader.calls == []


# Map context -------------------------------------------------------------------------------


def test_map_context_accepted_layer_with_features() -> None:
    reader = scenario(
        amenity_stats=[stats_row("library")],
        amenity_features=[
            amenity_row("library", 1, matched_total=2, eligible_total=2),
            amenity_row("library", 2, matched_total=2, eligible_total=2),
        ],
    )

    context = SuburbMapReads(reader).map_context(context_request("library"))

    assert context["schema_version"] == "propertyscope.suburb-map-context.v1"
    assert [feature["id"] for feature in context["layers"]["library"]["features"]] == [
        "library:1",
        "library:2",
    ]
    assert context["coverage"] == {"boundary": "accepted", "library": "accepted"}
    detail = context["layer_details"]["library"]
    assert detail["feature_count"] == 2
    assert detail["matched_count"] == 2
    assert detail["eligible_count"] == 2
    assert detail["truncated"] is False
    assert detail["reason"] is None
    assert detail["predicate"] == "ST_Covers"
    assert context["truncated"] is False
    assert context["releases"]["library"]["dataset_release_id"] == AMENITY_RELEASE
    assert context["releases"]["library"]["source_updated_at"] == "2026-07-01T00:00:00+00:00"
    assert context["suburb"]["boundary"]["geometry"]["type"] == "Polygon"
    assert context["response_vertices"] == 302
    features_params = reader.params("amenity-features")
    assert features_params["layers"] == ["library"]
    assert features_params["polygon_layers"] == []
    assert features_params["include_all"] is False


def test_map_context_amenity_clip_box_is_the_expanded_suburb_bbox() -> None:
    reader = scenario(amenity_stats=[stats_row("protected-reserve")])

    SuburbMapReads(reader).map_context(context_request("protected-reserve", detail="low"))

    params = reader.params("amenity-features")
    assert params["polygon_layers"] == ["protected-reserve"]
    assert params["tolerance"] == DETAIL_TOLERANCES["low"]
    assert params["xmin"] == pytest.approx(151.107)
    assert params["ymin"] == pytest.approx(-33.903)
    assert params["xmax"] == pytest.approx(151.143)
    assert params["ymax"] == pytest.approx(-33.867)


def test_map_context_empty_accepted_layer_is_distinct_from_unavailable_reasons() -> None:
    accepted = SuburbMapReads(scenario(amenity_stats=[stats_row("library")])).map_context(
        context_request("library")
    )
    no_pointer = SuburbMapReads(scenario(releases=all_releases(amenity=None))).map_context(
        context_request("library")
    )
    not_in_release = SuburbMapReads(scenario(amenity_stats=[])).map_context(
        context_request("library")
    )
    unsupported = SuburbMapReads(
        scenario(
            releases=all_releases(
                amenity=release_row(AMENITY_DATASET, AMENITY_RELEASE, schema_version="x.v0")
            )
        )
    ).map_context(context_request("library"))

    assert accepted["coverage"]["library"] == "accepted"
    assert accepted["layers"]["library"]["features"] == []
    assert accepted["layer_details"]["library"]["feature_count"] == 0
    assert accepted["layer_details"]["library"]["reason"] is None
    assert accepted["releases"]["library"] is not None

    for context, reason in (
        (no_pointer, "dataset_unavailable"),
        (not_in_release, "layer_not_in_release"),
        (unsupported, "unsupported_schema"),
    ):
        assert context["coverage"]["library"] == "unavailable"
        assert context["layer_details"]["library"]["reason"] == reason
        assert context["layers"]["library"]["features"] == []

    assert no_pointer["releases"]["library"] is None
    assert unsupported["releases"]["library"] is None
    assert not_in_release["releases"]["library"]["dataset_release_id"] == AMENITY_RELEASE


def test_map_context_unavailable_amenity_dataset_skips_spatial_reads() -> None:
    reader = scenario(releases=all_releases(amenity=None))

    SuburbMapReads(reader).map_context(context_request("library,train-station"))

    assert "amenity-stats" not in reader.tags()
    assert "amenity-features" not in reader.tags()


def test_map_context_layer_missing_from_stats_is_not_queried_for_features() -> None:
    reader = scenario(
        amenity_stats=[stats_row("library")],
        amenity_features=[amenity_row("library", 1)],
    )

    context = SuburbMapReads(reader).map_context(context_request("library,airport"))

    assert reader.params("amenity-features")["layers"] == ["library"]
    assert context["layer_details"]["airport"]["reason"] == "layer_not_in_release"


def test_map_context_invalid_boundary_makes_every_layer_unavailable() -> None:
    reader = scenario(suburb=suburb_row(valid=False))

    context = SuburbMapReads(reader).map_context(context_request("schools,library"))

    assert context["suburb"]["boundary"]["geometry"] is None
    assert context["coverage"] == {
        "boundary": "unavailable",
        "schools": "unavailable",
        "library": "unavailable",
    }
    for key in ("schools", "library"):
        assert context["layer_details"][key]["reason"] == "boundary_geometry_unavailable"
        assert context["layers"][key]["features"] == []
    assert reader.tags() == ["releases", "suburb"]


def test_map_context_truncated_layer_is_partial() -> None:
    reader = scenario(
        amenity_stats=[stats_row("library")],
        amenity_features=[
            amenity_row("library", 1, matched_total=5, eligible_total=5),
            amenity_row("library", 2, matched_total=5, eligible_total=5),
        ],
    )

    context = SuburbMapReads(reader).map_context(context_request("library", limit="2"))

    detail = context["layer_details"]["library"]
    assert detail["truncated"] is True
    assert detail["eligible_count"] == 5
    assert detail["feature_count"] == 2
    assert detail["limit"] == 2
    assert context["coverage"]["library"] == "partial"
    assert context["truncated"] is True
    assert reader.params("amenity-features")["limit"] == 2


@pytest.mark.parametrize(
    "stats",
    [{"invalid_near": 1}, {"missing_geometry": 2}],
    ids=["invalid-near", "missing-geometry"],
)
def test_map_context_excluded_geometry_is_partial(stats: JsonObject) -> None:
    reader = scenario(
        amenity_stats=[stats_row("library", **stats)],
        amenity_features=[amenity_row("library", 1)],
    )

    context = SuburbMapReads(reader).map_context(context_request("library"))

    detail = context["layer_details"]["library"]
    assert detail["excluded_invalid_geometry"] == stats.get("invalid_near", 0)
    assert detail["excluded_missing_geometry"] == stats.get("missing_geometry", 0)
    assert detail["truncated"] is False
    assert context["coverage"]["library"] == "partial"
    assert context["truncated"] is False


def test_partial_takes_precedence_over_stale_in_a_layer() -> None:
    releases = all_releases(
        amenity=release_row(AMENITY_DATASET, AMENITY_RELEASE, acquired_at=STALE_401_DAYS)
    )
    reader = scenario(
        releases=releases,
        amenity_stats=[stats_row("library", invalid_near=1)],
    )

    context = SuburbMapReads(reader).map_context(context_request("library"))

    assert context["layer_details"]["library"]["stale"] is True
    assert context["coverage"]["library"] == "partial"


def test_stale_amenity_release_marks_the_layer_stale() -> None:
    releases = all_releases(
        amenity=release_row(AMENITY_DATASET, AMENITY_RELEASE, acquired_at=STALE_401_DAYS)
    )
    reader = scenario(releases=releases, amenity_stats=[stats_row("library")])

    context = SuburbMapReads(reader).map_context(context_request("library"))

    assert context["coverage"] == {"boundary": "accepted", "library": "stale"}


@pytest.mark.parametrize(
    ("operational", "excluded"), [("current", 3), ("all", 0)], ids=["current", "all"]
)
def test_excluded_non_operational_is_reported_only_for_current(
    operational: str, excluded: int
) -> None:
    reader = scenario(
        amenity_stats=[stats_row("train-station")],
        amenity_features=[
            amenity_row("train-station", 1, matched_total=4, non_operational=3, eligible_total=1)
        ],
        school_features=[
            school_row("1001", matched_total=5, non_operational=3, eligible_total=2),
            school_row("1002", matched_total=5, non_operational=3, eligible_total=2),
        ],
    )

    context = SuburbMapReads(reader).map_context(
        context_request("train-station,schools", operational=operational)
    )

    assert context["layer_details"]["train-station"]["excluded_non_operational"] == excluded
    assert context["layer_details"]["schools"]["excluded_non_operational"] == excluded
    assert context["layer_details"]["train-station"]["operational_filter"] == operational
    assert reader.params("amenity-features")["include_all"] is (operational == "all")
    assert reader.params("school-features")["include_all"] is (operational == "all")


def test_amenity_layer_whose_matches_were_all_filtered_reports_totals_only() -> None:
    reader = scenario(
        amenity_stats=[stats_row("train-station")],
        amenity_features=[
            amenity_row(
                "train-station",
                0,
                matched_total=2,
                non_operational=2,
                eligible_total=0,
                record_id=None,
                name=None,
                status_code=None,
                geometry=None,
                vertices=None,
            )
        ],
    )

    context = SuburbMapReads(reader).map_context(context_request("train-station"))

    assert context["layers"]["train-station"]["features"] == []
    detail = context["layer_details"]["train-station"]
    assert detail["feature_count"] == 0
    assert detail["matched_count"] == 2
    assert detail["eligible_count"] == 0
    assert detail["excluded_non_operational"] == 2
    assert detail["truncated"] is False
    assert context["coverage"]["train-station"] == "accepted"
    assert context["response_vertices"] == 300


def test_school_features_keep_the_school_points_v2_shape() -> None:
    reader = scenario(
        school_features=[
            school_row("1001", matched_total=2, eligible_total=2),
            school_row("1002", matched_total=2, eligible_total=2, lga_name=None),
        ]
    )
    validator = Draft202012Validator(json.loads(SCHOOL_POINTS_SCHEMA.read_text(encoding="utf-8")))

    context = SuburbMapReads(reader).map_context(context_request("schools"))

    features = context["layers"]["schools"]["features"]
    assert [feature["id"] for feature in features] == ["school:1001", "school:1002"]
    for feature in features:
        errors = sorted(validator.iter_errors(feature["properties"]), key=str)
        assert errors == []
        assert feature["geometry"] == {"type": "Point", "coordinates": [151.125, -33.889]}
        provenance = feature["properties"]["provenance"]
        assert provenance["release_id"] == SCHOOL_RELEASE
        assert provenance["candidate_generation_id"] == SCHOOL_RELEASE
    assert context["coverage"]["schools"] == "accepted"
    assert context["layer_details"]["schools"]["predicate"] == "ST_Covers"
    assert context["releases"]["schools"]["target_feature"] == "feature-3"
    assert context["response_vertices"] == 302


def test_empty_school_layer_is_accepted_with_zero_features() -> None:
    context = SuburbMapReads(scenario()).map_context(context_request("schools"))

    assert context["layers"]["schools"]["features"] == []
    assert context["coverage"]["schools"] == "accepted"
    assert context["layer_details"]["schools"]["matched_count"] == 0


def test_school_release_with_another_schema_is_unsupported() -> None:
    releases = all_releases(
        school=release_row(
            SCHOOL_DATASET, SCHOOL_RELEASE, schema_version="propertyscope.school-points.v1"
        )
    )
    reader = scenario(releases=releases)

    context = SuburbMapReads(reader).map_context(context_request("schools"))

    assert context["layer_details"]["schools"]["reason"] == "unsupported_schema"
    assert context["releases"]["schools"] is None
    assert "school-features" not in reader.tags()


def test_protected_reserve_features_carry_clipping_and_reserve_type() -> None:
    polygon = {
        "type": "Polygon",
        "coordinates": [[[151.1, -33.9], [151.2, -33.9], [151.2, -33.8], [151.1, -33.9]]],
    }
    reader = scenario(
        amenity_stats=[stats_row("protected-reserve")],
        amenity_features=[
            amenity_row(
                "protected-reserve",
                1,
                status_code=None,
                topoid=None,
                cadid="C77",
                reserve_type="National Park",
                coverage_note="NPWS estate only",
                display_clipped=True,
                geometry=polygon,
                vertices=4,
            )
        ],
    )

    context = SuburbMapReads(reader).map_context(context_request("protected-reserve"))

    feature = context["layers"]["protected-reserve"]["features"][0]
    assert feature["geometry"] == polygon
    assert feature["properties"] == {
        "amenity_id": "protected-reserve:1",
        "category": "protected-reserve",
        "name": "protected-reserve 1",
        "source_feature_id": "C77",
        "source_updated_at": "2026-07-01T00:00:00+00:00",
        "match": "intersects",
        "reserve_type": "National Park",
        "coverage_note": "NPWS estate only",
        "display_clipped": True,
    }
    assert context["layer_details"]["protected-reserve"]["predicate"] == "ST_Intersects"
    assert context["layer_details"]["protected-reserve"]["geometry"] == "polygon"
    assert context["response_vertices"] == 304


@pytest.mark.parametrize(
    ("code", "label"),
    [(1, "operational"), (6, "non-operational"), (None, None)],
    ids=["code-1", "code-6", "no-code"],
)
def test_point_amenities_carry_operational_status(code: int | None, label: str | None) -> None:
    reader = scenario(
        amenity_stats=[stats_row("train-station")],
        amenity_features=[amenity_row("train-station", 1, status_code=code)],
    )

    context = SuburbMapReads(reader).map_context(
        context_request("train-station", operational="all")
    )

    properties = context["layers"]["train-station"]["features"][0]["properties"]
    assert properties["operational_status"] == label
    assert properties["operational_status_code"] == code
    assert properties["match"] == "covers"
    assert properties["source_feature_id"] == "T1"
    assert "display_clipped" not in properties


def test_response_vertex_ceiling_raises() -> None:
    reader = scenario(
        amenity_stats=[stats_row("protected-reserve")],
        amenity_features=[
            amenity_row("protected-reserve", 1, vertices=MAX_RESPONSE_VERTICES - 300 + 1)
        ],
    )

    with pytest.raises(ResponseLimitExceededError, match=str(MAX_RESPONSE_VERTICES + 1)):
        SuburbMapReads(reader).map_context(context_request("protected-reserve"))


def test_response_at_the_vertex_ceiling_is_allowed() -> None:
    reader = scenario(
        amenity_stats=[stats_row("protected-reserve")],
        amenity_features=[
            amenity_row("protected-reserve", 1, vertices=MAX_RESPONSE_VERTICES - 300)
        ],
    )

    context = SuburbMapReads(reader).map_context(context_request("protected-reserve"))

    assert context["response_vertices"] == MAX_RESPONSE_VERTICES


def test_map_context_echoes_request_and_limits() -> None:
    context = SuburbMapReads(scenario()).map_context(context_request("schools", zoom="16"))

    assert context["request"] == {
        "categories": ["schools"],
        "detail": "high",
        "tolerance_degrees": DETAIL_TOLERANCES["high"],
        "limit": DEFAULT_LAYER_LIMIT,
        "operational": "current",
    }
    assert context["limits"]["max_response_vertices"] == MAX_RESPONSE_VERTICES
    assert context["suburb"]["boundary"]["properties"]["detail"] == "high"


def test_map_context_for_a_missing_suburb_is_not_found() -> None:
    with pytest.raises(SuburbNotFoundError):
        SuburbMapReads(scenario(suburb=None)).map_context(context_request("library"))


def test_map_context_without_boundary_release_is_unavailable() -> None:
    reader = scenario(releases=all_releases(boundary=None))

    with pytest.raises(SuburbBoundariesUnavailableError):
        SuburbMapReads(reader).map_context(context_request("library"))


def test_release_pointers_report_none_for_missing_datasets() -> None:
    reader = scenario(releases=all_releases(school=None))

    pointers = SuburbMapReads(reader).release_pointers(
        (BOUNDARY_DATASET, SCHOOL_DATASET, AMENITY_DATASET)
    )

    assert pointers == {
        BOUNDARY_DATASET: BOUNDARY_RELEASE,
        SCHOOL_DATASET: None,
        AMENITY_DATASET: AMENITY_RELEASE,
    }


# Repository facade: the cheap revalidation ETag must equal the ETag sent with the body -------


def _store_over(reader: ScriptedReader, monkeypatch: pytest.MonkeyPatch) -> PropertyScopeStore:
    store = object.__new__(PropertyScopeStore)

    @contextmanager
    def snapshot() -> Iterator[SuburbMapReads]:
        yield SuburbMapReads(reader)

    monkeypatch.setattr(store, "_suburb_map", snapshot)
    return store


def test_detail_revalidation_etag_matches_the_full_read(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _store_over(scenario(), monkeypatch)

    _, etag = store.suburb_detail(SUBURB_ID)

    assert store.suburb_detail_etag(SUBURB_ID) == etag


@pytest.mark.parametrize(
    "releases",
    [all_releases(), all_releases(amenity=None)],
    ids=["all-accepted", "amenity-missing"],
)
def test_map_context_revalidation_etag_matches_the_full_read(
    releases: list[JsonObject], monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = scenario(releases=releases, amenity_stats=[stats_row("library")])
    store = _store_over(reader, monkeypatch)
    request = context_request("library,schools")

    _, etag = store.suburb_map_context(request)

    assert store.suburb_map_context_etag(request) == etag


def test_map_context_revalidation_etag_matches_with_an_incompatible_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    releases = all_releases(
        amenity=release_row(AMENITY_DATASET, AMENITY_RELEASE, schema_version="x.v0")
    )
    store = _store_over(scenario(releases=releases), monkeypatch)
    request = context_request("library")

    _, etag = store.suburb_map_context(request)

    assert store.suburb_map_context_etag(request) == etag


# Catalogue and migration stay in step ------------------------------------------------------


def test_amenity_index_layers_match_the_catalogue() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    index = re.search(
        r"CREATE INDEX reference_feature_map_amenity_geom_idx.*?layer IN \((.*?)\)",
        sql,
        flags=re.DOTALL,
    )
    assert index is not None

    layers = re.findall(r"'([^']+)'", index.group(1))

    assert len(layers) == len(set(layers))
    assert sorted(layers) == sorted(AMENITY_SOURCE_LAYERS)


def test_projection_function_tolerances_match_the_catalogue() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    tolerances = {
        level: float(value)
        for value, level in re.findall(
            r"ST_SimplifyPreserveTopology\(feature\.geom,\s*([0-9.]+)\)\s+AS\s+(low|medium|high)",
            sql,
        )
    }

    assert tolerances == DETAIL_TOLERANCES


def test_projection_function_reads_the_catalogue_boundary_layer() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert f"feature.layer = '{BOUNDARY_LAYER}'" in sql
    assert f"release.dataset_id = '{BOUNDARY_DATASET}'" in sql
