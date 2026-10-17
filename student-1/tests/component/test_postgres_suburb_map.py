"""Suburb-map spatial projection against a disposable, fully migrated PostGIS database.

Requires PROPERTYSCOPE_TEST_POSTGRES_URL for a disposable administrator server.
Never point it at the retained application database.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import jsonschema
import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from propertyscope_data_store._suburb_map_reads import (
    SuburbMapReads,
    build_map_context_request,
    map_context_etag,
    relevant_datasets,
)
from propertyscope_data_store.errors import SuburbNotFoundError
from propertyscope_data_store.migrations import migrate
from propertyscope_data_store.repository import _SnapshotRows

ADMIN_URL = os.getenv("PROPERTYSCOPE_TEST_POSTGRES_URL", "").strip()
pytestmark = pytest.mark.skipif(not ADMIN_URL, reason="requires disposable PostgreSQL test URL")

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
SEED_RELEASE = "60000000-0000-0000-0000-000000000004"
SOURCES = {
    "nsw-suburb-boundaries": "81d57c83-5fc0-5e7e-82c5-213e5a54036b",
    "nsw-amenities": "e4eb6cc6-62a4-5a0f-827a-770da28ede2d",
}
SCHEMAS = {
    "nsw-suburb-boundaries": "propertyscope.reference-feature.v1",
    "nsw-amenities": "propertyscope.reference-feature.v1",
    "nsw-government-schools": "propertyscope.school-points.v2",
}
TARGETS = {
    "nsw-suburb-boundaries": "feature-1",
    "nsw-amenities": "feature-1",
    "nsw-government-schools": "feature-3",
}
# ALPHA is the unit square [151.00,151.01] x [-33.80,-33.79].
ALPHA = "POLYGON((151 -33.8,151.01 -33.8,151.01 -33.79,151 -33.79,151 -33.8))"
BOWTIE = "POLYGON((151.1 -33.8,151.11 -33.79,151.11 -33.8,151.1 -33.79,151.1 -33.8))"
# A self-intersecting reserve inside ALPHA: excluded from matches but reported.
INVALID_RESERVE = (
    "POLYGON((151.001 -33.799,151.009 -33.791,151.009 -33.799,151.001 -33.791,151.001 -33.799))"
)

Connection = psycopg.Connection[dict[str, Any]]


@pytest.fixture
def database() -> Iterator[Connection]:
    name = f"propertyscope_suburb_map_{uuid.uuid4().hex}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        with psycopg.connect(make_conninfo(ADMIN_URL, dbname=name), row_factory=dict_row) as conn:
            migrate(conn)
            yield conn
    finally:
        with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def _release(
    conn: Connection,
    dataset_id: str,
    *,
    status: str = "candidate",
    created_at: str = "2026-10-01T00:00:00+00:00",
    schema_version: str | None = None,
) -> str:
    seed = conn.execute(
        "SELECT source_definition_id,ingestion_run_id,artifact_record_id "
        "FROM ops.dataset_release WHERE id=%s",
        (SEED_RELEASE,),
    ).fetchone()
    assert seed is not None
    release_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO ops.dataset_release (
            id,dataset_id,source_definition_id,ingestion_run_id,target_feature,release_version,
            schema_version,coverage_json,record_count,content_sha256,artifact_record_id,
            manifest_json,status,created_at,updated_at
        ) VALUES (%s,%s,%s,%s,%s,%s,%s,'{}',0,%s,%s,'{}','candidate',%s,%s)""",
        (
            release_id,
            dataset_id,
            SOURCES.get(dataset_id, seed["source_definition_id"]),
            seed["ingestion_run_id"],
            TARGETS[dataset_id],
            f"test-{release_id}",
            schema_version or SCHEMAS[dataset_id],
            "a" * 64,
            seed["artifact_record_id"],
            created_at,
            created_at,
        ),
    )
    if status == "accepted":
        _accept(conn, release_id)
    elif status != "candidate":
        conn.execute("UPDATE ops.dataset_release SET status=%s WHERE id=%s", (status, release_id))
    return release_id


