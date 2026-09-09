"""Registered canonical artifact validation and PostgreSQL staging profiles."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from psycopg import Connection
from psycopg.types.json import Jsonb

from propertyscope_data_store.source_materialisation import (
    BOCSAR_COPY_SQL,
    BOCSAR_COVERAGE_INSERT_SQL,
    BOCSAR_OBSERVATION_INSERT_SQL,
    BOCSAR_STAGE_SQL,
    BOCSAR_STREAM_COLUMNS,
    PSI_COPY_SQL,
    PSI_PHASE_SQL,
    PSI_STAGE_SQL,
    PSI_STREAM_COLUMNS,
)

# Compatibility seam for focused cancellation tests that replace a phase statement.
_PSI_PHASE_SQL = PSI_PHASE_SQL

CANONICAL_SCHEMA_VERSION = "propertyscope.canonical-import.v1"
CANONICAL_PARQUET_MEDIA_TYPE = "application/vnd.apache.parquet"
BOCSAR_PARQUET_SCHEMA_VERSION = "propertyscope.canonical-bocsar-parquet.v1"
BOCSAR_PARQUET_MEDIA_TYPE = CANONICAL_PARQUET_MEDIA_TYPE
BOCSAR_PARQUET_BATCH_ROWS = 65_536
PSI_PARQUET_SCHEMA_VERSION = "propertyscope.canonical-psi-parquet.v1"
PSI_PARQUET_MEDIA_TYPE = CANONICAL_PARQUET_MEDIA_TYPE
PSI_PARQUET_BATCH_ROWS = 65_536
POSTGRES_INTEGER_MAX = 2_147_483_647
POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807
IMPORT_PHASE_LABELS: Mapping[str, str] = {
    "artifact_verification": "Verifying canonical artifact",
    "typed_staging": "Validating and copying typed canonical rows",
    "identity_revision_derivation": "Deriving deterministic identities and revisions",
    "address_resolution": "Resolving eligible exact addresses",
    "target_materialisation": "Materialising isolated candidate generation",
    "verification": "Verifying candidate generation",
}
REGISTERED_PROFILES = frozenset(
    {
        "property-fixture",
        "gnaf-nsw",
        "psi-sales",
        "bocsar-sparse",
        "schools-master",
        "seifa-2021-sal-nsw",
    }
)
_PSI_QUALITY_WARNINGS_KEY = "_propertyscope_import_quality_warnings"
_PSI_ADDRESS_NUMBER_OUT_OF_RANGE = "address_number_out_of_range"


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
    *,
    phase_callback: Callable[[str, int], None] | None = None,
) -> ImportResult:
    """COPY validated rows and insert one isolated candidate generation atomically."""
    result = execute_stream_import(
        connection,
        work,
        profile=prepared.profile,
        rows=prepared.rows,
        phase_callback=phase_callback,
    )
    connection.commit()
    return result


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


def iter_bocsar_parquet_import(path: Path, *, profile: str) -> Iterable[dict[str, Any]]:
    """Validate and stream the registered typed BOCSAR Parquet contract."""
    if profile != "bocsar-sparse":
        raise ImportProfileError("canonical BOCSAR Parquet requires the bocsar-sparse profile")
    try:
        parquet = pq.ParquetFile(path)
    except (OSError, pa.ArrowException) as exc:
        raise ImportProfileError("canonical BOCSAR Parquet artifact is unreadable") from exc
    actual_schema = parquet.schema_arrow
    expected_schema = _bocsar_parquet_schema()
    if not actual_schema.remove_metadata().equals(expected_schema.remove_metadata()):
        raise ImportProfileError("canonical BOCSAR Parquet schema is not registered")
    metadata = actual_schema.metadata or {}
    for key, expected in (expected_schema.metadata or {}).items():
        if metadata.get(key) != expected:
            raise ImportProfileError("canonical BOCSAR Parquet metadata is not registered")
    if parquet.metadata.num_rows == 0:
        raise ImportProfileError("canonical import artifact must not be empty")
    index = 0
    try:
        for batch in parquet.iter_batches(batch_size=BOCSAR_PARQUET_BATCH_ROWS):
            for source in batch.to_pylist():
                index += 1
                yield _bocsar_parquet_row(source, index)
    except (OSError, pa.ArrowException) as exc:
        raise ImportProfileError("canonical BOCSAR Parquet artifact is unreadable") from exc


def iter_parquet_import(path: Path, *, profile: str) -> Iterable[dict[str, Any]]:
    """Dispatch a registered profile to its exact typed Parquet contract."""
    if profile == "gnaf-nsw":
        yield from iter_gnaf_parquet_import(path)
        return
    if profile == "bocsar-sparse":
        yield from iter_bocsar_parquet_import(path, profile=profile)
        return
    if profile == "psi-sales":
        yield from iter_psi_parquet_import(path, profile=profile)
        return
    raise ImportProfileError("canonical Parquet is not registered for this import profile")


def iter_gnaf_parquet_import(path: Path) -> Iterable[dict[str, Any]]:
    """Verify the exact source contract, then use the same normalization as legacy JSON."""
    # Deliberately database-owned: this service does not import backend implementation code.
    schema = pa.schema(
        [
            pa.field("gnaf_pid", pa.string(), nullable=False),
            pa.field("property_ref", pa.string()),
            pa.field("address_display", pa.string(), nullable=False),
            pa.field("flat_type", pa.string()),
            pa.field("unit_number", pa.string()),
            pa.field("street_number_first", pa.int32()),
            pa.field("street_number_suffix", pa.string()),
            pa.field("street_number_last", pa.int32()),
            pa.field("street_name", pa.string()),
            pa.field("street_type", pa.string()),
            pa.field("locality", pa.string(), nullable=False),
            pa.field("postcode", pa.string(), nullable=False),
            pa.field("source_status", pa.string(), nullable=False),
            pa.field("geocode_type", pa.string(), nullable=False),
            pa.field("source_crs", pa.int32(), nullable=False),
            pa.field("latitude", pa.float64(), nullable=False),
            pa.field("longitude", pa.float64(), nullable=False),
        ],
        metadata={
            b"propertyscope.schema_version": b"propertyscope.canonical-gnaf-parquet.v1",
            b"propertyscope.import_profile": b"gnaf-nsw",
        },
    )
    try:
        with pq.ParquetFile(path) as parquet:
            actual = parquet.schema_arrow
            if not actual.remove_metadata().equals(schema.remove_metadata()):
                raise ImportProfileError("canonical G-NAF Parquet schema is not registered")
            if any((actual.metadata or {}).get(k) != v for k, v in schema.metadata.items()):
                raise ImportProfileError("canonical G-NAF Parquet metadata is not registered")
            if parquet.metadata.num_rows == 0:
                raise ImportProfileError("canonical import artifact must not be empty")
            index = 0
            for batch in parquet.iter_batches(batch_size=65_536):
                for row in batch.to_pylist():
                    index += 1
                    yield _gnaf(row, index)
    except (OSError, pa.ArrowException) as exc:
        raise ImportProfileError("canonical G-NAF Parquet artifact is unreadable") from exc


def iter_psi_parquet_import(path: Path, *, profile: str) -> Iterable[dict[str, Any]]:
    """Validate and stream the registered partition-aware PSI Parquet contract."""
    if profile != "psi-sales":
        raise ImportProfileError("canonical PSI Parquet requires the psi-sales profile")
    try:
        parquet = pq.ParquetFile(path)
    except (OSError, pa.ArrowException) as exc:
        raise ImportProfileError("canonical PSI Parquet artifact is unreadable") from exc
    actual_schema = parquet.schema_arrow
    expected_schema = _psi_parquet_schema()
    if not actual_schema.remove_metadata().equals(expected_schema.remove_metadata()):
        raise ImportProfileError("canonical PSI Parquet schema is not registered")
    metadata = actual_schema.metadata or {}
    for key, expected in (expected_schema.metadata or {}).items():
        if metadata.get(key) != expected:
            raise ImportProfileError("canonical PSI Parquet metadata is not registered")
    if parquet.metadata.num_rows == 0:
        raise ImportProfileError("canonical import artifact must not be empty")
    index = 0
    try:
        for batch in parquet.iter_batches(batch_size=PSI_PARQUET_BATCH_ROWS):
            for source in batch.to_pylist():
                index += 1
                yield _psi_parquet_row(source, index)
    except (OSError, pa.ArrowException) as exc:
        raise ImportProfileError("canonical PSI Parquet artifact is unreadable") from exc


def _psi_parquet_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("source_business_key", pa.string(), nullable=False),
            pa.field("source_revision", pa.int32(), nullable=False),
            pa.field("source_era", pa.string(), nullable=False),
            pa.field("source_partition_year", pa.int32(), nullable=False),
            pa.field("district_code", pa.string()),
            pa.field("property_id", pa.string()),
            pa.field("dealing_id", pa.string()),
            pa.field("source_system", pa.string()),
            pa.field("valuation_number", pa.string()),
            pa.field("source_downloaded_at", pa.timestamp("us")),
            pa.field("property_name", pa.string()),
            pa.field("unit_number", pa.string()),
            pa.field("house_number", pa.string()),
            pa.field("street_number_first", pa.int32()),
            pa.field("street_number_last", pa.int32()),
            pa.field("street_number_suffix", pa.string()),
            pa.field("street_name", pa.string()),
            pa.field("street_name_normalised", pa.string()),
            pa.field("street_type", pa.string()),
            pa.field("locality", pa.string()),
            pa.field("postcode", pa.string()),
            pa.field("land_description", pa.string()),
            pa.field("dimensions", pa.string()),
            pa.field("zoning_code", pa.string()),
            pa.field("nature_code", pa.string()),
            pa.field("primary_purpose", pa.string()),
            pa.field("strata_lot_number", pa.string()),
            pa.field("component_code", pa.string()),
            pa.field("sale_code", pa.string()),
            pa.field("interest_of_sale", pa.string()),
            pa.field("contract_date", pa.date32()),
            pa.field("settlement_date", pa.date32()),
            pa.field("price_aud", pa.int64()),
            pa.field("area_original", pa.string()),
            pa.field("area_unit", pa.string()),
            pa.field("area_square_metres", pa.string()),
            pa.field("property_ref", pa.string()),
            pa.field("match_tier", pa.string(), nullable=False),
            pa.field("match_confidence", pa.string(), nullable=False),
            pa.field("geographic_precision", pa.string(), nullable=False),
            pa.field("source_row_sha256", pa.binary(32), nullable=False),
            pa.field("quality_warnings", pa.list_(pa.string())),
        ],
        metadata={
            b"propertyscope.schema_version": PSI_PARQUET_SCHEMA_VERSION.encode(),
            b"propertyscope.import_profile": b"psi-sales",
            b"propertyscope.partition_semantics": b"source-archive-order",
            b"propertyscope.retransmission_semantics": b"business-key-and-row-sha256",
            b"propertyscope.sha256_encoding": b"fixed-size-binary-32",
        },
    )


def _psi_parquet_row(source: dict[str, Any], index: int) -> dict[str, Any]:
    source_revision = _parquet_integer(
        source, "source_revision", index, minimum=1, maximum=POSTGRES_INTEGER_MAX
    )
    source_partition_year = _parquet_integer(
        source, "source_partition_year", index, minimum=1990, maximum=POSTGRES_INTEGER_MAX
    )
    postcode = _parquet_optional_text(source, "postcode", index)
    if postcode is not None and not _postcode_value(postcode):
        raise ImportProfileError(f"record {index} postcode must contain four digits")
    confidence = _parquet_decimal(source, "match_confidence", index, required=True)
    if confidence is None or not Decimal("0") <= confidence <= Decimal("1"):
        raise ImportProfileError(f"record {index} match_confidence is outside 0..1")
    warnings = source.get("quality_warnings")
    if warnings is None:
        parsed_warnings: tuple[str, ...] = ()
    elif (
        not isinstance(warnings, list)
        or any(not isinstance(value, str) for value in warnings)
        or warnings != sorted(set(warnings))
        or set(warnings) - {_PSI_ADDRESS_NUMBER_OUT_OF_RANGE}
    ):
        raise ImportProfileError(f"record {index} quality_warnings are not registered")
    else:
        parsed_warnings = tuple(warnings)
    result: dict[str, Any] = {
        "source_business_key": _parquet_text(source, "source_business_key", index),
        "source_revision": source_revision,
        "source_era": _parquet_text(source, "source_era", index),
        "source_partition_year": source_partition_year,
        "district_code": _parquet_optional_text(source, "district_code", index),
        "property_id": _parquet_optional_text(source, "property_id", index),
        "dealing_id": _parquet_optional_text(source, "dealing_id", index),
        "source_system": _parquet_optional_text(source, "source_system", index),
        "valuation_number": _parquet_optional_text(source, "valuation_number", index),
        "source_downloaded_at": _parquet_optional_datetime(source, "source_downloaded_at", index),
        "property_name": _parquet_optional_text(source, "property_name", index),
        "unit_number": _parquet_optional_text(source, "unit_number", index),
        "house_number": _parquet_optional_text(source, "house_number", index),
        "street_number_first": _parquet_optional_integer(
            source, "street_number_first", index, minimum=0, maximum=POSTGRES_INTEGER_MAX
        ),
        "street_number_last": _parquet_optional_integer(
            source, "street_number_last", index, minimum=0, maximum=POSTGRES_INTEGER_MAX
        ),
        "street_number_suffix": _parquet_optional_text(source, "street_number_suffix", index),
        "street_name": _parquet_optional_text(source, "street_name", index),
        "street_name_normalised": _parquet_optional_text(source, "street_name_normalised", index),
        "street_type": _parquet_optional_text(source, "street_type", index),
        "locality": _parquet_optional_text(source, "locality", index),
        "postcode": postcode,
        "land_description": _parquet_optional_text(
            source, "land_description", index, maximum_length=1_000
        ),
        "dimensions": _parquet_optional_text(source, "dimensions", index),
        "zoning_code": _parquet_optional_text(source, "zoning_code", index),
        "nature_code": _parquet_optional_text(source, "nature_code", index),
        "primary_purpose": _parquet_optional_text(source, "primary_purpose", index),
        "strata_lot_number": _parquet_optional_text(source, "strata_lot_number", index),
        "component_code": _parquet_optional_text(source, "component_code", index),
        "sale_code": _parquet_optional_text(source, "sale_code", index),
        "interest_of_sale": _parquet_optional_text(source, "interest_of_sale", index),
        "contract_date": _parquet_optional_date(source, "contract_date", index),
        "settlement_date": _parquet_optional_date(source, "settlement_date", index),
        "price_aud": _parquet_optional_integer(
            source, "price_aud", index, minimum=0, maximum=POSTGRES_BIGINT_MAX
        ),
        "area_original": _parquet_decimal_text(source, "area_original", index),
        "area_unit": _parquet_optional_text(source, "area_unit", index),
        "area_square_metres": _parquet_decimal_text(source, "area_square_metres", index),
        "property_ref": _parquet_optional_uuid(source, "property_ref", index),
        "match_tier": _parquet_choice(source, "match_tier", index, {"A", "B", "C", "D", "MISS"}),
        "match_confidence": str(confidence),
        "geographic_precision": _parquet_text(source, "geographic_precision", index),
        "source_row_sha256": _parquet_sha256(source, "source_row_sha256", index),
    }
    if parsed_warnings:
        result[_PSI_QUALITY_WARNINGS_KEY] = parsed_warnings
    return result


def _bocsar_parquet_schema() -> pa.Schema:
    return pa.schema(
        [
            pa.field("record_kind", pa.string(), nullable=False),
            pa.field("geography_kind", pa.string(), nullable=False),
            pa.field("geography_value", pa.string(), nullable=False),
            pa.field("source_category_key", pa.string(), nullable=False),
            pa.field("offence_label", pa.string()),
            pa.field("subcategory_label", pa.string()),
            pa.field("month", pa.date32()),
            pa.field("count", pa.int32()),
            pa.field("observed_months", pa.list_(pa.date32())),
            pa.field("first_month", pa.date32()),
            pa.field("last_month", pa.date32()),
            pa.field("month_count", pa.int32()),
            pa.field("blank_means_observed_zero", pa.bool_()),
            pa.field("completeness_sha256", pa.binary(32)),
            pa.field("source_row_sha256", pa.binary(32), nullable=False),
        ],
        metadata={
            b"propertyscope.schema_version": BOCSAR_PARQUET_SCHEMA_VERSION.encode(),
            b"propertyscope.import_profile": b"bocsar-sparse",
            b"propertyscope.zero_semantics": b"coverage-evidence-required",
            b"propertyscope.sha256_encoding": b"fixed-size-binary-32",
        },
    )


def _bocsar_parquet_row(source: dict[str, Any], index: int) -> dict[str, Any]:
    kind = _parquet_choice(source, "record_kind", index, {"observation", "coverage"})
    geography_kind = _parquet_choice(source, "geography_kind", index, {"postcode", "suburb"})
    geography_value = _parquet_text(source, "geography_value", index)
    if geography_kind == "postcode" and not _postcode_value(geography_value):
        raise ImportProfileError(f"record {index} geography_value must preserve four digits")
    common: dict[str, Any] = {
        "record_kind": kind,
        "geography_kind": geography_kind,
        "geography_value": geography_value,
        "source_category_key": _parquet_text(source, "source_category_key", index),
    }
    source_hash = _parquet_sha256(source, "source_row_sha256", index)
    if kind == "observation":
        _require_parquet_nulls(
            source,
            index,
            (
                "observed_months",
                "first_month",
                "last_month",
                "month_count",
                "blank_means_observed_zero",
                "completeness_sha256",
            ),
        )
        month = _parquet_date(source, "month", index)
        count = source.get("count")
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 1 <= count <= POSTGRES_INTEGER_MAX
        ):
            raise ImportProfileError(f"record {index} count is outside its registered range")
        return {
            **common,
            "offence_label": _parquet_text(source, "offence_label", index),
            "subcategory_label": _parquet_text(source, "subcategory_label", index),
            "month": month,
            "count": count,
            "month_or_coverage": month,
            "source_row_sha256": source_hash,
        }

    _require_parquet_nulls(source, index, ("offence_label", "subcategory_label", "month", "count"))
    raw_months = source.get("observed_months")
    if not isinstance(raw_months, list) or not raw_months:
        raise ImportProfileError(f"record {index} observed_months must be non-empty")
    months = tuple(_parquet_date_value(value, "observed_months", index) for value in raw_months)
    if months != tuple(sorted(set(months))):
        raise ImportProfileError(f"record {index} observed_months must be sorted and unique")
    first_month = _parquet_date(source, "first_month", index)
    last_month = _parquet_date(source, "last_month", index)
    if first_month != months[0] or last_month != months[-1]:
        raise ImportProfileError(f"record {index} coverage bounds do not match observed_months")
    month_count = source.get("month_count")
    if month_count != len(months):
        raise ImportProfileError(f"record {index} month_count does not match observed_months")
    zero_semantics = source.get("blank_means_observed_zero")
    if not isinstance(zero_semantics, bool):
        raise ImportProfileError(f"record {index} zero semantics must be boolean")
    completeness = _parquet_sha256(source, "completeness_sha256", index)
    expected_completeness = hashlib.sha256(
        json.dumps(months, separators=(",", ":")).encode()
    ).hexdigest()
    if completeness != expected_completeness:
        raise ImportProfileError(f"record {index} completeness checksum does not match coverage")
    return {
        **common,
        "observed_months": months,
        "first_month": first_month,
        "last_month": last_month,
        "month_count": month_count,
        "blank_means_observed_zero": zero_semantics,
        "completeness_sha256": completeness,
        "month_or_coverage": "coverage",
        "source_row_sha256": source_hash,
    }


def _parquet_text(source: Mapping[str, Any], field: str, index: int) -> str:
    value = source.get(field)
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > 500:
        raise ImportProfileError(f"record {index} {field} must be non-empty text")
    return value.strip()


def _parquet_optional_text(
    source: Mapping[str, Any],
    field: str,
    index: int,
    *,
    maximum_length: int = 500,
) -> str | None:
    value = source.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum_length:
        raise ImportProfileError(
            f"record {index} {field} must contain at most {maximum_length} characters"
        )
    return value.strip()


def _parquet_choice(source: Mapping[str, Any], field: str, index: int, allowed: set[str]) -> str:
    value = _parquet_text(source, field, index)
    if value not in allowed:
        raise ImportProfileError(f"record {index} {field} is not registered")
    return value


def _parquet_date(source: Mapping[str, Any], field: str, index: int) -> str:
    return _parquet_date_value(source.get(field), field, index)


def _parquet_optional_date(source: Mapping[str, Any], field: str, index: int) -> str | None:
    return (
        None if source.get(field) is None else _parquet_date_value(source.get(field), field, index)
    )


def _parquet_optional_datetime(source: Mapping[str, Any], field: str, index: int) -> str | None:
    value = source.get(field)
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise ImportProfileError(f"record {index} {field} must be an ISO date-time")
    return value.isoformat()


def _parquet_date_value(value: object, field: str, index: int) -> str:
    if not isinstance(value, date):
        raise ImportProfileError(f"record {index} {field} must be an ISO date")
    return value.isoformat()


def _parquet_sha256(source: Mapping[str, Any], field: str, index: int) -> str:
    value = source.get(field)
    if not isinstance(value, bytes) or len(value) != 32:
        raise ImportProfileError(f"record {index} {field} must be a SHA-256 value")
    return value.hex()


def _parquet_integer(
    source: Mapping[str, Any],
    field: str,
    index: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = source.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum or value > maximum:
        raise ImportProfileError(f"record {index} {field} is outside its registered range")
    return value


def _parquet_optional_integer(
    source: Mapping[str, Any],
    field: str,
    index: int,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    return (
        None
        if source.get(field) is None
        else _parquet_integer(source, field, index, minimum=minimum, maximum=maximum)
    )


def _parquet_decimal(
    source: Mapping[str, Any], field: str, index: int, *, required: bool
) -> Decimal | None:
    value = source.get(field)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise ImportProfileError(f"record {index} {field} must be decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ImportProfileError(f"record {index} {field} must be decimal") from exc
    if not result.is_finite():
        raise ImportProfileError(f"record {index} {field} must be finite")
    return result


def _parquet_decimal_text(source: Mapping[str, Any], field: str, index: int) -> str | None:
    value = _parquet_decimal(source, field, index, required=False)
    return None if value is None else str(value)


def _parquet_optional_uuid(source: Mapping[str, Any], field: str, index: int) -> str | None:
    value = source.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ImportProfileError(f"record {index} {field} must be a UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise ImportProfileError(f"record {index} {field} must be a UUID") from exc


def _require_parquet_nulls(source: Mapping[str, Any], index: int, fields: tuple[str, ...]) -> None:
    if any(source.get(field) is not None for field in fields):
        raise ImportProfileError(f"record {index} contains fields for the wrong record kind")


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
    quality_warning_rows = 0
    quality_warning_counts: Counter[str] = Counter()
    with connection.cursor() as cursor:
        # Constant batch provenance is checked once by the batch's foreign keys.
        # This transaction also owns the rows; failure rolls back both together.
        cursor.execute(
            """INSERT INTO warehouse.import_batch (
                dataset_release_id,artifact_record_id,ingestion_run_id
            ) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""",
            (release_id, artifact_id, run_id),
        )
        if profile == "gnaf-nsw":
            cursor.execute(_GNAF_STREAM_STAGE_SQL)
            with cursor.copy(_GNAF_STREAM_COPY_SQL) as copy:
                for row in rows:
                    staged += 1
                    _require_copy_ordinal(staged)
                    copy.write_row(tuple(row[field] for field in _GNAF_STREAM_COLUMNS))
        elif profile == "psi-sales":
            cursor.execute(PSI_STAGE_SQL)
            with cursor.copy(PSI_COPY_SQL) as copy:
                for staged, row in enumerate(rows, start=1):
                    _require_copy_ordinal(staged)
                    warnings = row.get(_PSI_QUALITY_WARNINGS_KEY, ())
                    if warnings:
                        quality_warning_rows += 1
                        quality_warning_counts.update(str(warning) for warning in warnings)
                    copy.write_row((staged, *(row[field] for field in PSI_STREAM_COLUMNS[1:])))
            if staged > POSTGRES_INTEGER_MAX:
                raise ImportProfileError(
                    "PSI record count exceeds PostgreSQL INTEGER revision range"
                )
            cursor.execute("ANALYZE propertyscope_psi_import_stage")
        elif profile == "bocsar-sparse":
            cursor.execute(BOCSAR_STAGE_SQL)
            with cursor.copy(BOCSAR_COPY_SQL) as copy:
                for staged, row in enumerate(rows, start=1):
                    _require_copy_ordinal(staged)
                    values = {
                        **row,
                        "ordinal": staged,
                        "observed_months": list(row.get("observed_months", ())) or None,
                    }
                    copy.write_row(tuple(values.get(field) for field in BOCSAR_STREAM_COLUMNS))
            cursor.execute("ANALYZE propertyscope_bocsar_import_stage")
        else:
            cursor.execute(
                "CREATE TEMP TABLE propertyscope_import_stage "
                "(ordinal BIGINT PRIMARY KEY, payload JSONB NOT NULL) ON COMMIT DROP"
            )
            with cursor.copy(
                "COPY propertyscope_import_stage (ordinal, payload) FROM STDIN"
            ) as copy:
                for staged, row in enumerate(rows, start=1):
                    _require_copy_ordinal(staged)
                    copy.write_row((staged, Jsonb(row)))
        if staged == 0:
            raise ImportProfileError("canonical import artifact must not be empty")
        accepted = _insert_profile_rows(
            cursor,
            profile,
            release_id=release_id,
            artifact_id=artifact_id,
            run_id=run_id,
            typed_gnaf_stage=profile == "gnaf-nsw",
            typed_source_stage=profile in {"psi-sales", "bocsar-sparse"},
            phase_rows=staged,
            phase_callback=phase_callback,
        )
        linked_property_rows: int | None = None
        if profile == "psi-sales":
            cursor.execute(
                "SELECT count(*) AS count FROM warehouse.psi_sale "
                "WHERE dataset_release_id=%s AND property_ref IS NOT NULL",
                (release_id,),
            )
            linked = cursor.fetchone()
            if linked is None:
                raise ImportProfileError("PSI property-linkage count is unavailable")
            linked_property_rows = int(linked["count"])
        if phase_callback is not None:
            phase_callback("verification", accepted)
        quality_checks = _record_quality(
            cursor,
            profile=profile,
            run_id=run_id,
            release_id=release_id,
            expected=accepted if profile == "psi-sales" else staged,
            accepted=accepted,
            quality_warning_rows=quality_warning_rows,
            quality_warning_counts=quality_warning_counts,
            linked_property_rows=linked_property_rows,
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
    typed_source_stage: bool = False,
    phase_rows: int = 0,
    phase_callback: Callable[[str, int], None] | None = None,
) -> int:
    if profile == "psi-sales" and typed_source_stage:
        return _insert_psi_rows(
            cursor,
            release_id=release_id,
            artifact_id=artifact_id,
            run_id=run_id,
            phase_rows=phase_rows,
            phase_callback=phase_callback,
        )
    if profile == "bocsar-sparse" and typed_source_stage:
        return _insert_bocsar_rows(
            cursor,
            release_id=release_id,
            artifact_id=artifact_id,
            run_id=run_id,
            phase_rows=phase_rows,
            phase_callback=phase_callback,
        )
    if phase_callback is not None:
        phase_callback("target_materialisation", phase_rows)
    statement = _GNAF_STREAM_INSERT_SQL if typed_gnaf_stage else _PROFILE_INSERT_SQL[profile]
    parameters: tuple[object, ...] = (release_id, artifact_id, run_id)
    cursor.execute(statement, parameters)
    if profile == "bocsar-sparse":
        cursor.execute(_BOCSAR_COVERAGE_INSERT_SQL, parameters)
        cursor.execute(_BOCSAR_OBSERVATION_COUNT_SQL, parameters)
        observations = cursor.fetchone()
        cursor.execute(_BOCSAR_COVERAGE_COUNT_SQL, parameters)
        coverage = cursor.fetchone()
        if observations is None or coverage is None:
            raise ImportProfileError("candidate generation row count is unavailable")
        return int(observations["count"]) + int(coverage["count"])
    cursor.execute(_PROFILE_COUNT_SQL[profile], parameters)
    persisted = cursor.fetchone()
    if persisted is None:
        raise ImportProfileError("candidate generation row count is unavailable")
    return int(persisted["count"])


def _insert_psi_rows(
    cursor: Any,
    *,
    release_id: uuid.UUID,
    artifact_id: uuid.UUID,
    run_id: uuid.UUID,
    phase_rows: int,
    phase_callback: Callable[[str, int], None] | None,
) -> int:
    """Run PSI identity, address, and target work as truthful transaction-local phases."""
    parameters: tuple[object, ...] = (release_id, artifact_id, run_id)
    inserted = 0
    for phase_key, statement in _PSI_PHASE_SQL:
        if phase_callback is not None:
            phase_callback(phase_key, phase_rows)
        cursor.execute(statement, parameters if phase_key == "target_materialisation" else ())
        if phase_key == "identity_revision_derivation":
            cursor.execute("ANALYZE propertyscope_psi_identity_stage")
        elif phase_key == "address_resolution":
            cursor.execute("ANALYZE propertyscope_psi_address_resolution")
        else:
            inserted = max(0, int(cursor.rowcount))
    if inserted:
        return inserted
    cursor.execute(_PROFILE_COUNT_SQL["psi-sales"], parameters)
    persisted = cursor.fetchone()
    if persisted is None:
        raise ImportProfileError("candidate generation row count is unavailable")
    return int(persisted["count"])


def _insert_bocsar_rows(
    cursor: Any,
    *,
    release_id: uuid.UUID,
    artifact_id: uuid.UUID,
    run_id: uuid.UUID,
    phase_rows: int,
    phase_callback: Callable[[str, int], None] | None,
) -> int:
    """Materialise typed sparse facts and use scans only for conflict-only replay."""
    parameters: tuple[object, ...] = (release_id, artifact_id, run_id)
    if phase_callback is not None:
        phase_callback("target_materialisation", phase_rows)
    cursor.execute(BOCSAR_OBSERVATION_INSERT_SQL, parameters)
    inserted = max(0, int(cursor.rowcount))
    cursor.execute(BOCSAR_COVERAGE_INSERT_SQL, parameters)
    inserted += max(0, int(cursor.rowcount))
    if inserted:
        return inserted
    cursor.execute(_BOCSAR_OBSERVATION_COUNT_SQL, parameters)
    observations = cursor.fetchone()
    cursor.execute(_BOCSAR_COVERAGE_COUNT_SQL, parameters)
    coverage = cursor.fetchone()
    if observations is None or coverage is None:
        raise ImportProfileError("candidate generation row count is unavailable")
    return int(observations["count"]) + int(coverage["count"])


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
    quality_warning_rows: int = 0,
    quality_warning_counts: Mapping[str, int] | None = None,
    linked_property_rows: int | None = None,
) -> int:
    # BOCSAR has two candidate tables, so accepted rows can exceed source envelope rows.
    load_complete = accepted >= expected
    blocking_checks_passed = load_complete
    results: list[tuple[str, str, str, str, object, object, str]] = [
        (
            f"import.{profile}.schema",
            "schema",
            "blocking",
            "pass",
            {"schema_version": CANONICAL_SCHEMA_VERSION},
            {"schema_version": CANONICAL_SCHEMA_VERSION},
            "Canonical artifact matches the registered schema.",
        ),
        (
            f"import.{profile}.candidate-row-count",
            "completeness",
            "blocking",
            "pass" if load_complete else "fail",
            {"accepted": accepted},
            {"minimum": expected},
            "Candidate generation contains the complete validated artifact."
            if load_complete
            else "Candidate generation lost validated rows.",
        ),
    ]
    if linked_property_rows is not None:
        results.append(
            (
                "import.psi-sales.property-linkage",
                "referential",
                "blocking",
                "pass" if linked_property_rows > 0 else "fail",
                {
                    "linked": linked_property_rows,
                    "unmatched": max(0, accepted - linked_property_rows),
                },
                {"minimum_linked": 1},
                "At least one sale is linked to a registered property."
                if linked_property_rows > 0
                else (
                    "No sales are linked to registered properties; publish or repair the "
                    "accepted address registry before publishing this sales generation."
                ),
            )
        )
    if profile == "seifa-2021-sal-nsw":
        cursor.execute(
            """SELECT count(*) AS count,count(DISTINCT sal_code) AS distinct_codes,
            count(*) FILTER (WHERE state='NSW' AND reference_year=2021) AS scoped,
            count(*) FILTER (WHERE usual_resident_population IS NOT NULL) AS populated
            FROM warehouse.seifa_sal WHERE dataset_release_id=%s""",
            (release_id,),
        )
        evidence = cursor.fetchone()
        coherent = bool(
            evidence
            and int(evidence["count"]) == accepted
            and int(evidence["distinct_codes"]) == accepted
            and int(evidence["scoped"]) == accepted
            and int(evidence["populated"]) == accepted
        )
        blocking_checks_passed = blocking_checks_passed and coherent
        results.append(
            (
                "import.seifa-2021-sal-nsw.nsw-scope",
                "coverage",
                "blocking",
                "pass" if coherent else "fail",
                dict(evidence or {}),
                {"rows": accepted, "state": "NSW", "reference_year": 2021},
                "Every accepted row is a unique NSW 2021 SAL with population evidence."
                if coherent
                else "SEIFA candidate scope or uniqueness evidence is inconsistent.",
            )
        )
    if quality_warning_rows:
        results.append(
            (
                f"import.{profile}.source-anomalies",
                "validity",
                "warning",
                "warn",
                {
                    "rows_retained": quality_warning_rows,
                    "anomaly_counts": dict(sorted((quality_warning_counts or {}).items())),
                },
                {"rows_retained": 0},
                "Publisher sale rows were retained, but unusable derived address-number "
                "components were recorded as unknown; original house-number text remains "
                "available.",
            )
        )
    for rule_key, dimension, severity, status, observed, expected_value, message in results:
        cursor.execute(
            """INSERT INTO ops.quality_result (
                id,ingestion_run_id,dataset_release_id,rule_key,rule_version,dimension,
                severity,status,observed_value_json,expected_value_json,message,created_at
            ) VALUES (%s,%s,%s,%s,'1.0.0',%s,%s,%s,%s,%s,%s,now())
            ON CONFLICT (ingestion_run_id,rule_key) DO NOTHING""",
            (
                uuid.uuid4(),
                run_id,
                release_id,
                rule_key,
                dimension,
                severity,
                status,
                Jsonb(observed),
                Jsonb(expected_value),
                message,
            ),
        )
    if not blocking_checks_passed:
        raise ImportProfileError("candidate generation blocking quality gate failed")
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
        "seifa-2021-sal-nsw": ("sal_code",),
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
        "street_number_first": _optional_integer(
            source, "street_number_first", index, minimum=0, maximum=POSTGRES_INTEGER_MAX
        ),
        "street_number_suffix": _optional_upper_text(source, "street_number_suffix", index),
        "street_number_last": _optional_integer(
            source, "street_number_last", index, minimum=0, maximum=POSTGRES_INTEGER_MAX
        ),
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


def _seifa(row: object, index: int) -> dict[str, Any]:
    source = _object(row, index)
    sal_code = _text(source, "sal_code", index)
    if len(sal_code) != 5 or not sal_code.isdigit() or not sal_code.startswith("1"):
        raise ImportProfileError(f"record {index} sal_code must be a five-digit NSW SAL code")
    if _choice(source, "state", index, {"NSW"}) != "NSW":
        raise AssertionError("unreachable")
    result: dict[str, Any] = {
        "sal_code": sal_code,
        "sal_name": _text(source, "sal_name", index),
        "locality_name": _text(source, "locality_name", index).upper(),
        "state": "NSW",
        "reference_year": _integer(source, "reference_year", index, allowed={2021}),
        "usual_resident_population": _integer(
            source,
            "usual_resident_population",
            index,
            minimum=0,
            maximum=POSTGRES_BIGINT_MAX,
        ),
    }
    for key in ("irsd", "irsad", "ier", "ieo"):
        score_field = f"{key}_score"
        decile_field = f"{key}_australia_decile"
        score = _optional_decimal(source, score_field, index)
        decile = _optional_integer(source, decile_field, index, minimum=1, maximum=10)
        if (score is None) != (decile is None):
            raise ImportProfileError(
                f"record {index} {key.upper()} score and Australia decile must both be present"
            )
        result[score_field] = score
        result[decile_field] = decile
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
        "street_number_first": _optional_integer(
            source, "street_number_first", index, minimum=0, maximum=POSTGRES_INTEGER_MAX
        ),
        "street_number_suffix": _optional_upper_text(source, "street_number_suffix", index),
        "street_number_last": _optional_integer(
            source, "street_number_last", index, minimum=0, maximum=POSTGRES_INTEGER_MAX
        ),
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
    quality_warnings: set[str] = set()
    confidence = _decimal(source, "match_confidence", index)
    if not Decimal("0") <= confidence <= Decimal("1"):
        raise ImportProfileError(f"record {index} match_confidence is outside 0..1")
    contract_date = _optional_date(source, "contract_date", index)
    settlement_date = _optional_date(source, "settlement_date", index)
    source_partition_year = _optional_integer(
        source,
        "source_partition_year",
        index,
        minimum=1990,
        maximum=POSTGRES_INTEGER_MAX,
    )
    if source_partition_year is None:
        scoped_date = contract_date or settlement_date
        if scoped_date is None:
            raise ImportProfileError(
                f"record {index} requires source_partition_year when both dates are null"
            )
        source_partition_year = int(scoped_date[:4])
    postcode = _optional_text(source, "postcode", index)
    if postcode is not None and not _postcode_value(postcode):
        # Historical PSI archives use values such as ``0`` and truncated numeric
        # strings when the postcode is unknown. A cached canonical artifact can retain
        # that publisher fact; the typed warehouse model records it as unknown rather
        # than guessing a postcode or rejecting the complete source generation.
        if len(postcode) < 4 and postcode.isdigit():
            postcode = None
        else:
            raise ImportProfileError(f"record {index} postcode must contain four digits")
    source_downloaded_at = _optional_text(source, "source_downloaded_at", index)
    if source_downloaded_at is not None:
        try:
            datetime.fromisoformat(source_downloaded_at)
        except ValueError as exc:
            raise ImportProfileError(
                f"record {index} source_downloaded_at must be an ISO date-time"
            ) from exc
    street_number_first = _optional_psi_address_integer(
        source, "street_number_first", index, quality_warnings=quality_warnings
    )
    street_number_last = _optional_psi_address_integer(
        source, "street_number_last", index, quality_warnings=quality_warnings
    )
    if street_number_first is None and _derived_psi_address_number_is_out_of_range(
        source.get("house_number"), last=False
    ):
        quality_warnings.add(_PSI_ADDRESS_NUMBER_OUT_OF_RANGE)
    if street_number_last is None and _derived_psi_address_number_is_out_of_range(
        source.get("house_number"), last=True
    ):
        quality_warnings.add(_PSI_ADDRESS_NUMBER_OUT_OF_RANGE)
    result = {
        "source_business_key": _text(source, "source_business_key", index),
        "source_revision": _integer(
            source, "source_revision", index, minimum=1, maximum=POSTGRES_INTEGER_MAX
        ),
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
        "street_number_first": street_number_first,
        "street_number_last": street_number_last,
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
        "price_aud": _optional_integer(
            source, "price_aud", index, minimum=0, maximum=POSTGRES_BIGINT_MAX
        ),
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
    validated = {**result, "source_row_sha256": _with_hash(facts)["source_row_sha256"]}
    if quality_warnings:
        validated[_PSI_QUALITY_WARNINGS_KEY] = tuple(sorted(quality_warnings))
    return validated


def _optional_psi_address_integer(
    row: Mapping[str, Any],
    field: str,
    index: int,
    *,
    quality_warnings: set[str],
) -> int | None:
    """Retain a PSI sale when only its derived address integer is unusable."""
    if row.get(field) is None:
        return None
    parsed = _integer(row, field, index, minimum=0)
    if parsed > POSTGRES_INTEGER_MAX:
        quality_warnings.add(_PSI_ADDRESS_NUMBER_OUT_OF_RANGE)
        return None
    return parsed


def _derived_psi_address_number_is_out_of_range(value: object, *, last: bool) -> bool:
    """Recognise the conservative number shape emitted by the PSI adapter."""
    if not isinstance(value, str):
        return False
    if last:
        if "-" not in value:
            return False
        candidate = value.split("-", 1)[1].strip()
    else:
        candidate = value.strip()
    digits = ""
    for character in candidate:
        if character.isdigit():
            digits += character
        elif digits:
            break
    return bool(digits) and int(digits) > POSTGRES_INTEGER_MAX


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
                "count": _integer(source, "count", index, minimum=1, maximum=POSTGRES_INTEGER_MAX),
            }
        )
        common["month_or_coverage"] = common["month"]
    else:
        months = source.get("observed_months")
        if not isinstance(months, list) or not months:
            raise ImportProfileError(f"record {index} observed_months must be non-empty")
        parsed = tuple(_iso_date(value, "observed_months", index) for value in months)
        if len(parsed) > POSTGRES_INTEGER_MAX:
            raise ImportProfileError(f"record {index} observed_months exceeds its maximum")
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


def _require_copy_ordinal(ordinal: int) -> None:
    if ordinal > POSTGRES_BIGINT_MAX:
        raise ImportProfileError("canonical record ordinal exceeds PostgreSQL BIGINT range")


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
    maximum: int | None = None,
    allowed: set[int] | None = None,
) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ImportProfileError(f"record {index} {field} must be an integer")
    if minimum is not None and value < minimum:
        raise ImportProfileError(f"record {index} {field} is below its minimum")
    if maximum is not None and value > maximum:
        raise ImportProfileError(f"record {index} {field} is above its maximum")
    if allowed is not None and value not in allowed:
        raise ImportProfileError(f"record {index} {field} is not registered")
    return value


def _optional_integer(
    row: Mapping[str, Any],
    field: str,
    index: int,
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int | None:
    return (
        None
        if row.get(field) is None
        else _integer(row, field, index, minimum=minimum, maximum=maximum)
    )


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
    "seifa-2021-sal-nsw": _seifa,
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
    "seifa-2021-sal-nsw": """
        INSERT INTO warehouse.seifa_sal (
            dataset_release_id,sal_code,sal_name,locality_name,state,reference_year,
            irsd_score,irsd_australia_decile,irsad_score,irsad_australia_decile,
            ier_score,ier_australia_decile,ieo_score,ieo_australia_decile,
            usual_resident_population,source_row_sha256,normalisation_version,
            artifact_record_id,ingestion_run_id,created_at
        ) SELECT %s,payload->>'sal_code',payload->>'sal_name',payload->>'locality_name',
            payload->>'state',(payload->>'reference_year')::smallint,
            NULLIF(payload->>'irsd_score','')::numeric,
            NULLIF(payload->>'irsd_australia_decile','')::smallint,
            NULLIF(payload->>'irsad_score','')::numeric,
            NULLIF(payload->>'irsad_australia_decile','')::smallint,
            NULLIF(payload->>'ier_score','')::numeric,
            NULLIF(payload->>'ier_australia_decile','')::smallint,
            NULLIF(payload->>'ieo_score','')::numeric,
            NULLIF(payload->>'ieo_australia_decile','')::smallint,
            (payload->>'usual_resident_population')::bigint,
            payload->>'source_row_sha256','1.0.0',%s,%s,now()
        FROM propertyscope_import_stage ORDER BY ordinal
        ON CONFLICT (dataset_release_id,sal_code) DO NOTHING
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

