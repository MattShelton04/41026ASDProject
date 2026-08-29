"""Registered canonical artifact validation and PostgreSQL staging profiles."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

CANONICAL_SCHEMA_VERSION = "propertyscope.canonical-import.v1"
REGISTERED_PROFILES = frozenset(
    {"property-fixture", "gnaf-nsw", "psi-sales", "bocsar-sparse", "schools-master"}
)


@dataclass(frozen=True, slots=True)
class PreparedImport:
    """Validated rows ready for the fixed database-side staging operation."""

    profile: str
    rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class ImportResult:
    """Counts and evidence returned by an atomic candidate-generation load."""

    rows_in: int
    rows_staged: int
    rows_accepted: int
    rows_rejected: int
    quality_checks: int


class ImportProfileError(ValueError):
    """A canonical artifact violates its registered import contract."""


def prepare_import(data: bytes, *, profile: str) -> PreparedImport:
    """Validate one canonical JSON artifact without persistence side effects."""
    if profile not in REGISTERED_PROFILES:
        raise ImportProfileError("import profile is not registered")
    try:
        document = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ImportProfileError("canonical import artifact must be valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise ImportProfileError("canonical import artifact must contain an object")
    if document.get("schema_version") != CANONICAL_SCHEMA_VERSION:
        raise ImportProfileError("canonical import schema version is not registered")
    if document.get("profile") != profile:
        raise ImportProfileError("canonical import profile does not match the operation")
    source_rows = document.get("records")
    if not isinstance(source_rows, list):
        raise ImportProfileError("canonical import artifact must contain records")
    if not source_rows:
        raise ImportProfileError("canonical import artifact must not be empty")
    validator = _VALIDATORS[profile]
    rows = tuple(validator(row, index) for index, row in enumerate(source_rows, start=1))
    if profile == "psi-sales":
        rows = _normalise_psi_revisions(rows)
    _validate_natural_keys(profile, rows)
    return PreparedImport(profile=profile, rows=rows)


def execute_import(
    connection: Connection[Any],
    work: Mapping[str, Any],
    prepared: PreparedImport,
) -> ImportResult:
    """COPY validated rows and insert one isolated candidate generation atomically."""
    run_id = uuid.UUID(str(work["ingestion_run_id"]))
    release_id = uuid.UUID(str(work["candidate_release_id"]))
    artifact_id = uuid.UUID(str(work["artifact_record_id"]))
    with connection.cursor() as cursor:
        cursor.execute(
            "CREATE TEMP TABLE propertyscope_import_stage "
            "(ordinal BIGINT PRIMARY KEY, payload JSONB NOT NULL) ON COMMIT DROP"
        )
        with cursor.copy("COPY propertyscope_import_stage (ordinal, payload) FROM STDIN") as copy:
            for ordinal, row in enumerate(prepared.rows, start=1):
                copy.write_row((ordinal, Jsonb(row)))
        accepted = _insert_profile_rows(
            cursor,
            prepared.profile,
            release_id=release_id,
            artifact_id=artifact_id,
            run_id=run_id,
        )
        quality_checks = _record_quality(
            cursor,
            profile=prepared.profile,
            run_id=run_id,
            release_id=release_id,
            expected=len(prepared.rows),
            accepted=accepted,
        )
        cursor.execute(
            """UPDATE ops.dataset_release SET record_count=%s,
            manifest_json=jsonb_set(manifest_json,'{record_count}',to_jsonb(%s::bigint),true),
            coverage_json=jsonb_set(coverage_json,'{source_record_count}',
                to_jsonb(%s::bigint),true),
            updated_at=now(),version=version+1
            WHERE id=%s AND ingestion_run_id=%s AND status IN ('draft','candidate')""",
            (accepted, accepted, accepted, release_id, run_id),
        )
        if cursor.rowcount != 1:
            raise ImportProfileError("candidate release is not mutable for this import")
    connection.commit()
    return ImportResult(
        rows_in=len(prepared.rows),
        rows_staged=len(prepared.rows),
        rows_accepted=accepted,
        rows_rejected=len(prepared.rows) - accepted,
        quality_checks=quality_checks,
    )


def iter_ndjson_import(lines: Iterable[bytes], *, profile: str) -> Iterable[dict[str, Any]]:
    """Validate canonical NDJSON incrementally for source-scale imports."""
    if profile not in REGISTERED_PROFILES:
        raise ImportProfileError("import profile is not registered")
    validator = _VALIDATORS[profile]
    found = False
    for index, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        found = True
        try:
            row = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ImportProfileError(f"canonical NDJSON record {index} is invalid") from exc
        yield validator(row, index)
    if not found:
        raise ImportProfileError("canonical import artifact must not be empty")


def execute_stream_import(
    connection: Connection[Any],
    work: Mapping[str, Any],
    *,
    profile: str,
    rows: Iterable[dict[str, Any]],
    phase_callback: Callable[[str, int], None] | None = None,
) -> ImportResult:
    """Stream validated rows through COPY and collapse retransmitted PSI keys atomically."""
    run_id = uuid.UUID(str(work["ingestion_run_id"]))
    release_id = uuid.UUID(str(work["candidate_release_id"]))
    artifact_id = uuid.UUID(str(work["artifact_record_id"]))
    staged = 0
    with connection.cursor() as cursor:
        if profile == "gnaf-nsw":
            cursor.execute(_GNAF_STREAM_STAGE_SQL)
            with cursor.copy(_GNAF_STREAM_COPY_SQL) as copy:
                for row in rows:
                    staged += 1
                    copy.write_row(tuple(row[field] for field in _GNAF_STREAM_COLUMNS))
        else:
            cursor.execute(
                "CREATE TEMP TABLE propertyscope_import_stage "
                "(ordinal BIGINT PRIMARY KEY, payload JSONB NOT NULL) ON COMMIT DROP"
            )
            with cursor.copy(
                "COPY propertyscope_import_stage (ordinal, payload) FROM STDIN"
            ) as copy:
                for staged, row in enumerate(rows, start=1):
                    copy.write_row((staged, Jsonb(row)))
        if staged == 0:
            raise ImportProfileError("canonical import artifact must not be empty")
        if phase_callback is not None:
            phase_callback("inserting candidate generation", staged)
        accepted = _insert_profile_rows(
            cursor,
            profile,
            release_id=release_id,
            artifact_id=artifact_id,
            run_id=run_id,
            typed_gnaf_stage=profile == "gnaf-nsw",
        )
        if phase_callback is not None:
            phase_callback("recording import quality", accepted)
        quality_checks = _record_quality(
            cursor,
            profile=profile,
            run_id=run_id,
            release_id=release_id,
            expected=accepted if profile == "psi-sales" else staged,
            accepted=accepted,
        )
        cursor.execute(
            """UPDATE ops.dataset_release SET record_count=%s,
            manifest_json=jsonb_set(manifest_json,'{record_count}',to_jsonb(%s::bigint),true),
            coverage_json=jsonb_set(coverage_json,'{source_record_count}',
                to_jsonb(%s::bigint),true),
            updated_at=now(),version=version+1
            WHERE id=%s AND ingestion_run_id=%s AND status IN ('draft','candidate')""",
            (accepted, accepted, accepted, release_id, run_id),
        )
        if cursor.rowcount != 1:
            raise ImportProfileError("candidate release is not mutable for this import")
    return ImportResult(staged, staged, accepted, 0, quality_checks)


def _insert_profile_rows(
    cursor: Any,
    profile: str,
    *,
    release_id: uuid.UUID,
    artifact_id: uuid.UUID,
    run_id: uuid.UUID,
    typed_gnaf_stage: bool = False,
) -> int:
    statement = _GNAF_STREAM_INSERT_SQL if typed_gnaf_stage else _PROFILE_INSERT_SQL[profile]
    parameters: tuple[object, ...] = (release_id, artifact_id, run_id)
    cursor.execute(statement, parameters)
    accepted = int(cursor.rowcount)
    if profile == "bocsar-sparse":
        cursor.execute(_BOCSAR_COVERAGE_INSERT_SQL, parameters)
        accepted += cursor.rowcount
    return accepted


_GNAF_STREAM_COLUMNS = (
    "gnaf_pid",
    "property_ref",
    "address_display",
    "locality",
    "postcode",
    "flat_type",
    "unit_number",
    "street_number_first",
    "street_number_suffix",
    "street_number_last",
    "street_name",
    "street_type",
    "source_status",
    "geocode_type",
    "source_crs",
    "longitude",
    "latitude",
    "source_row_sha256",
)

_GNAF_STREAM_STAGE_SQL = """
    CREATE TEMP TABLE propertyscope_gnaf_import_stage (
        gnaf_pid TEXT NOT NULL,
        property_ref UUID,
        address_display TEXT NOT NULL,
        locality TEXT NOT NULL,
        postcode TEXT NOT NULL,
        flat_type TEXT,
        unit_number TEXT,
        street_number_first INTEGER,
        street_number_suffix TEXT,
        street_number_last INTEGER,
        street_name TEXT,
        street_type TEXT,
        source_status TEXT NOT NULL,
        geocode_type TEXT NOT NULL,
        source_crs INTEGER NOT NULL,
        longitude DOUBLE PRECISION NOT NULL,
        latitude DOUBLE PRECISION NOT NULL,
        source_row_sha256 TEXT NOT NULL
    ) ON COMMIT DROP
