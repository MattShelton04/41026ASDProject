"""G-NAF archive member validation and deterministic selected-geocode policy."""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path
from tempfile import TemporaryDirectory
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
    maximum_records: int | None,
    localities: frozenset[str] | None = None,
    maximum_member_bytes: int = 1_000_000_000,
    maximum_scanned_rows: int = 7_000_000,
) -> tuple[GnafAddress, ...]:
    """Return a selected slice; source-scale callers should consume the streaming iterator."""
    return tuple(
        iter_gnaf_archive_path(
            path,
            declared_crs=declared_crs,
            maximum_records=maximum_records,
            localities=localities,
            maximum_member_bytes=maximum_member_bytes,
            maximum_scanned_rows=maximum_scanned_rows,
        )
    )


def iter_gnaf_archive_path(
    path: Path,
    *,
    declared_crs: str,
    maximum_records: int | None = None,
    capacity_ceiling: int = 6_500_000,
    localities: frozenset[str] | None = None,
    maximum_member_bytes: int = 1_000_000_000,
    maximum_scanned_rows: int = 7_000_000,
    progress: Callable[[int], None] | None = None,
) -> Iterator[GnafAddress]:
    """Stream a complete NSW generation, spilling the large geocode join to local SQLite."""
    if maximum_records is not None and maximum_records < 1:
        raise ValueError("G-NAF maximum_records must be positive")
    if capacity_ceiling < 1:
        raise ValueError("G-NAF capacity ceiling must be positive")
    with ZipFile(path) as archive:
        manifest = inspect_gnaf_archive(archive, declared_crs=declared_crs)
        members = {suffix: _member(manifest.members, suffix) for suffix in REQUIRED_MEMBER_SUFFIXES}
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
        streets = {
            row["STREET_LOCALITY_PID"]: row
            for row in _psv_rows(archive, members["NSW_STREET_LOCALITY_PSV.PSV"])
            if row.get("LOCALITY_PID") in locality_rows
        }
        if not streets:
            raise ValueError("G-NAF scope matched no street localities")
        source_crs = 7844 if declared_crs == "GDA2020" else 4283
        with TemporaryDirectory(prefix="propertyscope-gnaf-") as directory:
            database = sqlite3.connect(Path(directory) / "geocodes.sqlite3")
            try:
                database.execute("PRAGMA journal_mode=OFF")
                database.execute("PRAGMA synchronous=OFF")
                database.execute(
                    "CREATE TABLE geocode (pid TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                    "latitude TEXT NOT NULL, longitude TEXT NOT NULL) WITHOUT ROWID"
                )
                batch: list[tuple[str, str, str, str]] = []
                for index, row in enumerate(
                    _psv_rows(archive, members["NSW_ADDRESS_DEFAULT_GEOCODE_PSV.PSV"])
                ):
                    if index >= maximum_scanned_rows:
                        raise ValueError(
                            "G-NAF geocode scan exceeds the registered capacity ceiling"
                        )
                    if progress is not None and index % 10_000 == 0:
                        progress(10_000)
                    pid = row.get("ADDRESS_DETAIL_PID", "")
                    if not pid or not _coordinate(row):
                        continue
                    batch.append(
                        (
                            pid,
                            row.get("GEOCODE_TYPE_CODE") or "UNKNOWN",
                            row["LATITUDE"],
                            row["LONGITUDE"],
                        )
                    )
                    if len(batch) >= 10_000:
                        database.executemany(
                            "INSERT OR REPLACE INTO geocode VALUES (?,?,?,?)", batch
                        )
                        batch.clear()
                if batch:
                    database.executemany("INSERT OR REPLACE INTO geocode VALUES (?,?,?,?)", batch)
                database.commit()
                emitted = 0
                address_batch: list[dict[str, str]] = []
                for index, row in enumerate(
                    _psv_rows(archive, members["NSW_ADDRESS_DETAIL_PSV.PSV"])
                ):
                    if index >= maximum_scanned_rows:
                        raise ValueError(
                            "G-NAF address scan exceeds the registered capacity ceiling"
                        )
                    if progress is not None and index % 10_000 == 0:
                        progress(10_000)
                    if _valid_address_row(row, locality_rows, streets):
                        address_batch.append(row)
                    if len(address_batch) >= 500:
                        for item in _joined_addresses(
                            database, address_batch, locality_rows, streets, source_crs
                        ):
                            if maximum_records is not None and emitted >= maximum_records:
                                return
                            if emitted >= capacity_ceiling:
                                raise ValueError(
                                    "G-NAF canonical output exceeds the registered capacity ceiling"
                                )
                            emitted += 1
                            yield item
                        address_batch.clear()
                for item in _joined_addresses(
                    database, address_batch, locality_rows, streets, source_crs
                ):
                    if maximum_records is not None and emitted >= maximum_records:
                        return
                    if emitted >= capacity_ceiling:
                        raise ValueError(
                            "G-NAF canonical output exceeds the registered capacity ceiling"
                        )
                    emitted += 1
                    yield item
                if emitted == 0:
                    raise ValueError("G-NAF scope has no addresses with valid default geocodes")
            finally:
                database.close()


def _valid_address_row(
    row: dict[str, str],
    localities: dict[str, dict[str, str]],
    streets: dict[str, dict[str, str]],
) -> bool:
    postcode = row.get("POSTCODE", "")
    return (
        row.get("LOCALITY_PID") in localities
        and row.get("STREET_LOCALITY_PID") in streets
        and bool(row.get("ADDRESS_DETAIL_PID"))
        and len(postcode) == 4
        and postcode.isdigit()
    )


def _joined_addresses(
    database: sqlite3.Connection,
    addresses: list[dict[str, str]],
    localities: dict[str, dict[str, str]],
    streets: dict[str, dict[str, str]],
    source_crs: int,
) -> Iterator[GnafAddress]:
    if not addresses:
        return
    identifiers = [row["ADDRESS_DETAIL_PID"] for row in addresses]
    placeholders = ",".join("?" for _ in identifiers)
    geocodes = {
        str(row[0]): {
            "GEOCODE_TYPE_CODE": str(row[1]),
            "LATITUDE": str(row[2]),
            "LONGITUDE": str(row[3]),
        }
        for row in database.execute(
            f"SELECT pid,kind,latitude,longitude FROM geocode WHERE pid IN ({placeholders})",
            identifiers,
        )
    }
    for address in addresses:
        geocode = geocodes.get(address["ADDRESS_DETAIL_PID"])
        if geocode is None:
            continue
        yield _canonical_address(
            address,
            streets[address["STREET_LOCALITY_PID"]],
            localities[address["LOCALITY_PID"]],
            geocode,
            source_crs,
        )


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
    unit = (
        "".join(
            filter(
                None,
                (
                    address.get("FLAT_NUMBER_PREFIX"),
                    address.get("FLAT_NUMBER"),
                    address.get("FLAT_NUMBER_SUFFIX"),
                ),
            )
        )
        or None
    )
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
        return -45 <= latitude <= -9 and 110 <= longitude <= 160
    except (KeyError, ValueError):
        return False