_LEGACY_PSI_IDENTITY_SQL = """
    CREATE TEMP TABLE propertyscope_psi_identity_stage ON COMMIT DROP AS
    WITH distinct_source_rows AS (
        SELECT DISTINCT ON (
            payload->>'source_business_key',payload->>'source_row_sha256'
        ) ordinal,payload
        FROM propertyscope_import_stage
        ORDER BY payload->>'source_business_key',payload->>'source_row_sha256',ordinal
    )
    SELECT ordinal,payload,payload->>'source_business_key' AS source_business_key,
        payload->>'source_row_sha256' AS source_row_sha256,
        row_number() OVER (
            PARTITION BY payload->>'source_business_key' ORDER BY ordinal
        )::integer AS derived_revision
    FROM distinct_source_rows
"""

_LEGACY_PSI_ADDRESS_RESOLUTION_SQL = """
    CREATE TEMP TABLE propertyscope_psi_address_resolution ON COMMIT DROP AS
    WITH eligible_addresses AS (
        SELECT DISTINCT payload->>'postcode' AS postcode,
            payload->>'locality' AS locality,
            payload->>'street_name_normalised' AS street_name_normalised,
            payload->>'street_type' AS street_type,
            (payload->>'street_number_first')::integer AS street_number_first,
            NULLIF(payload->>'street_number_last','')::integer AS street_number_last,
            NULLIF(payload->>'street_number_suffix','') AS street_number_suffix,
            NULLIF(payload->>'unit_number','') AS unit_number
        FROM propertyscope_psi_identity_stage
        WHERE NULLIF(payload->>'postcode','') IS NOT NULL
          AND NULLIF(payload->>'locality','') IS NOT NULL
          AND NULLIF(payload->>'street_name_normalised','') IS NOT NULL
          AND NULLIF(payload->>'street_type','') IS NOT NULL
          AND NULLIF(payload->>'street_number_first','') IS NOT NULL
          AND payload->>'house_number' ~ '^[0-9]+[A-Z]?(-[0-9]+)?$'
    )
    SELECT eligible.postcode,eligible.locality,eligible.street_name_normalised,
        eligible.street_type,eligible.street_number_first,eligible.street_number_last,
        eligible.street_number_suffix,eligible.unit_number,
        CASE WHEN count(property.property_ref)=1
            THEN min(property.property_ref::text)::uuid ELSE NULL END AS exact_property_ref
    FROM eligible_addresses eligible
    JOIN registry.property property
      ON property.postcode=eligible.postcode
     AND property.locality=eligible.locality
     AND property.street_name=eligible.street_name_normalised
     AND property.street_type=eligible.street_type
     AND property.street_number_first=eligible.street_number_first
     AND COALESCE(property.street_number_last,-1)=COALESCE(eligible.street_number_last,-1)
     AND COALESCE(property.street_number_suffix,'')=COALESCE(eligible.street_number_suffix,'')
     AND COALESCE(property.unit_number,'')=COALESCE(eligible.unit_number,'')
    GROUP BY eligible.postcode,eligible.locality,eligible.street_name_normalised,
        eligible.street_type,eligible.street_number_first,eligible.street_number_last,
        eligible.street_number_suffix,eligible.unit_number
"""