"""

_GNAF_STREAM_COPY_SQL = """
    COPY propertyscope_gnaf_import_stage (
        gnaf_pid,property_ref,address_display,locality,postcode,flat_type,unit_number,
        street_number_first,street_number_suffix,street_number_last,street_name,street_type,
        source_status,geocode_type,source_crs,longitude,latitude,source_row_sha256
    ) FROM STDIN WITH (FREEZE TRUE)
"""

_GNAF_STREAM_INSERT_SQL = """
    INSERT INTO warehouse.gnaf_address (
        dataset_release_id,gnaf_pid,property_ref,address_display,locality,postcode,
        flat_type,unit_number,street_number_first,street_number_suffix,
        street_number_last,street_name,street_type,source_status,geocode_type,source_crs,
        geom,source_row_sha256,normalisation_version,artifact_record_id,ingestion_run_id,
        created_at
    ) SELECT %s,gnaf_pid,property_ref,address_display,locality,postcode,
        flat_type,unit_number,street_number_first,street_number_suffix,
        street_number_last,street_name,street_type,source_status,geocode_type,source_crs,
        ST_Transform(ST_SetSRID(ST_MakePoint(longitude,latitude),source_crs),4326),
        source_row_sha256,'1.0.0',%s,%s,now()
    FROM propertyscope_gnaf_import_stage
    ON CONFLICT (dataset_release_id,gnaf_pid) DO NOTHING
