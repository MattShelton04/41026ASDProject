"""BOCSAR wide CSV parsing into sparse observations and explicit coverage."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime

MONTH_PATTERNS = ("%b %Y", "%B %Y", "%Y-%m")


@dataclass(frozen=True, slots=True)
class CrimeObservation:
    geography_kind: str
    geography_value: str
    category_key: str
    month: date
    count: int


@dataclass(frozen=True, slots=True)
class CrimeCoverage:
    geography_kind: str
    geography_value: str
    category_key: str
    observed_months: tuple[date, ...]
    blank_means_observed_zero: bool = True


def parse_bocsar_csv(
    content: bytes, *, geography_kind: str, maximum_rows: int
) -> tuple[tuple[CrimeObservation, ...], tuple[CrimeCoverage, ...]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
    headers = tuple(reader.fieldnames or ())
    if len(headers) < 4:
        raise ValueError("BOCSAR source has no month columns")
    month_headers = [(header, _month(header)) for header in headers[3:]]
    observations: list[CrimeObservation] = []
    coverage: list[CrimeCoverage] = []
    for index, row in enumerate(reader):
        if index >= maximum_rows:
            raise ValueError("BOCSAR source exceeds registered row limit")
        geography = str(row[headers[0]]).strip()
        offence = str(row[headers[1]]).strip()
        subcategory = str(row[headers[2]]).strip()
        if geography_kind == "postcode":
            geography = geography.zfill(4)
        category_key = re.sub(r"[^a-z0-9]+", "-", f"{offence}-{subcategory}".lower()).strip("-")
        months: list[date] = []
        for header, month in month_headers:
            months.append(month)
            raw = str(row.get(header, "")).strip().replace(",", "")
            count = 0 if raw == "" else int(raw)
            if count < 0:
                raise ValueError("BOCSAR count must not be negative")
            if count:
                observations.append(
                    CrimeObservation(geography_kind, geography, category_key, month, count)
                )
        coverage.append(CrimeCoverage(geography_kind, geography, category_key, tuple(months)))
    if not coverage:
        raise ValueError("BOCSAR source is empty")
    return tuple(observations), tuple(coverage)


def _month(value: str) -> date:
    cleaned = value.strip()
    for pattern in MONTH_PATTERNS:
        try:
            parsed = datetime.strptime(cleaned, pattern)
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            continue
    raise ValueError(f"invalid BOCSAR month heading: {cleaned}")