_LEGACY_PSI_TARGET_INSERT_SQL = """
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
    ) SELECT %s,identity.source_business_key,identity.derived_revision,
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
        COALESCE(NULLIF(payload->>'property_ref','')::uuid,resolution.exact_property_ref),
        CASE WHEN COALESCE(NULLIF(payload->>'property_ref','')::uuid,
            resolution.exact_property_ref) IS NOT NULL THEN 'A' ELSE payload->>'match_tier' END,
        CASE WHEN COALESCE(NULLIF(payload->>'property_ref','')::uuid,
            resolution.exact_property_ref) IS NOT NULL
            THEN 1 ELSE (payload->>'match_confidence')::numeric END,
        CASE WHEN COALESCE(NULLIF(payload->>'property_ref','')::uuid,
            resolution.exact_property_ref) IS NOT NULL
            THEN 'exact_address' ELSE payload->>'geographic_precision' END,
        identity.source_row_sha256,'1.0.0',%s,%s,now()
    FROM propertyscope_psi_identity_stage identity
    LEFT JOIN propertyscope_psi_address_resolution resolution
      ON resolution.postcode=payload->>'postcode'
     AND resolution.locality=payload->>'locality'
     AND resolution.street_name_normalised=payload->>'street_name_normalised'
     AND resolution.street_type=payload->>'street_type'
     AND resolution.street_number_first=(payload->>'street_number_first')::integer
     AND COALESCE(resolution.street_number_last,-1)=COALESCE(
         NULLIF(payload->>'street_number_last','')::integer,-1)
     AND COALESCE(resolution.street_number_suffix,'')=COALESCE(
         payload->>'street_number_suffix','')
     AND COALESCE(resolution.unit_number,'')=COALESCE(payload->>'unit_number','')
     AND identity.payload->>'house_number' ~ '^[0-9]+[A-Z]?(-[0-9]+)?$'
    ORDER BY identity.source_business_key,identity.derived_revision
    ON CONFLICT (dataset_release_id,source_business_key,source_revision) DO NOTHING
"""