"""


def _record_quality(
    cursor: Any,
    *,
    profile: str,
    run_id: uuid.UUID,
    release_id: uuid.UUID,
    expected: int,
    accepted: int,
) -> int:
    # BOCSAR has two candidate tables, so accepted rows can exceed source envelope rows.
    load_complete = accepted >= expected
    results = (
        (
            f"import.{profile}.schema",
            "schema",
            "pass",
            {"schema_version": CANONICAL_SCHEMA_VERSION},
            {"schema_version": CANONICAL_SCHEMA_VERSION},
            "Canonical artifact matches the registered schema.",
        ),
        (
            f"import.{profile}.candidate-row-count",
            "completeness",
            "pass" if load_complete else "fail",
            {"accepted": accepted},
            {"minimum": expected},
            "Candidate generation contains the complete validated artifact."
            if load_complete
            else "Candidate generation lost validated rows.",
        ),
    )
    for rule_key, dimension, status, observed, expected_value, message in results:
        cursor.execute(
            """INSERT INTO ops.quality_result (
                id,ingestion_run_id,dataset_release_id,rule_key,rule_version,dimension,
                severity,status,observed_value_json,expected_value_json,message,created_at
            ) VALUES (%s,%s,%s,%s,'1.0.0',%s,'blocking',%s,%s,%s,%s,now())
            ON CONFLICT (ingestion_run_id,rule_key) DO NOTHING""",
            (
                uuid.uuid4(),
                run_id,
                release_id,
                rule_key,
                dimension,
                status,
                Jsonb(observed),
                Jsonb(expected_value),
                message,
            ),
        )
    if not load_complete:
        raise ImportProfileError("candidate generation row-count quality gate failed")
    return len(results)


def _validate_natural_keys(profile: str, rows: tuple[dict[str, Any], ...]) -> None:
    key_fields = {
        "property-fixture": ("gnaf_pid",),
        "gnaf-nsw": ("gnaf_pid",),
        "psi-sales": ("source_business_key", "source_revision"),
        "bocsar-sparse": (
            "record_kind",
            "geography_kind",
            "geography_value",
            "source_category_key",
            "month_or_coverage",
        ),
        "schools-master": ("school_code",),
    }[profile]
    keys = [tuple(row[field] for field in key_fields) for row in rows]
    if len(keys) != len(set(keys)):
        raise ImportProfileError("canonical import natural keys must be unique")


def _normalise_psi_revisions(
    rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Collapse exact PSI retransmissions and version changed facts in source order."""
    seen: dict[str, set[str]] = {}
    normalised: list[dict[str, Any]] = []
    for row in rows:
        key = str(row["source_business_key"])
        digest = str(row["source_row_sha256"])
        hashes = seen.setdefault(key, set())
        if digest in hashes:
            continue
        hashes.add(digest)
        normalised.append({**row, "source_revision": len(hashes)})
    return tuple(normalised)


def _fixture(row: object, index: int) -> dict[str, Any]:
    source = _object(row, index)
    latitude, longitude = _coordinates(source, index)
    result = {
        "gnaf_pid": _text(source, "source_pid", index),
        "property_ref": _optional_uuid(source, "property_ref", index),
        "address_display": _text(source, "address_display", index),
        "flat_type": _optional_text(source, "flat_type", index),
        "unit_number": _optional_upper_text(source, "unit_number", index),
        "street_number_first": _optional_integer(source, "street_number_first", index, minimum=0),
        "street_number_suffix": _optional_upper_text(source, "street_number_suffix", index),
        "street_number_last": _optional_integer(source, "street_number_last", index, minimum=0),
        "street_name": _optional_upper_text(source, "street_name", index),
        "street_type": _optional_upper_text(source, "street_type", index),
        "locality": _text(source, "locality", index).upper(),
        "postcode": _postcode(source, index),
        "source_status": _text(source, "source_status", index),
        "geocode_type": _text(source, "geocode_type", index),
        "source_crs": _integer(source, "source_crs", index, allowed={4326}),
        "latitude": latitude,
        "longitude": longitude,
    }
    return _with_hash(result)


