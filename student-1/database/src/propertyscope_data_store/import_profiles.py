"""Registered canonical artifact validation and PostgreSQL staging profiles."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from psycopg import Connection
from psycopg.types.json import Jsonb

CANONICAL_SCHEMA_VERSION = "propertyscope.canonical-import.v1"
MAX_BOUNDED_RECORDS = 100_000
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
    """Validate one bounded canonical JSON artifact without persistence side effects."""
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
    if len(source_rows) > MAX_BOUNDED_RECORDS:
        raise ImportProfileError("canonical import artifact exceeds bounded row limit")
    validator = _VALIDATORS[profile]
    rows = tuple(validator(row, index) for index, row in enumerate(source_rows, start=1))
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
            updated_at=now(),version=version+1
            WHERE id=%s AND ingestion_run_id=%s AND status IN ('draft','candidate')""",
            (accepted, accepted, release_id, run_id),
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


def _insert_profile_rows(
    cursor: Any,
    profile: str,
    *,
    release_id: uuid.UUID,
    artifact_id: uuid.UUID,
    run_id: uuid.UUID,
) -> int:
    if profile == "property-fixture":
        return len(cursor.execute("SELECT 1 FROM propertyscope_import_stage").fetchall())
    statement = _PROFILE_INSERT_SQL[profile]
    parameters: tuple[object, ...] = (release_id, artifact_id, run_id)
    cursor.execute(statement, parameters)
    accepted = int(cursor.rowcount)
    if profile == "bocsar-sparse":
        cursor.execute(_BOCSAR_COVERAGE_INSERT_SQL, parameters)
        accepted += cursor.rowcount
    return accepted


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
        "property-fixture": ("source_key",),
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


def _fixture(row: object, index: int) -> dict[str, Any]:
    source = _object(row, index)
    return {"source_key": _text(source, "source_key", index)}


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
    result = {
        "source_business_key": _text(source, "source_business_key", index),
        "source_revision": _integer(source, "source_revision", index, minimum=1),
        "source_era": _text(source, "source_era", index),
        "district_code": _optional_text(source, "district_code", index),
        "property_id": _optional_text(source, "property_id", index),
        "dealing_id": _optional_text(source, "dealing_id", index),
        "contract_date": _optional_date(source, "contract_date", index),
        "settlement_date": _optional_date(source, "settlement_date", index),
        "price_aud": _optional_integer(source, "price_aud", index, minimum=0),
        "area_original": _optional_decimal(source, "area_original", index),
        "area_unit": _optional_text(source, "area_unit", index),
        "area_square_metres": _optional_decimal(source, "area_square_metres", index),
        "property_ref": _optional_uuid(source, "property_ref", index),
        "match_tier": _choice(source, "match_tier", index, {"A", "B", "C", "D", "MISS"}),
        "match_confidence": str(confidence),
        "geographic_precision": _text(source, "geographic_precision", index),
    }
    return _with_hash(result)


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
    if value is None or value == "":
        return None
    return _text(row, field, index)


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
            source_status,geocode_type,source_crs,geom,source_row_sha256,
            normalisation_version,artifact_record_id,ingestion_run_id,created_at
        ) SELECT %s,payload->>'gnaf_pid',NULLIF(payload->>'property_ref','')::uuid,
            payload->>'address_display',payload->>'locality',payload->>'postcode',
            payload->>'source_status',payload->>'geocode_type',(payload->>'source_crs')::integer,
            ST_SetSRID(ST_MakePoint((payload->>'longitude')::double precision,
                (payload->>'latitude')::double precision),4326),
            payload->>'source_row_sha256','1.0.0',%s,%s,now()
        FROM propertyscope_import_stage ORDER BY ordinal
        ON CONFLICT (dataset_release_id,gnaf_pid) DO NOTHING
    """,
    "psi-sales": """
        INSERT INTO warehouse.psi_sale (
            dataset_release_id,source_business_key,source_revision,source_era,district_code,
            property_id,dealing_id,contract_date,settlement_date,price_aud,area_original,
            area_unit,area_square_metres,property_ref,match_tier,match_confidence,
            geographic_precision,source_row_sha256,normalisation_version,artifact_record_id,
            ingestion_run_id,created_at
        ) SELECT %s,payload->>'source_business_key',(payload->>'source_revision')::integer,
            payload->>'source_era',NULLIF(payload->>'district_code',''),
            NULLIF(payload->>'property_id',''),NULLIF(payload->>'dealing_id',''),
            NULLIF(payload->>'contract_date','')::date,NULLIF(payload->>'settlement_date','')::date,
            NULLIF(payload->>'price_aud','')::bigint,NULLIF(payload->>'area_original','')::numeric,
            NULLIF(payload->>'area_unit',''),NULLIF(payload->>'area_square_metres','')::numeric,
            NULLIF(payload->>'property_ref','')::uuid,payload->>'match_tier',
            (payload->>'match_confidence')::numeric,payload->>'geographic_precision',
            payload->>'source_row_sha256','1.0.0',%s,%s,now()
        FROM propertyscope_import_stage ORDER BY ordinal
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