def _accept(conn: Connection, release_id: str) -> None:
    row = conn.execute(
        "SELECT dataset_id,target_feature FROM ops.dataset_release WHERE id=%s", (release_id,)
    ).fetchone()
    assert row is not None
    conn.execute(
        "UPDATE ops.dataset_release SET status='superseded' WHERE dataset_id=%s "
        "AND target_feature=%s AND status='accepted'",
        (row["dataset_id"], row["target_feature"]),
    )
    conn.execute(
        "UPDATE ops.dataset_release SET status='accepted',accepted_at=now() WHERE id=%s",
        (release_id,),
    )
    if row["dataset_id"] == "nsw-suburb-boundaries":
        conn.execute("SELECT serving.build_suburb_boundary_display(%s)", (release_id,))
    conn.execute(
        """INSERT INTO serving.accepted_generation
        (dataset_id,target_feature,dataset_release_id,activated_at,activated_by)
        VALUES (%s,%s,%s,now(),'test') ON CONFLICT (dataset_id,target_feature)
        DO UPDATE SET dataset_release_id=excluded.dataset_release_id""",
        (row["dataset_id"], row["target_feature"], release_id),
    )


def _feature(
    conn: Connection,
    release_id: str,
    layer: str,
    record_id: str,
    name: str,
    wkt: str,
    attributes: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """INSERT INTO warehouse.reference_feature (
            dataset_release_id,record_id,layer,name,geometry_json,geom,attributes,source_url,
            source_crs,source_updated_at,valid_from,source_row_sha256,normalisation_version,
            artifact_record_id,ingestion_run_id
        ) SELECT %s,%s,%s,%s,ST_AsGeoJSON(geom)::jsonb,geom,%s,
            'https://example.test/source','EPSG:7844','2026-09-01T00:00:00Z','2026-09-01',
            %s,'1.0.0',release.artifact_record_id,release.ingestion_run_id
        FROM ST_GeomFromText(%s,4326) geom, ops.dataset_release release WHERE release.id=%s""",
        (
            release_id,
            record_id,
            layer,
            name,
            json.dumps(attributes or {}),
            "b" * 64,
            wkt,
            release_id,
        ),
    )


def _suburb(
    conn: Connection, release_id: str, cadid: int, name: str, postcode: int, wkt: str
) -> None:
    _feature(
        conn,
        release_id,
        "nsw-gazetted-suburb",
        f"nsw-gazetted-suburb:{cadid}",
        name,
        wkt,
        {"cadid": cadid, "postcode": postcode, "lastupdate": 1723624626000},
    )


def _school(conn: Connection, release_id: str, code: str, name: str, wkt: str) -> None:
    conn.execute(
        """INSERT INTO warehouse.school (
            dataset_release_id,school_code,school_name,school_type,status,locality_original,
            locality_normalised,lga_name,geom,source_row_sha256,normalisation_version,
            artifact_record_id,ingestion_run_id,created_at
        ) SELECT %s,%s,%s,'Primary School','Open','Alpha','ALPHA','Example',
            ST_GeomFromText(%s,4326),%s,'1.0.0',release.artifact_record_id,
            release.ingestion_run_id,now()
        FROM ops.dataset_release release WHERE release.id=%s""",
        (release_id, code, name, wkt, "c" * 64, release_id),
    )