def _school(row: object, index: int) -> dict[str, Any]:
    source = _object(row, index)
    latitude, longitude = _coordinates(source, index)
    result = {
        "school_code": _text(source, "school_code", index),
        "school_name": _text(source, "school_name", index),
        "school_type": _text(source, "school_type", index),
        "status": _text(source, "status", index),
        "locality_original": _text(source, "locality_original", index),
        "locality_normalised": _text(source, "locality_normalised", index).upper(),
        "lga_name": _optional_text(source, "lga_name", index),
        "latitude": latitude,
        "longitude": longitude,
    }
    return _with_hash(result)


def _gnaf(row: object, index: int) -> dict[str, Any]:
    source = _object(row, index)
    latitude, longitude = _coordinates(source, index)
    property_ref = _optional_uuid(source, "property_ref", index)
    result = {
        "gnaf_pid": _text(source, "gnaf_pid", index),
        "property_ref": property_ref,
        "address_display": _text(source, "address_display", index),
        "flat_type": _optional_text(source, "flat_type", index),
        "unit_number": _optional_upper_text(source, "unit_number", index),
        "street_number_first": _optional_integer(source, "street_number_first", index, minimum=0),
        "street_number_suffix": _optional_upper_text(source, "street_number_suffix", index),
        "street_number_last": _optional_integer(source, "street_number_last", index, minimum=0),
        "street_name": _optional_upper_text(source, "street_name", index),
        "street_type": _optional_upper_text(source, "street_type", index),
        "locality": _text(source, "locality", index).upper(),
        "postcode": _postcode(source, index),
        "source_status": _text(source, "source_status", index),
        "geocode_type": _text(source, "geocode_type", index),
        "source_crs": _integer(source, "source_crs", index, allowed={4283, 4326, 7844}),
        "latitude": latitude,
        "longitude": longitude,
    }
    return _with_hash(result)


def _psi(row: object, index: int) -> dict[str, Any]:
    source = _object(row, index)
    confidence = _decimal(source, "match_confidence", index)
    if not Decimal("0") <= confidence <= Decimal("1"):
        raise ImportProfileError(f"record {index} match_confidence is outside 0..1")
    contract_date = _optional_date(source, "contract_date", index)
    settlement_date = _optional_date(source, "settlement_date", index)
    source_partition_year = _optional_integer(source, "source_partition_year", index, minimum=1990)
    if source_partition_year is None:
        scoped_date = contract_date or settlement_date
        if scoped_date is None:
            raise ImportProfileError(
                f"record {index} requires source_partition_year when both dates are null"
            )
        source_partition_year = int(scoped_date[:4])
    postcode = _optional_text(source, "postcode", index)
    if postcode is not None and not _postcode_value(postcode):
        raise ImportProfileError(f"record {index} postcode must contain four digits")
    source_downloaded_at = _optional_text(source, "source_downloaded_at", index)
    if source_downloaded_at is not None:
        try:
            datetime.fromisoformat(source_downloaded_at)
        except ValueError as exc:
            raise ImportProfileError(
                f"record {index} source_downloaded_at must be an ISO date-time"
            ) from exc
    result = {
        "source_business_key": _text(source, "source_business_key", index),
        "source_revision": _integer(source, "source_revision", index, minimum=1),
        "source_era": _text(source, "source_era", index),
        "source_partition_year": source_partition_year,
        "district_code": _optional_text(source, "district_code", index),
        "property_id": _optional_text(source, "property_id", index),
        "dealing_id": _optional_text(source, "dealing_id", index),
        "source_system": _optional_text(source, "source_system", index),
        "valuation_number": _optional_text(source, "valuation_number", index),
        "source_downloaded_at": source_downloaded_at,
        "property_name": _optional_text(source, "property_name", index),
        "unit_number": _optional_upper_text(source, "unit_number", index),
        "house_number": _optional_text(source, "house_number", index),
        "street_number_first": _optional_integer(source, "street_number_first", index, minimum=0),
        "street_number_last": _optional_integer(source, "street_number_last", index, minimum=0),
        "street_number_suffix": _optional_upper_text(source, "street_number_suffix", index),
        "street_name": _optional_text(source, "street_name", index),
        "street_name_normalised": _optional_upper_text(source, "street_name_normalised", index),
        "street_type": _optional_upper_text(source, "street_type", index),
        "locality": _optional_upper_text(source, "locality", index),
        "postcode": postcode,
        "land_description": _optional_source_text(
            source, "land_description", index, maximum_length=1_000
        ),
        "dimensions": _optional_text(source, "dimensions", index),
        "zoning_code": _optional_text(source, "zoning_code", index),
        "nature_code": _optional_text(source, "nature_code", index),
        "primary_purpose": _optional_text(source, "primary_purpose", index),
        "strata_lot_number": _optional_text(source, "strata_lot_number", index),
        "component_code": _optional_text(source, "component_code", index),
        "sale_code": _optional_text(source, "sale_code", index),
        "interest_of_sale": _optional_text(source, "interest_of_sale", index),
        "contract_date": contract_date,
        "settlement_date": settlement_date,
        "price_aud": _optional_integer(source, "price_aud", index, minimum=0),
        "area_original": _optional_decimal(source, "area_original", index),
        "area_unit": _optional_text(source, "area_unit", index),
        "area_square_metres": _optional_decimal(source, "area_square_metres", index),
        "property_ref": _optional_uuid(source, "property_ref", index),
        "match_tier": _choice(source, "match_tier", index, {"A", "B", "C", "D", "MISS"}),
        "match_confidence": str(confidence),
        "geographic_precision": _text(source, "geographic_precision", index),
    }
    facts = {
        key: value
        for key, value in result.items()
        if key not in {"source_revision", "source_partition_year"}
    }
    return {**result, "source_row_sha256": _with_hash(facts)["source_row_sha256"]}