_LEGACY_PSI_PHASE_SQL = (
    ("identity_revision_derivation", _LEGACY_PSI_IDENTITY_SQL),
    ("address_resolution", _LEGACY_PSI_ADDRESS_RESOLUTION_SQL),
    ("target_materialisation", _LEGACY_PSI_TARGET_INSERT_SQL),
)

_PROFILE_COUNT_SQL = {
    "property-fixture": """
        SELECT count(*) AS count FROM warehouse.gnaf_address
        WHERE dataset_release_id=%s AND artifact_record_id=%s AND ingestion_run_id=%s
    """,
    "gnaf-nsw": """
        SELECT count(*) AS count FROM warehouse.gnaf_address
        WHERE dataset_release_id=%s AND artifact_record_id=%s AND ingestion_run_id=%s
    """,
    "psi-sales": """
        SELECT count(*) AS count FROM warehouse.psi_sale
        WHERE dataset_release_id=%s AND artifact_record_id=%s AND ingestion_run_id=%s
    """,
    "schools-master": """
        SELECT count(*) AS count FROM warehouse.school
        WHERE dataset_release_id=%s AND artifact_record_id=%s AND ingestion_run_id=%s
    """,
    "seifa-2021-sal-nsw": """
        SELECT count(*) AS count FROM warehouse.seifa_sal
        WHERE dataset_release_id=%s AND artifact_record_id=%s AND ingestion_run_id=%s
    """,
}

_BOCSAR_OBSERVATION_COUNT_SQL = """
    SELECT count(*) AS count FROM warehouse.bocsar_observation
    WHERE dataset_release_id=%s AND artifact_record_id=%s AND ingestion_run_id=%s
"""

_BOCSAR_COVERAGE_COUNT_SQL = """
    SELECT count(*) AS count FROM warehouse.bocsar_coverage
    WHERE dataset_release_id=%s AND artifact_record_id=%s AND ingestion_run_id=%s
"""

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