@pytest.fixture
def world(database: Connection) -> dict[str, str]:
    """Synthetic accepted generations around suburb ALPHA (cadid 1001)."""
    conn = database
    suburbs = _release(conn, "nsw-suburb-boundaries")
    _suburb(conn, suburbs, 1001, "ALPHA", 2000, ALPHA)
    _suburb(
        conn,
        suburbs,
        1002,
        "MAYFIELD",
        2304,
        "POLYGON((151.2 -33.8,151.21 -33.8,151.21 -33.79,151.2 -33.79,151.2 -33.8))",
    )
    _suburb(
        conn,
        suburbs,
        1003,
        "MAYFIELD",
        2540,
        "POLYGON((150.2 -34.8,150.21 -34.8,150.21 -34.79,150.2 -34.79,150.2 -34.8))",
    )
    _suburb(conn, suburbs, 1004, "BOW TIE", 2001, BOWTIE)
    _accept(conn, suburbs)

    amenities = _release(conn, "nsw-amenities")
    station = {"operationalstatus": 1, "topoid": 1}
    _feature(
        conn,
        amenities,
        "train-station",
        "train-station:1",
        "INSIDE STN",
        "POINT(151.005 -33.795)",
        station,
    )
    _feature(
        conn,
        amenities,
        "train-station",
        "train-station:2",
        "EDGE STN",
        "POINT(151.01 -33.795)",
        station,
    )
    _feature(
        conn,
        amenities,
        "train-station",
        "train-station:3",
        "VERTEX STN",
        "POINT(151 -33.8)",
        station,
    )
    _feature(
        conn,
        amenities,
        "train-station",
        "train-station:4",
        "OUTSIDE STN",
        "POINT(151.02 -33.795)",
        station,
    )
    _feature(
        conn,
        amenities,
        "train-station",
        "train-station:5",
        "CLOSED STN",
        "POINT(151.006 -33.796)",
        {"operationalstatus": 6, "topoid": 5},
    )
    _feature(conn, amenities, "library", "library:1", "FAR LIBRARY", "POINT(151.5 -33.5)", station)
    _feature(
        conn,
        amenities,
        "protected-reserve",
        "protected-reserve:1",
        "PARTLY INSIDE NP",
        "POLYGON((151.008 -33.81,151.05 -33.81,151.05 -33.78,151.008 -33.78,151.008 -33.81))",
        {"cadid": 1, "reservetype": "NP", "coverage_note": "NPWS reserves only"},
    )
    _feature(
        conn,
        amenities,
        "protected-reserve",
        "protected-reserve:2",
        "INVALID NP",
        INVALID_RESERVE,
        {"cadid": 2, "reservetype": "NP"},
    )
    _accept(conn, amenities)

    schools = _release(conn, "nsw-government-schools")
    _school(conn, schools, "S1", "Alpha Public School", "POINT(151.002 -33.798)")
    _school(conn, schools, "S2", "Edge Public School", "POINT(151.01 -33.79)")
    _school(conn, schools, "S3", "Beyond Public School", "POINT(151.03 -33.79)")
    _accept(conn, schools)
    return {"suburbs": suburbs, "amenities": amenities, "schools": schools}


def _reads(conn: Connection) -> SuburbMapReads:
    return SuburbMapReads(_SnapshotRows(conn))


def _validated(payload: dict[str, Any], schema_file: str) -> dict[str, Any]:
    """Every real PostGIS projection must satisfy its published, closed contract."""
    schema = json.loads((CONTRACTS / schema_file).read_text("utf-8"))
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER
    ).validate(json.loads(json.dumps(payload, default=str)))
    return payload


def _context(conn: Connection, suburb_id: str = "1001", **args: str) -> dict[str, Any]:
    context = _reads(conn).map_context(build_map_context_request(suburb_id, args))
    return _validated(context, "suburb-map-context.v1.schema.json")


def test_migration_registers_projection_function_and_generation_scoped_indexes(
    database: Connection,
) -> None:
    indexes = {
        row["indexname"]: row["indexdef"]
        for row in database.execute(
            "SELECT indexname,indexdef FROM pg_indexes WHERE indexname IN "
            "('reference_feature_map_amenity_geom_idx','school_release_geom_idx')"
        ).fetchall()
    }
    assert (
        "gist (dataset_release_id, layer, geom)"
        in indexes["reference_feature_map_amenity_geom_idx"]
    )
    assert "gist (dataset_release_id, geom)" in indexes["school_release_geom_idx"]


def test_projection_is_idempotent_and_keeps_invalid_geometry_out_of_display(
    database: Connection, world: dict[str, str]
) -> None:
    assert database.execute(
        "SELECT serving.build_suburb_boundary_display(%s) AS built", (world["suburbs"],)
    ).fetchone() == {"built": 4}
    rows = {
        row["suburb_id"]: row
        for row in database.execute(
            """SELECT suburb_id,name_normalised,postcode,geometry_status,
            display_medium IS NOT NULL AS has_display,
            ST_IsValid(display_low) AND ST_IsValid(display_high) AS display_valid,
            min_longitude FROM serving.suburb_boundary_display WHERE dataset_release_id=%s""",
            (world["suburbs"],),
        ).fetchall()
    }
    assert set(rows) == {"1001", "1002", "1003", "1004"}
    assert rows["1001"]["display_valid"] is True
    assert rows["1001"]["postcode"] == "2000"
    assert rows["1004"]["geometry_status"] == "invalid"
    assert rows["1004"]["has_display"] is False
    # The envelope still lets a consumer fit the camera to an invalid suburb.
    assert rows["1004"]["min_longitude"] == pytest.approx(151.1)