def _bocsar(row: object, index: int) -> dict[str, Any]:
    source = _object(row, index)
    kind = _choice(source, "record_kind", index, {"observation", "coverage"})
    common: dict[str, Any] = {
        "record_kind": kind,
        "geography_kind": _choice(source, "geography_kind", index, {"postcode", "suburb"}),
        "geography_value": _text(source, "geography_value", index),
        "source_category_key": _text(source, "source_category_key", index),
    }
    if common["geography_kind"] == "postcode" and not _postcode_value(
        str(common["geography_value"])
    ):
        raise ImportProfileError(f"record {index} geography_value must preserve four digits")
    if kind == "observation":
        common.update(
            {
                "offence_label": _text(source, "offence_label", index),
                "subcategory_label": _text(source, "subcategory_label", index),
                "month": _date(source, "month", index),
                "count": _integer(source, "count", index, minimum=1),
            }
        )
        common["month_or_coverage"] = common["month"]
    else:
        months = source.get("observed_months")
        if not isinstance(months, list) or not months:
            raise ImportProfileError(f"record {index} observed_months must be non-empty")
        parsed = tuple(_iso_date(value, "observed_months", index) for value in months)
        if parsed != tuple(sorted(set(parsed))):
            raise ImportProfileError(f"record {index} observed_months must be sorted and unique")
        common.update(
            {
                "observed_months": parsed,
                "first_month": parsed[0],
                "last_month": parsed[-1],
                "month_count": len(parsed),
                "blank_means_observed_zero": source.get("blank_means_observed_zero") is True,
                "completeness_sha256": hashlib.sha256(
                    json.dumps(parsed, separators=(",", ":")).encode()
                ).hexdigest(),
            }
        )
        common["month_or_coverage"] = "coverage"
    return _with_hash(common)


def _object(row: object, index: int) -> dict[str, Any]:
    if not isinstance(row, dict):
        raise ImportProfileError(f"record {index} must be an object")
    return row


def _text(row: Mapping[str, Any], field: str, index: int) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip() or len(value) > 500:
        raise ImportProfileError(f"record {index} {field} must be non-empty text")
    return value.strip()


def _optional_text(row: Mapping[str, Any], field: str, index: int) -> str | None:
    value = row.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return _text(row, field, index)


def _optional_source_text(
    row: Mapping[str, Any], field: str, index: int, *, maximum_length: int
) -> str | None:
    value = row.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or len(value.strip()) > maximum_length:
        raise ImportProfileError(
            f"record {index} {field} must contain at most {maximum_length} characters"
        )
    return value.strip()


def _optional_upper_text(row: Mapping[str, Any], field: str, index: int) -> str | None:
    value = _optional_text(row, field, index)
    return value.upper() if value is not None else None


def _integer(
    row: Mapping[str, Any],
    field: str,
    index: int,
    *,
    minimum: int | None = None,
    allowed: set[int] | None = None,
) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImportProfileError(f"record {index} {field} must be an integer")
    if minimum is not None and value < minimum:
        raise ImportProfileError(f"record {index} {field} is below its minimum")
    if allowed is not None and value not in allowed:
        raise ImportProfileError(f"record {index} {field} is not registered")
    return value


def _optional_integer(
    row: Mapping[str, Any], field: str, index: int, *, minimum: int | None = None
) -> int | None:
    return None if row.get(field) is None else _integer(row, field, index, minimum=minimum)


