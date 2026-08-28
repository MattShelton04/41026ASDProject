"""Pure NSW government-school master parser."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SchoolRecord:
    school_code: str
    school_name: str
    school_type: str
    status: str
    locality_original: str
    locality_normalised: str
    lga_name: str | None
    latitude: float
    longitude: float


def parse_schools_csv(content: bytes) -> tuple[SchoolRecord, ...]:
    """Parse source header aliases while preserving original locality evidence."""
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
    rows: list[SchoolRecord] = []
    seen: set[str] = set()
    for source in reader:
        code = _field(source, "School_code", "school_code", "School Code")
        if code in seen:
            raise ValueError("school_code must be unique")
        seen.add(code)
        locality = _optional(source, "Town_suburb", "locality", "Town/Suburb") or "NOT PUBLISHED"
        latitude = float(_field(source, "Latitude", "latitude"))
        longitude = float(_field(source, "Longitude", "longitude"))
        # Include NSW-administered Lord Howe Island (around 159E) while still
        # rejecting coordinates outside the state's published school footprint.
        if not -38 <= latitude <= -27 or not 140 <= longitude <= 160:
            raise ValueError("school coordinates fall outside NSW bounds")
        rows.append(
            SchoolRecord(
                school_code=code,
                school_name=_field(source, "School_name", "school_name"),
                school_type=_field(source, "School_type", "school_type", "Level_of_schooling"),
                # The current NSW master extract contains only operating schools and
                # no longer publishes the legacy Operational_status column.
                status=_optional(source, "Operational_status", "status") or "Open",
                locality_original=locality,
                locality_normalised=" ".join(locality.upper().split()),
                lga_name=_optional(source, "LGA", "lga_name"),
                latitude=latitude,
                longitude=longitude,
            )
        )
    if not rows:
        raise ValueError("schools source is empty")
    return tuple(rows)


def _field(row: dict[str, str], *names: str) -> str:
    value = _optional(row, *names)
    if value is None:
        raise ValueError(f"required schools field is missing: {names[0]}")
    return value


def _optional(row: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = row.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None
