"""G-NAF archive member validation and deterministic selected-geocode policy."""

from __future__ import annotations

import csv
from collections.abc import Iterator
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

REQUIRED_MEMBER_SUFFIXES = (
    "NSW_ADDRESS_DETAIL_PSV.PSV",
    "NSW_ADDRESS_DEFAULT_GEOCODE_PSV.PSV",
    "NSW_LOCALITY_PSV.PSV",
    "NSW_STREET_LOCALITY_PSV.PSV",
)
GEOCODE_PREFERENCE = {"PC": 0, "PAP": 1, "GAP": 2, "GNAF": 3, "LOCALITY": 20}


@dataclass(frozen=True, slots=True)
class GnafMemberManifest:
    members: tuple[str, ...]
    coordinate_reference_system: str


@dataclass(frozen=True, slots=True)
class GnafAddress:
    gnaf_pid: str
    address_display: str
    flat_type: str | None
    unit_number: str | None
    street_number_first: int | None
    street_number_suffix: str | None
    street_number_last: int | None
    street_name: str
    street_type: str | None
    locality: str
    postcode: str
    source_status: str
    geocode_type: str
    source_crs: int
    latitude: float
    longitude: float


def inspect_gnaf_archive(
    archive: ZipFile, *, maximum_members: int = 1000, declared_crs: str | None = None
) -> GnafMemberManifest:
    names = tuple(sorted(info.filename for info in archive.infolist() if not info.is_dir()))
    if len(names) > maximum_members:
        raise ValueError("G-NAF archive exceeds registered member limit")
    for name in names:
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
            raise ValueError("G-NAF archive contains an unsafe member path")
    for suffix in REQUIRED_MEMBER_SUFFIXES:
        matches = [name for name in names if name.upper().endswith(suffix)]
        if len(matches) != 1:
            raise ValueError(f"G-NAF archive requires exactly one {suffix} member")
    upper_names = "\n".join(names).upper()
    inferred_crs = (
        "GDA2020" if "GDA2020" in upper_names else "GDA94" if "GDA94" in upper_names else "UNKNOWN"
    )
    crs = declared_crs or inferred_crs
    if crs not in {"GDA94", "GDA2020"}:
        raise ValueError("G-NAF archive coordinate reference system is not declared")
    return GnafMemberManifest(names, crs)


def parse_gnaf_archive_path(
    path: Path,
    *,
    declared_crs: str,
    maximum_records: int,
    localities: frozenset[str] | None = None,
    maximum_member_bytes: int = 1_000_000_000,
    maximum_scanned_rows: int = 7_000_000,
) -> tuple[GnafAddress, ...]:
    """Stream and join a bounded NSW address slice without extracting the bulk archive."""
    if maximum_records < 1:
        raise ValueError("G-NAF maximum_records must be positive")
    with ZipFile(path) as archive:
        manifest = inspect_gnaf_archive(archive, declared_crs=declared_crs)
        members = {
            suffix: _member(manifest.members, suffix) for suffix in REQUIRED_MEMBER_SUFFIXES
        }
        for member in members.values():
            if archive.getinfo(member).file_size > maximum_member_bytes:
                raise ValueError("G-NAF member exceeds the uncompressed byte limit")
        locality_rows = {
            row["LOCALITY_PID"]: row
            for row in _psv_rows(archive, members["NSW_LOCALITY_PSV.PSV"])
            if localities is None or row.get("LOCALITY_NAME", "").upper() in localities
        }
        if not locality_rows:
            raise ValueError("G-NAF scope matched no NSW localities")
        addresses: dict[str, dict[str, str]] = {}
        street_ids: set[str] = set()
        for index, row in enumerate(_psv_rows(archive, members["NSW_ADDRESS_DETAIL_PSV.PSV"])):
            if index >= maximum_scanned_rows:
                raise ValueError("G-NAF address scan exceeds the registered row limit")
            if row.get("LOCALITY_PID") not in locality_rows:
                continue
            postcode = row.get("POSTCODE", "")
            if len(postcode) != 4 or not postcode.isdigit():
                continue
            pid = row.get("ADDRESS_DETAIL_PID", "")
            street_id = row.get("STREET_LOCALITY_PID", "")
            if not pid or not street_id:
                continue
            addresses[pid] = row
            street_ids.add(street_id)
            if len(addresses) >= maximum_records:
                break
        if not addresses:
            raise ValueError("G-NAF scope matched no valid address details")
        streets = {
            row["STREET_LOCALITY_PID"]: row
            for row in _psv_rows(archive, members["NSW_STREET_LOCALITY_PSV.PSV"])
            if row.get("STREET_LOCALITY_PID") in street_ids
        }
        geocodes: dict[str, dict[str, str]] = {}
        for index, row in enumerate(
            _psv_rows(archive, members["NSW_ADDRESS_DEFAULT_GEOCODE_PSV.PSV"])
        ):
            if index >= maximum_scanned_rows:
                raise ValueError("G-NAF geocode scan exceeds the registered row limit")
            pid = row.get("ADDRESS_DETAIL_PID", "")
            if pid in addresses:
                geocodes[pid] = row
                if len(geocodes) == len(addresses):
                    break
        source_crs = 7844 if declared_crs == "GDA2020" else 4283
        result: list[GnafAddress] = []
        for pid, address in addresses.items():
            locality = locality_rows.get(address.get("LOCALITY_PID", ""))
            street = streets.get(address.get("STREET_LOCALITY_PID", ""))
            geocode = geocodes.get(pid)
            if locality is None or street is None or geocode is None:
                continue
            coordinate = select_geocode((geocode,))
            if coordinate is None:
                continue
            result.append(_canonical_address(address, street, locality, coordinate, source_crs))
        if not result:
            raise ValueError("G-NAF scope has no addresses with valid default geocodes")
        return tuple(result)