def test_search_reports_ambiguous_unique_and_empty_matches(
    database: Connection, world: dict[str, str]
) -> None:
    reads = _reads(database)
    ambiguous = _validated(
        reads.search("Mayfield", postcode=None, limit=20), "suburb-search.v1.schema.json"
    )
    assert ambiguous["match"] == "ambiguous"
    assert [item["postcode"] for item in ambiguous["items"]] == ["2304", "2540"]
    unique = reads.search("  mayfield ", postcode="2540", limit=20)
    assert unique["match"] == "unique"
    assert unique["items"][0]["suburb_id"] == "1003"
    assert reads.search("Bow-Tie", postcode=None, limit=20)["items"][0]["suburb_id"] == "1004"
    assert reads.search("Nowhere", postcode=None, limit=20)["match"] == "none"
    truncated = reads.search("Mayfield", postcode=None, limit=1)
    assert truncated["has_more"] is True
    assert truncated["release"]["dataset_release_id"] == world["suburbs"]


def test_search_without_accepted_boundaries_is_unavailable_not_empty(
    database: Connection,
) -> None:
    result = _validated(
        _reads(database).search("Alpha", postcode=None, limit=20), "suburb-search.v1.schema.json"
    )
    assert result["availability"]["status"] == "dataset_unavailable"
    assert result["release"] is None


def test_detail_reports_identity_dates_and_unknown_suburbs(
    database: Connection, world: dict[str, str]
) -> None:
    detail = _validated(_reads(database).detail("1001"), "suburb-detail.v1.schema.json")
    assert detail["name"] == "ALPHA"
    assert detail["bbox"] == [151.0, -33.8, 151.01, -33.79]
    assert detail["coverage"] == "accepted"
    assert detail["source"]["last_update"].startswith("2024-08-14")
    assert detail["release"]["dataset_release_id"] == world["suburbs"]
    with pytest.raises(SuburbNotFoundError):
        _reads(database).detail("999999")


def test_points_use_st_covers_so_edges_and_vertices_are_inside(
    database: Connection, world: dict[str, str]
) -> None:
    context = _context(database, categories="train-station")
    names = [
        feature["properties"]["name"] for feature in context["layers"]["train-station"]["features"]
    ]
    assert names == ["EDGE STN", "INSIDE STN", "VERTEX STN"]
    details = context["layer_details"]["train-station"]
    assert details["excluded_non_operational"] == 1
    assert details["matched_count"] == 4
    assert context["coverage"]["train-station"] == "accepted"
    everything = _context(database, categories="train-station", operational="all")
    assert len(everything["layers"]["train-station"]["features"]) == 4
    statuses = {
        feature["properties"]["name"]: feature["properties"]["operational_status"]
        for feature in everything["layers"]["train-station"]["features"]
    }
    assert statuses["CLOSED STN"] == "non-operational"


def test_empty_accepted_layer_differs_from_unpublished_and_unregistered_layers(
    database: Connection, world: dict[str, str]
) -> None:
    context = _context(database, categories="library,hospital,schools")
    assert context["coverage"]["library"] == "accepted"
    assert context["layers"]["library"]["features"] == []
    assert context["coverage"]["hospital"] == "unavailable"
    assert context["layer_details"]["hospital"]["reason"] == "layer_not_in_release"
    database.execute(
        "DELETE FROM serving.accepted_generation WHERE dataset_id='nsw-government-schools'"
    )
    without_schools = _context(database, categories="library,schools")
    assert without_schools["coverage"]["schools"] == "unavailable"
    assert without_schools["layer_details"]["schools"]["reason"] == "dataset_unavailable"
    assert without_schools["releases"]["schools"] is None


def test_schools_keep_the_school_points_v2_contract_and_boundary_points(
    database: Connection, world: dict[str, str]
) -> None:
    schema = json.loads((CONTRACTS / "school-points.v2.schema.json").read_text("utf-8"))
    context = _context(database, categories="schools")
    features = context["layers"]["schools"]["features"]
    assert [feature["properties"]["school_code"] for feature in features] == ["S1", "S2"]
    for feature in features:
        jsonschema.Draft202012Validator(schema).validate(feature["properties"])
        assert feature["properties"]["provenance"]["release_id"] == world["schools"]


def test_reserves_intersect_clip_and_report_excluded_invalid_geometry(
    database: Connection, world: dict[str, str]
) -> None:
    context = _context(database, categories="protected-reserve")
    features = context["layers"]["protected-reserve"]["features"]
    assert [feature["properties"]["name"] for feature in features] == ["PARTLY INSIDE NP"]
    assert features[0]["properties"]["display_clipped"] is True
    assert features[0]["properties"]["match"] == "intersects"
    assert context["layer_details"]["protected-reserve"]["excluded_invalid_geometry"] == 1
    assert context["coverage"]["protected-reserve"] == "partial"


