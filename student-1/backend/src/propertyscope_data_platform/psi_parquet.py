"""Typed canonical Parquet writer for partitioned PSI sale imports."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]

from propertyscope_data_platform.adapters.psi import PsiSale
from propertyscope_data_platform.canonical_parquet import (
    CANONICAL_PARQUET_BATCH_ROWS,
    CANONICAL_PARQUET_MEDIA_TYPE,
    POSTGRES_INTEGER_MAX,
    canonical_parquet_writer,
    canonical_row_sha256,
    write_row_group,
)

PSI_PARQUET_MEDIA_TYPE = CANONICAL_PARQUET_MEDIA_TYPE
PSI_PARQUET_SCHEMA_VERSION = "propertyscope.canonical-psi-parquet.v1"
PSI_PARQUET_BATCH_ROWS = CANONICAL_PARQUET_BATCH_ROWS
PSI_ADDRESS_NUMBER_OUT_OF_RANGE = "address_number_out_of_range"
POSTGRES_BIGINT_MAX = 9_223_372_036_854_775_807

_SCHEMA_METADATA = {
    b"propertyscope.schema_version": PSI_PARQUET_SCHEMA_VERSION.encode(),
    b"propertyscope.import_profile": b"psi-sales",
    b"propertyscope.partition_semantics": b"source-archive-order",
    b"propertyscope.retransmission_semantics": b"business-key-and-row-sha256",
    b"propertyscope.sha256_encoding": b"fixed-size-binary-32",
}


def psi_parquet_schema() -> pa.Schema:
    """Return the exact v1 Arrow schema written into canonical PSI artifacts."""
    fields = [
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
        # Preserve publisher decimal text exactly; validation still requires finite NUMERIC values.
        pa.field("area_original", pa.string()),
        pa.field("area_unit", pa.string()),
        pa.field("area_square_metres", pa.string()),
        pa.field("property_ref", pa.string()),
        pa.field("match_tier", pa.string(), nullable=False),
        pa.field("match_confidence", pa.string(), nullable=False),
        pa.field("geographic_precision", pa.string(), nullable=False),
        pa.field("source_row_sha256", pa.binary(32), nullable=False),
        pa.field("quality_warnings", pa.list_(pa.string())),
    ]
    return pa.schema(fields, metadata=_SCHEMA_METADATA)


def write_psi_parquet(
    destination: Path,
    partitions: Iterable[tuple[int, Iterable[PsiSale]]],
    *,
    on_record: Callable[[], None] | None = None,
    batch_rows: int = PSI_PARQUET_BATCH_ROWS,
) -> int:
    """Write partitions in source order with bounded row groups and return total rows."""
    if batch_rows < 1:
        raise ValueError("PSI Parquet batch_rows must be positive")
    schema = psi_parquet_schema()
    writer = canonical_parquet_writer(
        destination,
        schema,
        dictionary_columns=(
            "source_era",
            "district_code",
            "source_system",
            "street_type",
            "locality",
            "postcode",
            "zoning_code",
            "nature_code",
            "area_unit",
            "match_tier",
            "geographic_precision",
            "quality_warnings",
        ),
    )
    row_count = 0
    try:
        for source_year, sales in partitions:
            rows: list[dict[str, Any]] = []
            for sale in sales:
                rows.append(_parquet_row(sale, source_year=source_year))
                row_count += 1
                if on_record is not None:
                    on_record()
                if len(rows) >= batch_rows:
                    write_row_group(writer, rows, schema)
                    rows.clear()
            # A partition boundary starts a new row group and retains source ordering evidence.
            if rows:
                write_row_group(writer, rows, schema)
    finally:
        writer.close()
    if row_count == 0:
        destination.unlink(missing_ok=True)
        raise ValueError("canonical PSI artifact must not be empty")
    return row_count


def _parquet_row(sale: PsiSale, *, source_year: int) -> dict[str, Any]:
    if not 1990 <= source_year <= POSTGRES_INTEGER_MAX:
        raise ValueError("PSI source partition year is outside its registered range")
    warnings: set[str] = set()
    first = _address_number(sale.street_number_first, warnings)
    last = _address_number(sale.street_number_last, warnings)
    if first is None and _derived_number_is_out_of_range(sale.house_number, last=False):
        warnings.add(PSI_ADDRESS_NUMBER_OUT_OF_RANGE)
    if last is None and _derived_number_is_out_of_range(sale.house_number, last=True):
        warnings.add(PSI_ADDRESS_NUMBER_OUT_OF_RANGE)
    postcode = _optional_text(sale.postcode)
    if postcode is not None and (len(postcode) != 4 or not postcode.isdigit()):
        if len(postcode) < 4 and postcode.isdigit():
            postcode = None
        else:
            raise ValueError("PSI postcode must contain four digits")
    if sale.price_aud is not None and not 0 <= sale.price_aud <= POSTGRES_BIGINT_MAX:
        raise ValueError("PSI price exceeds PostgreSQL BIGINT range")
    result: dict[str, Any] = {
        "source_business_key": _required_text(sale.source_business_key),
        "source_revision": 1,
        "source_era": _required_text(sale.source_era),
        "source_partition_year": source_year,
        "district_code": _optional_text(sale.district_code),
        "property_id": _optional_text(sale.property_id),
        "dealing_id": _optional_text(sale.dealing_id),
        "source_system": _optional_text(sale.source_system),
        "valuation_number": _optional_text(sale.valuation_number),
        "source_downloaded_at": sale.source_downloaded_at,
        "property_name": _optional_text(sale.property_name),
        "unit_number": _optional_upper(sale.unit_number),
        "house_number": _optional_text(sale.house_number),
        "street_number_first": first,
        "street_number_last": last,
        "street_number_suffix": _optional_upper(sale.street_number_suffix),
        "street_name": _optional_text(sale.street_name),
        "street_name_normalised": _optional_upper(sale.street_name_normalised),
        "street_type": _optional_upper(sale.street_type),
        "locality": _optional_upper(sale.locality),
        "postcode": postcode,
        "land_description": _optional_text(sale.land_description, maximum_length=1_000),
        "dimensions": _optional_text(sale.dimensions),
        "zoning_code": _optional_text(sale.zoning_code),
        "nature_code": _optional_text(sale.nature_code),
        "primary_purpose": _optional_text(sale.primary_purpose),
        "strata_lot_number": _optional_text(sale.strata_lot_number),
        "component_code": _optional_text(sale.component_code),
        "sale_code": _optional_text(sale.sale_code),
        "interest_of_sale": _optional_text(sale.interest_of_sale),
        "contract_date": sale.contract_date,
        "settlement_date": sale.settlement_date,
        "price_aud": sale.price_aud,
        "area_original": _decimal_text(sale.area_original),
        "area_unit": _optional_text(sale.area_unit),
        "area_square_metres": _decimal_text(sale.area_square_metres),
        "property_ref": None,
        "match_tier": "MISS",
        "match_confidence": "0",
        "geographic_precision": "unmatched",
    }
    facts = {
        key: _canonical_value(value)
        for key, value in result.items()
        if key not in {"source_revision", "source_partition_year"}
    }
    return {
        **result,
        "source_row_sha256": canonical_row_sha256(facts),
        "quality_warnings": sorted(warnings) or None,
    }


def _required_text(value: object, *, maximum_length: int = 500) -> str:
    result = _optional_text(value, maximum_length=maximum_length)
    if result is None:
        raise ValueError("PSI required text must not be blank")
    return result


def _optional_text(value: object, *, maximum_length: int = 500) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str) or len(value.strip()) > maximum_length:
        raise ValueError(f"PSI text must contain at most {maximum_length} characters")
    return value.strip()


def _optional_upper(value: object) -> str | None:
    result = _optional_text(value)
    return result.upper() if result is not None else None


def _address_number(value: int | None, warnings: set[str]) -> int | None:
    if value is None:
        return None
    if value < 0:
        raise ValueError("PSI address number must not be negative")
    if value > POSTGRES_INTEGER_MAX:
        warnings.add(PSI_ADDRESS_NUMBER_OUT_OF_RANGE)
        return None
    return value


def _derived_number_is_out_of_range(value: object, *, last: bool) -> bool:
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


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if not value.is_finite():
        raise ValueError("PSI decimal values must be finite")
    return str(value)


def _canonical_value(value: object) -> object:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