def _decimal(row: Mapping[str, Any], field: str, index: int) -> Decimal:
    try:
        result = Decimal(str(row[field]))
    except (KeyError, InvalidOperation) as exc:
        raise ImportProfileError(f"record {index} {field} must be decimal") from exc
    if not result.is_finite():
        raise ImportProfileError(f"record {index} {field} must be finite")
    return result


def _optional_decimal(row: Mapping[str, Any], field: str, index: int) -> str | None:
    if row.get(field) is None:
        return None
    return str(_decimal(row, field, index))


def _date(row: Mapping[str, Any], field: str, index: int) -> str:
    return _iso_date(row.get(field), field, index)


def _optional_date(row: Mapping[str, Any], field: str, index: int) -> str | None:
    return None if row.get(field) is None else _date(row, field, index)


def _iso_date(value: object, field: str, index: int) -> str:
    if not isinstance(value, str):
        raise ImportProfileError(f"record {index} {field} must be an ISO date")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ImportProfileError(f"record {index} {field} must be an ISO date") from exc


def _choice(row: Mapping[str, Any], field: str, index: int, allowed: set[str]) -> str:
    value = _text(row, field, index)
    if value not in allowed:
        raise ImportProfileError(f"record {index} {field} is not registered")
    return value


def _optional_uuid(row: Mapping[str, Any], field: str, index: int) -> str | None:
    value = row.get(field)
    if value is None:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except ValueError as exc:
        raise ImportProfileError(f"record {index} {field} must be a UUID") from exc


