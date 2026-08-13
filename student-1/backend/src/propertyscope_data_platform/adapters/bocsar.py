"""BOCSAR wide CSV parsing into sparse observations and explicit coverage."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from zipfile import BadZipFile, ZipFile

MONTH_PATTERNS = ("%b %Y", "%B %Y", "%Y-%m")


@dataclass(frozen=True, slots=True)
class CrimeObservation:
    geography_kind: str
    geography_value: str
    category_key: str
    offence_label: str
    subcategory_label: str
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
    content: bytes,
    *,
    geography_kind: str,
    maximum_rows: int,
    geography_values: frozenset[str] | None = None,
    start_month: date | None = None,
    end_month: date | None = None,
    maximum_records: int | None = None,
) -> tuple[tuple[CrimeObservation, ...], tuple[CrimeCoverage, ...]]:
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
    headers = tuple(reader.fieldnames or ())
    if len(headers) < 4:
        raise ValueError("BOCSAR source has no month columns")
    month_headers = [
        (header, month)
        for header in headers[3:]
        if (month := _month(header))
        and (start_month is None or month >= start_month)
        and (end_month is None or month <= end_month)
    ]
    if not month_headers:
        raise ValueError("BOCSAR source has no months inside the requested range")
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
        if geography_values is not None and geography not in geography_values:
            continue
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
                    CrimeObservation(
                        geography_kind,
                        geography,
                        category_key,
                        offence,
                        subcategory,
                        month,
                        count,
                    )
                )
        coverage.append(CrimeCoverage(geography_kind, geography, category_key, tuple(months)))
        if maximum_records is not None and len(observations) + len(coverage) > maximum_records:
            raise ValueError("BOCSAR canonical output exceeds the requested record limit")
    if not coverage:
        raise ValueError("BOCSAR source is empty")
    return tuple(observations), tuple(coverage)


def parse_bocsar_archive(
    content: bytes,
    *,
    geography_kind: str,
    maximum_rows: int,
    geography_values: frozenset[str] | None = None,
    start_month: date | None = None,
    end_month: date | None = None,
    maximum_records: int | None = None,
    maximum_uncompressed_bytes: int = 100_000_000,
) -> tuple[tuple[CrimeObservation, ...], tuple[CrimeCoverage, ...]]:
    """Validate a registered BOCSAR ZIP and parse its single wide CSV."""
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1 or not members[0].filename.lower().endswith(".csv"):
                raise ValueError("BOCSAR archive must contain exactly one CSV")
            member = members[0]
            parts = member.filename.replace("\\", "/").split("/")
            if member.filename.startswith("/") or ".." in parts:
                raise ValueError("BOCSAR archive contains an unsafe member path")
            if member.file_size > maximum_uncompressed_bytes:
                raise ValueError("BOCSAR archive exceeds the uncompressed byte limit")
            return parse_bocsar_csv(
                archive.read(member),
                geography_kind=geography_kind,
                maximum_rows=maximum_rows,
                geography_values=geography_values,
                start_month=start_month,
                end_month=end_month,
                maximum_records=maximum_records,
            )
    except BadZipFile as exc:
        raise ValueError("BOCSAR source is not a valid ZIP archive") from exc


def _month(value: str) -> date:
    cleaned = value.strip()
    for pattern in MONTH_PATTERNS:
        try:
            parsed = datetime.strptime(cleaned, pattern)
            return date(parsed.year, parsed.month, 1)
        except ValueError:
            continue
    raise ValueError(f"invalid BOCSAR month heading: {cleaned}")