def _member(names: tuple[str, ...], suffix: str) -> str:
    return next(name for name in names if name.upper().endswith(suffix))


def _psv_rows(archive: ZipFile, member: str) -> Iterator[dict[str, str]]:
    with archive.open(member) as raw, TextIOWrapper(raw, encoding="utf-8-sig", newline="") as text:
        yield from csv.DictReader(text, delimiter="|")


def _canonical_address(
    address: dict[str, str],
    street: dict[str, str],
    locality: dict[str, str],
    geocode: dict[str, str],
    source_crs: int,
) -> GnafAddress:
    flat_type = address.get("FLAT_TYPE_CODE") or None
    unit = "".join(
        filter(
            None,
            (
                address.get("FLAT_NUMBER_PREFIX"),
                address.get("FLAT_NUMBER"),
                address.get("FLAT_NUMBER_SUFFIX"),
            ),
        )
    ) or None
    number_first = _integer(address.get("NUMBER_FIRST"))
    number_last = _integer(address.get("NUMBER_LAST"))
    street_name = street.get("STREET_NAME", "").strip()
    street_type = street.get("STREET_TYPE_CODE") or None
    number = "" if number_first is None else str(number_first)
    number += address.get("NUMBER_FIRST_SUFFIX", "")
    if number_last is not None:
        number += f"-{number_last}{address.get('NUMBER_LAST_SUFFIX', '')}"
    unit_display = f"{flat_type or 'UNIT'} {unit}/" if unit else ""
    street_display = " ".join(filter(None, (street_name, street_type)))
    locality_name = locality["LOCALITY_NAME"].upper()
    display = f"{unit_display}{number} {street_display}, {locality_name} NSW {address['POSTCODE']}"
    return GnafAddress(
        address["ADDRESS_DETAIL_PID"],
        " ".join(display.split()),
        flat_type,
        unit,
        number_first,
        address.get("NUMBER_FIRST_SUFFIX") or None,
        number_last,
        street_name,
        street_type,
        locality_name,
        address["POSTCODE"],
        "RETIRED" if address.get("DATE_RETIRED") else "CURRENT",
        geocode.get("GEOCODE_TYPE_CODE") or "UNKNOWN",
        source_crs,
        float(geocode["LATITUDE"]),
        float(geocode["LONGITUDE"]),
    )


def _integer(value: str | None) -> int | None:
    try:
        return int(value) if value else None
    except ValueError:
        return None


def select_geocode(candidates: tuple[dict[str, str], ...]) -> dict[str, str] | None:
    """Choose one geocode by registered type preference and stable source identifier."""
    valid = [candidate for candidate in candidates if _coordinate(candidate)]
    if not valid:
        return None
    return min(
        valid,
        key=lambda item: (
            GEOCODE_PREFERENCE.get(item.get("GEOCODE_TYPE_CODE", "").upper(), 100),
            item.get("GEOCODE_PID", ""),
        ),
    )


def _coordinate(candidate: dict[str, str]) -> bool:
    try:
        latitude = float(candidate["LATITUDE"])
        longitude = float(candidate["LONGITUDE"])
        return -45 <= latitude <= -9 and 110 <= longitude <= 155
    except (KeyError, ValueError):
        return False
