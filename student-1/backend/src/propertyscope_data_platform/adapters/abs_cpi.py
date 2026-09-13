"""Strict, bounded ABS CPI 2.0.0 series acquisition and projection."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlsplit

import httpx

_BASE_URL = "https://data.api.abs.gov.au/rest/data/ABS,CPI,2.0.0"
_MAX_CPI_BYTES = 2 * 1024 * 1024
_BASE_PERIOD_CODE = "25"
_BASE_PERIOD = "Sep 2025 = 100.0"
_REQUIRED_COLUMNS = {
    "STRUCTURE",
    "STRUCTURE_ID",
    "MEASURE",
    "INDEX",
    "TSEST",
    "REGION",
    "FREQ",
    "TIME_PERIOD",
    "OBS_VALUE",
    "UNIT_MEASURE",
    "BASE_PERIOD",
    "Reference Base Period",
}


@dataclass(frozen=True, slots=True)
class CpiSeries:
    logical_key: str
    region_code: str
    region_name: str
    frequency_code: str
    frequency_name: str

    @property
    def url(self) -> str:
        key = f"1.10001.10.{self.region_code}.{self.frequency_code}"
        return f"{_BASE_URL}/{key}?format=csvfilewithlabels"


CPI_SERIES = (
    CpiSeries("cpi-monthly-sydney", "1", "Sydney", "M", "Monthly"),
    CpiSeries("cpi-monthly-australia", "50", "Australia", "M", "Monthly"),
    CpiSeries("cpi-quarterly-sydney", "1", "Sydney", "Q", "Quarterly"),
    CpiSeries("cpi-quarterly-australia", "50", "Australia", "Q", "Quarterly"),
)
_SERIES_BY_KEY = {item.logical_key: item for item in CPI_SERIES}


def discover_abs_cpi(client: httpx.Client) -> list[dict[str, Any]]:
    """Discover four exact All groups/original CPI series and fence their bytes."""
    objects: list[dict[str, Any]] = []
    for series in CPI_SERIES:
        content = _read_cpi_bytes(client, series.url)
        rows = parse_abs_cpi_csv(content, series)
        periods = [str(row["period"]) for row in rows]
        objects.append(
            {
                "logical_key": series.logical_key,
                "url": series.url,
                "media_type": "text/csv",
                "complete": True,
                "count": len(rows),
                "expected_bytes": len(content),
                "expected_sha256": hashlib.sha256(content).hexdigest(),
                "edition": "ABS:CPI(2.0.0)",
                "source_crs": "non-spatial",
                "output_crs": None,
                "schema": sorted(_REQUIRED_COLUMNS),
                "coverage": {
                    "kind": "complete-series",
                    "region": series.region_name,
                    "frequency": series.frequency_name,
                    "first_period": min(periods),
                    "last_period": max(periods),
                },
                "reference_basis": _BASE_PERIOD,
                "publisher": "Australian Bureau of Statistics",
                "licence": "Creative Commons Attribution 4.0 International",
            }
        )
    return sorted(objects, key=lambda item: str(item["logical_key"]))


def iter_abs_cpi_records(
    client: httpx.Client, objects: list[dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    """Fetch and project discovered CPI series, rejecting drift or partial data."""
    keys = sorted(str(item.get("logical_key")) for item in objects)
    if keys != sorted(_SERIES_BY_KEY):
        raise ValueError("ABS CPI acquisition requires all four registered series")
    for descriptor in sorted(objects, key=lambda item: str(item["logical_key"])):
        key = str(descriptor["logical_key"])
        series = _SERIES_BY_KEY[key]
        if descriptor.get("url") != series.url or descriptor.get("complete") is not True:
            raise ValueError("ABS CPI source descriptor is outside the registered scope")
        content = _read_cpi_bytes(client, series.url)
        digest = hashlib.sha256(content).hexdigest()
        if digest != descriptor.get("expected_sha256"):
            raise ValueError("ABS CPI source changed after discovery")
        rows = parse_abs_cpi_csv(content, series)
        if len(rows) != descriptor.get("count"):
            raise ValueError("ABS CPI acquisition is incomplete")
        for row in rows:
            period = str(row["period"])
            yield {
                "record_id": f"{series.logical_key}:{period}",
                "layer": "abs-cpi",
                "name": f"All groups CPI - {series.region_name}",
                "geometry": None,
                "attributes": row,
                "source_url": series.url,
                "source_crs": "non-spatial",
                "source_updated_at": None,
                "valid_from": _period_start(period),
                "valid_to": None,
            }


def parse_abs_cpi_csv(content: bytes, series: CpiSeries) -> list[dict[str, Any]]:
    """Parse one exact ABS series while preserving frequency and reference basis."""
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("ABS CPI response is not UTF-8 CSV") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    headers = set(reader.fieldnames or ())
    if not _REQUIRED_COLUMNS.issubset(headers):
        raise ValueError("ABS CPI CSV schema does not match the registered series")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row_number, source in enumerate(reader, start=2):
        expected = {
            "STRUCTURE": "DATAFLOW",
            "STRUCTURE_ID": "ABS:CPI(2.0.0)",
            "MEASURE": "1",
            "INDEX": "10001",
            "TSEST": "10",
            "REGION": series.region_code,
            "FREQ": series.frequency_code,
            "UNIT_MEASURE": "IN",
            "BASE_PERIOD": _BASE_PERIOD_CODE,
            "Reference Base Period": _BASE_PERIOD,
        }
        if any(source.get(field) != value for field, value in expected.items()):
            raise ValueError(f"ABS CPI row {row_number} is outside the registered series")
        period = (source.get("TIME_PERIOD") or "").strip()
        pattern = r"\d{4}-\d{2}" if series.frequency_code == "M" else r"\d{4}-Q[1-4]"
        if not re.fullmatch(pattern, period):
            raise ValueError(f"ABS CPI row {row_number} has an invalid period")
        if period in seen:
            raise ValueError(f"ABS CPI row {row_number} duplicates period {period}")
        seen.add(period)
        try:
            value = Decimal((source.get("OBS_VALUE") or "").strip())
        except InvalidOperation as exc:
            raise ValueError(f"ABS CPI row {row_number} has an invalid index value") from exc
        if not value.is_finite() or value <= 0:
            raise ValueError(f"ABS CPI row {row_number} has an invalid index value")
        rows.append(
            {
                "dataflow": "ABS:CPI(2.0.0)",
                "measure_code": "1",
                "measure": source.get("Measure") or "Index numbers",
                "index_code": "10001",
                "index": source.get("Index") or "All groups CPI",
                "adjustment_code": "10",
                "adjustment": source.get("Adjustment Type") or "Original",
                "region_code": series.region_code,
                "region": source.get("Region") or series.region_name,
                "frequency_code": series.frequency_code,
                "frequency": source.get("Frequency") or series.frequency_name,
                "period": period,
                "index_value": float(value),
                "unit_code": "IN",
                "unit": source.get("Unit of Measure") or "Index Numbers",
                "observation_status": (source.get("OBS_STATUS") or "").strip() or None,
                "reference_basis_code": _BASE_PERIOD_CODE,
                "reference_basis": _BASE_PERIOD,
            }
        )
    if not rows:
        raise ValueError("ABS CPI series is empty")
    return sorted(rows, key=lambda item: str(item["period"]))


def _read_cpi_bytes(client: httpx.Client, url: str) -> bytes:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "data.api.abs.gov.au"
        or parsed.port not in (None, 443)
        or parsed.username
        or parsed.password
        or url not in {series.url for series in CPI_SERIES}
    ):
        raise ValueError("ABS CPI URL is outside the registered source allowlist")
    with client.stream("GET", url, timeout=120, follow_redirects=False) as response:
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > _MAX_CPI_BYTES:
                raise ValueError("ABS CPI response exceeds the registered size bound")
    return bytes(content)


def _period_start(period: str) -> str:
    if "-Q" not in period:
        return f"{period}-01"
    year, quarter = period.split("-Q", 1)
    month = 1 + (int(quarter) - 1) * 3
    return f"{year}-{month:02d}-01"