def test_invalid_boundary_makes_every_layer_unavailable(
    database: Connection, world: dict[str, str]
) -> None:
    context = _context(database, suburb_id="1004", categories="schools,train-station")
    assert context["suburb"]["boundary"]["geometry"] is None
    assert context["coverage"] == {
        "boundary": "unavailable",
        "schools": "unavailable",
        "train-station": "unavailable",
    }
    assert {item["reason"] for item in context["layer_details"].values()} == {
        "boundary_geometry_unavailable"
    }


def test_truncation_is_explicit_and_deterministic(
    database: Connection, world: dict[str, str]
) -> None:
    context = _context(database, categories="train-station", limit="1")
    assert [f["properties"]["name"] for f in context["layers"]["train-station"]["features"]] == [
        "EDGE STN"
    ]
    assert context["truncated"] is True
    assert context["layer_details"]["train-station"]["eligible_count"] == 3
    assert context["coverage"]["train-station"] == "partial"


def test_candidate_rows_never_appear_until_publication_switches_the_generation(
    database: Connection, world: dict[str, str]
) -> None:
    request = build_map_context_request("1001", {"categories": "train-station"})
    datasets = relevant_datasets(request.categories)
    before = _reads(database).release_pointers(datasets)
    candidate = _release(database, "nsw-amenities")
    _feature(
        database,
        candidate,
        "train-station",
        "train-station:9",
        "NEW STN",
        "POINT(151.004 -33.794)",
        {"operationalstatus": 1},
    )
    names = {
        f["properties"]["name"]
        for f in _context(database, categories="train-station")["layers"]["train-station"][
            "features"
        ]
    }
    assert "NEW STN" not in names
    assert map_context_etag(request, _reads(database).release_pointers(datasets)) == (
        map_context_etag(request, before)
    )
    _accept(database, candidate)
    after = _context(database, categories="train-station")
    assert [f["properties"]["name"] for f in after["layers"]["train-station"]["features"]] == [
        "NEW STN"
    ]
    assert after["releases"]["train-station"]["dataset_release_id"] == candidate
    assert map_context_etag(request, _reads(database).release_pointers(datasets)) != (
        map_context_etag(request, before)
    )


def test_old_layers_are_stale_after_the_freshness_window(
    database: Connection, world: dict[str, str]
) -> None:
    database.execute(
        "UPDATE ops.dataset_release SET created_at=now()-interval '401 days' WHERE id=%s",
        (world["amenities"],),
    )
    context = _context(database, categories="library,schools")
    assert context["coverage"]["library"] == "stale"
    assert context["layer_details"]["library"]["stale"] is True
    assert context["coverage"]["schools"] == "accepted"


def test_amenity_probe_can_use_the_generation_scoped_gist_index(
    database: Connection, world: dict[str, str]
) -> None:
    database.execute("SET enable_seqscan = off")
    plan = database.execute(
        """EXPLAIN (FORMAT JSON)
        SELECT feature.record_id FROM warehouse.reference_feature feature,
            (SELECT ST_GeomFromText(%s,4326) AS geom) boundary
        WHERE feature.dataset_release_id=%s AND feature.layer = ANY(%s)
          AND feature.geometry_status='valid' AND feature.geom && boundary.geom""",
        (ALPHA, world["amenities"], ["train-station"]),
    ).fetchone()
    assert plan is not None
    assert "reference_feature_map_amenity_geom_idx" in json.dumps(plan)


def test_contract_fixtures_can_be_regenerated_from_the_synthetic_world(
    database: Connection, world: dict[str, str]
) -> None:
    """Set PROPERTYSCOPE_WRITE_SUBURB_MAP_FIXTURES=1 to refresh the checked-in valid fixtures."""
    payloads = {
        "suburb-search.v1.valid.json": _reads(database).search("Mayfield", postcode=None, limit=20),
        "suburb-detail.v1.valid.json": _reads(database).detail("1001"),
        "suburb-map-context.v1.valid.json": _context(
            database, categories="schools,train-station,library,protected-reserve,hospital"
        ),
    }
    if os.getenv("PROPERTYSCOPE_WRITE_SUBURB_MAP_FIXTURES") == "1":
        for name, payload in payloads.items():
            (CONTRACTS / "fixtures" / name).write_text(
                json.dumps(payload, indent=2, default=str) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    for name in payloads:
        assert (CONTRACTS / "fixtures" / name).is_file(), name