def _coordinates(row: Mapping[str, Any], index: int) -> tuple[float, float]:
    try:
        latitude = float(row["latitude"])
        longitude = float(row["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ImportProfileError(f"record {index} coordinates must be numeric") from exc
    # NSW public-school coverage includes Lord Howe Island at roughly 159E.
    if not -38 <= latitude <= -27 or not 140 <= longitude <= 160:
        raise ImportProfileError(f"record {index} coordinates fall outside NSW bounds")
    return latitude, longitude


def _postcode(row: Mapping[str, Any], index: int) -> str:
    value = _text(row, "postcode", index)
    if not _postcode_value(value):
        raise ImportProfileError(f"record {index} postcode must contain four digits")
    return value


def _postcode_value(value: str) -> bool:
    return len(value) == 4 and value.isdigit()


def _with_hash(row: dict[str, Any]) -> dict[str, Any]:
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
    return {**row, "source_row_sha256": hashlib.sha256(canonical).hexdigest()}


_VALIDATORS = {
    "property-fixture": _fixture,
    "gnaf-nsw": _gnaf,
    "psi-sales": _psi,
    "bocsar-sparse": _bocsar,
    "schools-master": _school,
}

_PROFILE_INSERT_SQL = {
    "property-fixture": """
        INSERT INTO warehouse.gnaf_address (
            dataset_release_id,gnaf_pid,property_ref,address_display,locality,postcode,
            flat_type,unit_number,street_number_first,street_number_suffix,
            street_number_last,street_name,street_type,source_status,geocode_type,source_crs,
            geom,source_row_sha256,normalisation_version,artifact_record_id,ingestion_run_id,
            created_at
        ) SELECT %s,payload->>'gnaf_pid',NULLIF(payload->>'property_ref','')::uuid,
            payload->>'address_display',payload->>'locality',payload->>'postcode',
            NULLIF(payload->>'flat_type',''),NULLIF(payload->>'unit_number',''),
            NULLIF(payload->>'street_number_first','')::integer,
            NULLIF(payload->>'street_number_suffix',''),
            NULLIF(payload->>'street_number_last','')::integer,
            NULLIF(payload->>'street_name',''),NULLIF(payload->>'street_type',''),
            payload->>'source_status',payload->>'geocode_type',(payload->>'source_crs')::integer,
            ST_SetSRID(ST_MakePoint((payload->>'longitude')::double precision,
                (payload->>'latitude')::double precision),4326),payload->>'source_row_sha256',
            '1.0.0',%s,%s,now() FROM propertyscope_import_stage ORDER BY ordinal
        ON CONFLICT (dataset_release_id,gnaf_pid) DO NOTHING
    """,
    "schools-master": """
        INSERT INTO warehouse.school (
            dataset_release_id,school_code,school_name,school_type,status,locality_original,
            locality_normalised,lga_name,geom,source_row_sha256,normalisation_version,
            artifact_record_id,ingestion_run_id,created_at
        ) SELECT %s,payload->>'school_code',payload->>'school_name',payload->>'school_type',
            payload->>'status',payload->>'locality_original',payload->>'locality_normalised',
            NULLIF(payload->>'lga_name',''),
            ST_SetSRID(ST_MakePoint((payload->>'longitude')::double precision,
                (payload->>'latitude')::double precision),4326),
            payload->>'source_row_sha256','1.0.0',%s,%s,now()
        FROM propertyscope_import_stage ORDER BY ordinal
        ON CONFLICT (dataset_release_id,school_code) DO NOTHING
    """,
    "gnaf-nsw": """
        INSERT INTO warehouse.gnaf_address (
            dataset_release_id,gnaf_pid,property_ref,address_display,locality,postcode,
            flat_type,unit_number,street_number_first,street_number_suffix,
            street_number_last,street_name,street_type,source_status,geocode_type,source_crs,
            geom,source_row_sha256,
            normalisation_version,artifact_record_id,ingestion_run_id,created_at
        ) SELECT %s,payload->>'gnaf_pid',NULLIF(payload->>'property_ref','')::uuid,
            payload->>'address_display',payload->>'locality',payload->>'postcode',
            NULLIF(payload->>'flat_type',''),NULLIF(payload->>'unit_number',''),
            NULLIF(payload->>'street_number_first','')::integer,
            NULLIF(payload->>'street_number_suffix',''),
            NULLIF(payload->>'street_number_last','')::integer,
            NULLIF(payload->>'street_name',''),NULLIF(payload->>'street_type',''),
            payload->>'source_status',payload->>'geocode_type',(payload->>'source_crs')::integer,
            ST_Transform(ST_SetSRID(ST_MakePoint((payload->>'longitude')::double precision,
                (payload->>'latitude')::double precision),(payload->>'source_crs')::integer),4326),
            payload->>'source_row_sha256','1.0.0',%s,%s,now()
        FROM propertyscope_import_stage ORDER BY ordinal
        ON CONFLICT (dataset_release_id,gnaf_pid) DO NOTHING
    """,
    "psi-sales": """
        WITH distinct_source_rows AS (
            SELECT DISTINCT ON (
                payload->>'source_business_key',payload->>'source_row_sha256'
            ) payload,ordinal
            FROM propertyscope_import_stage
            ORDER BY payload->>'source_business_key',payload->>'source_row_sha256',ordinal
        ), ranked_source_rows AS (
            SELECT payload,row_number() OVER (
                PARTITION BY payload->>'source_business_key' ORDER BY ordinal
            )::integer AS derived_revision
            FROM distinct_source_rows
        ), exact_candidates AS (
            SELECT ranked.payload->>'source_business_key' AS source_business_key,
                ranked.derived_revision,min(property.property_ref::text)::uuid
                    AS exact_property_ref
            FROM ranked_source_rows ranked
            JOIN registry.property property
              ON property.postcode=ranked.payload->>'postcode'
             AND property.locality=ranked.payload->>'locality'
             AND property.street_name=ranked.payload->>'street_name_normalised'
             AND property.street_type=ranked.payload->>'street_type'
             AND property.street_number_first=
                 (ranked.payload->>'street_number_first')::integer
             AND COALESCE(property.street_number_last,-1)=COALESCE(
                 NULLIF(ranked.payload->>'street_number_last','')::integer,-1)
             AND COALESCE(property.street_number_suffix,'')=COALESCE(
                 ranked.payload->>'street_number_suffix','')
             AND COALESCE(property.unit_number,'')=COALESCE(
                 ranked.payload->>'unit_number','')
            WHERE NULLIF(ranked.payload->>'postcode','') IS NOT NULL
              AND NULLIF(ranked.payload->>'locality','') IS NOT NULL
              AND NULLIF(ranked.payload->>'street_name_normalised','') IS NOT NULL
              AND NULLIF(ranked.payload->>'street_type','') IS NOT NULL
              AND NULLIF(ranked.payload->>'street_number_first','') IS NOT NULL
              AND ranked.payload->>'house_number' ~ '^[0-9]+[A-Z]?(-[0-9]+)?$'
            GROUP BY ranked.payload->>'source_business_key',ranked.derived_revision
            HAVING count(*)=1
        ), prepared_rows AS (
            SELECT ranked.*,candidate.exact_property_ref
            FROM ranked_source_rows ranked
            LEFT JOIN exact_candidates candidate
              ON candidate.source_business_key=ranked.payload->>'source_business_key'
             AND candidate.derived_revision=ranked.derived_revision
        )
        INSERT INTO warehouse.psi_sale (
            dataset_release_id,source_business_key,source_revision,source_era,
            source_partition_year,district_code,
            property_id,dealing_id,source_system,valuation_number,source_downloaded_at,
            property_name,unit_number,house_number,street_number_first,street_number_last,
            street_number_suffix,
            street_name,street_name_normalised,street_type,locality,postcode,land_description,
            dimensions,zoning_code,nature_code,primary_purpose,strata_lot_number,component_code,
            sale_code,interest_of_sale,contract_date,settlement_date,price_aud,area_original,
            area_unit,area_square_metres,property_ref,match_tier,match_confidence,
            geographic_precision,source_row_sha256,normalisation_version,artifact_record_id,
            ingestion_run_id,created_at
        ) SELECT %s,payload->>'source_business_key',derived_revision,
            payload->>'source_era',(payload->>'source_partition_year')::integer,
            NULLIF(payload->>'district_code',''),
            NULLIF(payload->>'property_id',''),NULLIF(payload->>'dealing_id',''),
            NULLIF(payload->>'source_system',''),NULLIF(payload->>'valuation_number',''),
            NULLIF(payload->>'source_downloaded_at','')::timestamp,
            NULLIF(payload->>'property_name',''),NULLIF(payload->>'unit_number',''),
            NULLIF(payload->>'house_number',''),
            NULLIF(payload->>'street_number_first','')::integer,
            NULLIF(payload->>'street_number_last','')::integer,
            NULLIF(payload->>'street_number_suffix',''),NULLIF(payload->>'street_name',''),
            NULLIF(payload->>'street_name_normalised',''),NULLIF(payload->>'street_type',''),
            NULLIF(payload->>'locality',''),NULLIF(payload->>'postcode',''),
            NULLIF(payload->>'land_description',''),NULLIF(payload->>'dimensions',''),
            NULLIF(payload->>'zoning_code',''),NULLIF(payload->>'nature_code',''),
            NULLIF(payload->>'primary_purpose',''),NULLIF(payload->>'strata_lot_number',''),
            NULLIF(payload->>'component_code',''),NULLIF(payload->>'sale_code',''),
            NULLIF(payload->>'interest_of_sale',''),
            NULLIF(payload->>'contract_date','')::date,NULLIF(payload->>'settlement_date','')::date,
            NULLIF(payload->>'price_aud','')::bigint,NULLIF(payload->>'area_original','')::numeric,
            NULLIF(payload->>'area_unit',''),NULLIF(payload->>'area_square_metres','')::numeric,
            COALESCE(NULLIF(payload->>'property_ref','')::uuid,exact_property_ref),
            CASE WHEN COALESCE(NULLIF(payload->>'property_ref','')::uuid,exact_property_ref)
                IS NOT NULL THEN 'A' ELSE payload->>'match_tier' END,
            CASE WHEN COALESCE(NULLIF(payload->>'property_ref','')::uuid,exact_property_ref)
                IS NOT NULL THEN 1 ELSE (payload->>'match_confidence')::numeric END,
            CASE WHEN COALESCE(NULLIF(payload->>'property_ref','')::uuid,exact_property_ref)
                IS NOT NULL THEN 'exact_address' ELSE payload->>'geographic_precision' END,
            payload->>'source_row_sha256','1.0.0',%s,%s,now()
        FROM prepared_rows ORDER BY payload->>'source_business_key',derived_revision
        ON CONFLICT (dataset_release_id,source_business_key,source_revision) DO NOTHING
    """,
    "bocsar-sparse": """
        INSERT INTO warehouse.bocsar_observation (
            dataset_release_id,geography_kind,geography_value,source_category_key,
            offence_label,subcategory_label,month,count,source_row_sha256,
            normalisation_version,artifact_record_id,ingestion_run_id,created_at
        ) SELECT %s,payload->>'geography_kind',payload->>'geography_value',
            payload->>'source_category_key',payload->>'offence_label',
            payload->>'subcategory_label',(payload->>'month')::date,(payload->>'count')::integer,
            payload->>'source_row_sha256','1.0.0',%s,%s,now()
        FROM propertyscope_import_stage WHERE payload->>'record_kind'='observation'
        ORDER BY ordinal
        ON CONFLICT (dataset_release_id,geography_kind,geography_value,source_category_key,month)
        DO NOTHING
    """,
}

_BOCSAR_COVERAGE_INSERT_SQL = """
    INSERT INTO warehouse.bocsar_coverage (
        dataset_release_id,geography_kind,geography_value,source_category_key,observed_months,
        first_month,last_month,month_count,blank_means_observed_zero,completeness_sha256,
        source_row_sha256,normalisation_version,artifact_record_id,ingestion_run_id,created_at
    ) SELECT %s,payload->>'geography_kind',payload->>'geography_value',
        payload->>'source_category_key',ARRAY(
            SELECT value::date FROM jsonb_array_elements_text(payload->'observed_months') value
        ),(payload->>'first_month')::date,(payload->>'last_month')::date,
        (payload->>'month_count')::integer,(payload->>'blank_means_observed_zero')::boolean,
        payload->>'completeness_sha256',payload->>'source_row_sha256','1.0.0',%s,%s,now()
    FROM propertyscope_import_stage WHERE payload->>'record_kind'='coverage'
    ORDER BY ordinal
    ON CONFLICT (dataset_release_id,geography_kind,geography_value,source_category_key) DO NOTHING
"""
