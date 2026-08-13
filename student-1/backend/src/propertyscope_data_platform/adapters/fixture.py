"""Strict parser for the deterministic synthetic property snapshot."""

from __future__ import annotations

import csv
import io
from uuid import UUID

from pydantic import Field

from ..domain import Coordinates, DomainModel

_HEADERS = (
    "property_ref",
    "display_address",
    "locality",
    "state",
    "postcode",
    "latitude",
    "longitude",
    "source_pid",
)


class FixtureProperty(DomainModel):
    property_ref: UUID
    display_address: str = Field(min_length=1, max_length=500)
    locality: str = Field(min_length=1, max_length=100)
    state: str = Field(pattern=r"^NSW$")
    postcode: str = Field(pattern=r"^\d{4}$")
    coordinates: Coordinates
    source_pid: str = Field(min_length=1, max_length=100)


def parse_property_fixture(content: bytes, *, maximum_rows: int) -> tuple[FixtureProperty, ...]:
    """Parse bounded UTF-8 CSV without filesystem, network, or persistence access."""
    if maximum_rows < 1:
        raise ValueError("maximum_rows must be positive")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("property fixture must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != _HEADERS:
        raise ValueError("property fixture headers do not match the registered schema")
    records: list[FixtureProperty] = []
    for row in reader:
        if len(records) >= maximum_rows:
            raise ValueError("property fixture exceeds the registered row limit")
        records.append(
            FixtureProperty(
                property_ref=row["property_ref"],
                display_address=row["display_address"],
                locality=row["locality"],
                state=row["state"],
                postcode=row["postcode"],
                coordinates={"latitude": row["latitude"], "longitude": row["longitude"]},
                source_pid=row["source_pid"],
            )
        )
    if not records:
        raise ValueError("property fixture must contain at least one record")
    source_ids = [record.source_pid for record in records]
    if len(source_ids) != len(set(source_ids)):
        raise ValueError("property fixture source_pid values must be unique")
    return tuple(records)
