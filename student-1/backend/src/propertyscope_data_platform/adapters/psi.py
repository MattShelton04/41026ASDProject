"""NSW Valuer-General PSI source-era helpers and stable source identity."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from io import TextIOWrapper
from pathlib import Path
from shutil import copyfileobj
from tempfile import SpooledTemporaryFile
from typing import IO
from zipfile import BadZipFile, ZipFile, ZipInfo

POSTGRES_INTEGER_MAX = 2_147_483_647


@dataclass(frozen=True, slots=True)
class PsiSale:
    source_business_key: str
    source_era: str
    district_code: str
    property_id: str
    sale_counter: str | None
    contract_date: date | None
    settlement_date: date | None
    price_aud: int | None
    area_original: Decimal | None
    area_unit: str | None
    area_square_metres: Decimal | None
    dealing_id: str | None
    source_system: str | None = None
    valuation_number: str | None = None
    source_downloaded_at: datetime | None = None
    property_name: str | None = None
    unit_number: str | None = None
    house_number: str | None = None
    street_number_first: int | None = None
    street_number_last: int | None = None
    street_number_suffix: str | None = None
    street_name: str | None = None
    street_name_normalised: str | None = None
    street_type: str | None = None
    locality: str | None = None
    postcode: str | None = None
    land_description: str | None = None
    dimensions: str | None = None
    zoning_code: str | None = None
    nature_code: str | None = None
    primary_purpose: str | None = None
    strata_lot_number: str | None = None
    component_code: str | None = None
    sale_code: str | None = None
    interest_of_sale: str | None = None


_SALE_FACT_FIELDS = tuple(
    field.name for field in dataclass_fields(PsiSale) if field.name != "source_business_key"
)


def parse_psi_b_record(fields: tuple[str, ...], *, source_year: int) -> PsiSale:
    """Parse a canonical B record for pre-2001 or post-2001 fixture layouts."""
    if fields and fields[0] == "B":
        fields = fields[1:]
    if source_year < 2001:
        if len(fields) < 9:
            raise ValueError("pre-2001 PSI B record is incomplete")
        district, property_id, contract_raw, price_raw, area_raw, unit, zoning, address, dealing = (
            fields[:9]
        )
        canonical = [
            district,
            property_id,
            contract_raw,
            price_raw,
            area_raw,
            unit,
            zoning,
            address,
            dealing,
        ]
        key = hashlib.sha256(json.dumps(canonical, separators=(",", ":")).encode()).hexdigest()
        return PsiSale(
            key,
            "pre-2001",
            district,
            property_id,
            None,
            _date(contract_raw, ("%d%m%Y", "%Y%m%d")),
            None,
            _integer(price_raw),
            _decimal(area_raw),
            unit or None,
            _square_metres(area_raw, unit),
            dealing or None,
        )
    if len(fields) < 10:
        raise ValueError("post-2001 PSI B record is incomplete")
    (
        district,
        property_id,
        counter,
        contract_raw,
        settlement_raw,
        price_raw,
        area_raw,
        unit,
        _address,
        dealing,
    ) = fields[:10]
    key = f"{district}:{property_id}:{counter}"
    return PsiSale(
        key,
        "post-2001",
        district,
        property_id,
        counter,
        _date(contract_raw, ("%Y%m%d", "%d%m%Y")),
        _date(settlement_raw, ("%Y%m%d", "%d%m%Y")),
        _integer(price_raw),
        _decimal(area_raw),
        unit or None,
        _square_metres(area_raw, unit),
        dealing or None,
    )


def parse_psi_archive(
    content: bytes,
    *,
    source_year: int,
    maximum_records: int | None = None,
    maximum_members: int | None = None,
    maximum_uncompressed_bytes: int | None = None,
) -> tuple[PsiSale, ...]:
    """Parse a registered annual PSI archive across its historical format eras."""
    if maximum_records is not None and maximum_records < 1:
        raise ValueError("PSI maximum_records must be positive")
    return tuple(
        iter_psi_archive(
            content,
            source_year=source_year,
            maximum_records=maximum_records,
            maximum_members=maximum_members,
            maximum_uncompressed_bytes=maximum_uncompressed_bytes,
        )
    )


def iter_psi_archive(
    content: bytes,
    *,
    source_year: int,
    maximum_records: int | None = None,
    maximum_members: int | None = None,
    maximum_uncompressed_bytes: int | None = None,
) -> Iterator[PsiSale]:
    """Yield every unique sale in an annual or standalone weekly PSI archive.

    ``maximum_records`` exists only for deterministic fixtures and targeted previews.
    Production full-data acquisition passes ``None`` and never truncates a partition.
    """
    if maximum_records is not None and maximum_records < 1:
        raise ValueError("PSI maximum_records must be positive")
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            yield from _iter_psi_zip(
                archive,
                source_year=source_year,
                maximum_records=maximum_records,
                maximum_members=maximum_members,
                maximum_uncompressed_bytes=maximum_uncompressed_bytes,
            )
    except BadZipFile as exc:
        raise ValueError("PSI source is not a valid ZIP archive") from exc


def parse_psi_archive_path(
    path: Path,
    *,
    source_year: int,
    maximum_records: int | None = None,
    maximum_members: int | None = None,
    maximum_uncompressed_bytes: int | None = None,
) -> tuple[PsiSale, ...]:
    """Parse a PSI archive from disk without materialising the ZIP in memory."""
    return tuple(
        iter_psi_archive_path(
            path,
            source_year=source_year,
            maximum_records=maximum_records,
            maximum_members=maximum_members,
            maximum_uncompressed_bytes=maximum_uncompressed_bytes,
        )
    )


def iter_psi_archive_path(
    path: Path,
    *,
    source_year: int,
    maximum_records: int | None = None,
    maximum_members: int | None = None,
    maximum_uncompressed_bytes: int | None = None,
) -> Iterator[PsiSale]:
    """Yield every PSI sale from a filesystem archive using streaming reads."""
    if maximum_records is not None and maximum_records < 1:
        raise ValueError("PSI maximum_records must be positive")
    try:
        with ZipFile(path) as archive:
            yield from _iter_psi_zip(
                archive,
                source_year=source_year,
                maximum_records=maximum_records,
                maximum_members=maximum_members,
                maximum_uncompressed_bytes=maximum_uncompressed_bytes,
            )
    except BadZipFile as exc:
        raise ValueError("PSI source is not a valid ZIP archive") from exc


def _iter_psi_zip(
    archive: ZipFile,
    *,
    source_year: int,
    maximum_records: int | None,
    maximum_members: int | None,
    maximum_uncompressed_bytes: int | None,
) -> Iterator[PsiSale]:
    seen: set[tuple[str, str]] = set()
    yielded = 0
    for fields in _source_b_records(
        archive,
        maximum_members=maximum_members,
        maximum_uncompressed_bytes=maximum_uncompressed_bytes,
    ):
        sale = _parse_source_b_record(fields, source_year=source_year)
        if sale is None:
            continue
        identity = (sale.source_business_key, _sale_fingerprint(sale))
        if identity in seen:
            continue
        seen.add(identity)
        yield sale
        yielded += 1
        if maximum_records is not None and yielded >= maximum_records:
            return
    if not seen:
        raise ValueError("PSI archive contains no supported B records")


def _sale_fingerprint(sale: PsiSale) -> str:
    """Distinguish corrected retransmissions while collapsing byte-equivalent source facts."""
    # PsiSale is flat and its fields are immutable. Recursive dataclass deepcopy is
    # unnecessary for a read-only projection performed millions of times per archive.
    payload: dict[str, object] = {}
    for name in _SALE_FACT_FIELDS:
        value = getattr(sale, name)
        payload[name] = str(value) if isinstance(value, (date, Decimal)) else value
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _source_postcode(value: str) -> str | None:
    """Treat publisher placeholders and truncated postcodes as unknown, never guessed."""
    postcode = value.strip()
    if not postcode:
        return None
    if len(postcode) == 4 and postcode.isdigit():
        return postcode
    if len(postcode) < 4 and postcode.isdigit():
        return None
    raise ValueError("PSI source postcode is malformed")


def _source_b_records(
    archive: ZipFile, *, maximum_members: int | None, maximum_uncompressed_bytes: int | None
) -> Iterator[tuple[str, ...]]:
    members = [item for item in archive.infolist() if not item.is_dir()]
    if not members:
        raise ValueError("PSI archive member count is outside the registered limit")
    budget = _ArchiveBudget(maximum_members, maximum_uncompressed_bytes)
    yield from _archive_b_records(archive, members, budget)


@dataclass(slots=True)
class _ArchiveBudget:
    maximum_members: int | None
    maximum_uncompressed_bytes: int | None
    members: int = 0
    uncompressed_bytes: int = 0

    def register(self, members: list[ZipInfo]) -> None:
        """Consume one global member/expanded-byte budget across nested archives."""
        self.members += len(members)
        if self.maximum_members is not None and self.members > self.maximum_members:
            raise ValueError("PSI archive member count is outside the registered limit")
        for member in members:
            parts = member.filename.replace("\\", "/").split("/")
            if member.filename.startswith("/") or ".." in parts:
                raise ValueError("PSI archive contains an unsafe member path")
            if member.filename.lower().endswith(".zip"):
                # The nested ZIP bytes are a container, not expanded source data. Bound
                # each container while counting its leaf members against the global budget.
                if (
                    self.maximum_uncompressed_bytes is not None
                    and member.file_size > self.maximum_uncompressed_bytes
                ):
                    raise ValueError("PSI nested ZIP exceeds the container byte limit")
                continue
            self.uncompressed_bytes += member.file_size
            if (
                self.maximum_uncompressed_bytes is not None
                and self.uncompressed_bytes > self.maximum_uncompressed_bytes
            ):
                raise ValueError("PSI archive exceeds the uncompressed byte limit")


def _archive_b_records(
    archive: ZipFile, members: list[ZipInfo], budget: _ArchiveBudget, *, depth: int = 0
) -> Iterator[tuple[str, ...]]:
    if depth > 4:
        raise ValueError("PSI archive exceeds the nested ZIP depth limit")
    budget.register(members)
    for member in members:
        if member.filename.upper().endswith(".DAT"):
            with archive.open(member) as raw:
                yield from _b_records_from_stream(raw)
        elif member.filename.lower().endswith(".zip"):
            try:
                with SpooledTemporaryFile(max_size=16 * 1024 * 1024) as nested_file:
                    with archive.open(member) as nested_source:
                        copyfileobj(nested_source, nested_file, length=1024 * 1024)
                    nested_file.seek(0)
                    with ZipFile(nested_file) as nested:
                        nested_members = [item for item in nested.infolist() if not item.is_dir()]
                        yield from _archive_b_records(
                            nested, nested_members, budget, depth=depth + 1
                        )
            except BadZipFile as exc:
                raise ValueError("PSI archive contains an invalid nested ZIP") from exc


def _b_records(raw: bytes) -> Iterator[tuple[str, ...]]:
    yield from _b_records_from_stream(io.BytesIO(raw))


def _b_records_from_stream(raw: IO[bytes]) -> Iterator[tuple[str, ...]]:
    text = TextIOWrapper(raw, encoding="latin-1", errors="replace", newline="")
    try:
        for index, line in enumerate(text):
            if index == 0:
                line = line.lstrip("\ufeff")
            fields = tuple(value.strip() for value in line.split(";"))
            if fields and fields[0] == "B":
                yield fields
    finally:
        text.detach()


def _parse_source_b_record(fields: tuple[str, ...], *, source_year: int) -> PsiSale | None:
    padded = fields + ("",) * max(0, 25 - len(fields))
    # The official 2001 annual archive contains legacy ARCHIVE/VALNET rows even
    # though current-format weekly publication also begins in 2001. Detect the
    # wire layout per record: legacy rows carry DD/MM/YYYY at [10], where the
    # current layout carries a postcode. Property IDs are not assumed numeric.
    legacy_layout = source_year < 2001 or "/" in padded[10]
    if legacy_layout:
        district, property_id = padded[1], padded[4]
        if not district and not property_id:
            return None
        canonical = padded[:24]
        key = hashlib.sha256(
            json.dumps((source_year, canonical), separators=(",", ":")).encode()
        ).hexdigest()
        return PsiSale(
            key,
            "pre-2001",
            district,
            property_id,
            None,
            _source_date(padded[10], ("%d/%m/%Y", "%d%m%Y", "%Y%m%d")),
            None,
            _integer(padded[11]),
            _decimal(padded[13]),
            padded[14] or None,
            _square_metres(padded[13], padded[14]),
            None,
            source_system=padded[2] or None,
            valuation_number=padded[3] or None,
            unit_number=padded[5] or None,
            house_number=padded[6] or None,
            street_number_first=_street_number_first(padded[6]),
            street_number_last=_street_number_last(padded[6]),
            street_number_suffix=_street_number_suffix(padded[6]),
            street_name=padded[7] or None,
            street_name_normalised=_street_parts(padded[7])[0],
            street_type=_street_parts(padded[7])[1],
            locality=padded[8] or None,
            postcode=_source_postcode(padded[9]),
            land_description=padded[12] or None,
            dimensions=padded[15] or None,
            zoning_code=padded[17] or None,
            component_code=padded[16] or None,
        )
    district, property_id, counter = padded[1], padded[2], padded[3]
    if not district and not property_id:
        return None
    key = (
        f"{district}:{property_id}:{counter}"
        if counter
        else hashlib.sha256(
            json.dumps((source_year, padded[:25]), separators=(",", ":")).encode()
        ).hexdigest()
    )
    return PsiSale(
        key,
        "post-2001",
        district,
        property_id,
        counter or None,
        _source_date(padded[13], ("%Y%m%d", "%d%m%Y")),
        _source_date(padded[14], ("%Y%m%d", "%d%m%Y")),
        _integer(padded[15]),
        _decimal(padded[11]),
        padded[12] or None,
        _square_metres(padded[11], padded[12]),
        padded[23] or None,
        source_downloaded_at=_source_datetime(padded[4]),
        property_name=padded[5] or None,
        unit_number=padded[6] or None,
        house_number=padded[7] or None,
        street_number_first=_street_number_first(padded[7]),
        street_number_last=_street_number_last(padded[7]),
        street_number_suffix=_street_number_suffix(padded[7]),
        street_name=padded[8] or None,
        street_name_normalised=_street_parts(padded[8])[0],
        street_type=_street_parts(padded[8])[1],
        locality=padded[9] or None,
        postcode=_source_postcode(padded[10]),
        zoning_code=padded[16] or None,
        nature_code=padded[17] or None,
        primary_purpose=padded[18] or None,
        strata_lot_number=padded[19] or None,
        component_code=padded[20] or None,
        sale_code=padded[21] or None,
        interest_of_sale=padded[22] or None,
    )


_STREET_TYPE_ALIASES = {
    "AV": "AV",
    "AVE": "AV",
    "AVENUE": "AV",
    "CL": "CL",
    "CLOSE": "CL",
    "CT": "CT",
    "COURT": "CT",
    "CRES": "CR",
    "CR": "CR",
    "CRESCENT": "CR",
    "DR": "DR",
    "DRIVE": "DR",
    "HWY": "HWY",
    "HIGHWAY": "HWY",
    "LANE": "LANE",
    "LN": "LANE",
    "PDE": "PDE",
    "PARADE": "PDE",
    "PL": "PL",
    "PLACE": "PL",
    "RD": "RD",
    "ROAD": "RD",
    "ST": "ST",
    "STREET": "ST",
    "TCE": "TCE",
    "TERRACE": "TCE",
}


def _street_parts(value: str) -> tuple[str | None, str | None]:
    """Preserve the publisher's street text while deriving conservative match components."""
    tokens = value.strip().upper().split()
    if not tokens:
        return None, None
    street_type = _STREET_TYPE_ALIASES.get(tokens[-1])
    name_tokens = tokens[:-1] if street_type else tokens
    name = " ".join(name_tokens).strip()
    return name or None, street_type


def _street_number_first(value: str) -> int | None:
    digits = ""
    for character in value.strip():
        if character.isdigit():
            digits += character
        elif digits:
            break
    if not digits:
        return None
    number = int(digits)
    # PSI house-number text is a publisher fact and is preserved separately. A
    # handful of source rows contain concatenated identifiers that are not usable
    # address numbers. Do not manufacture a typed match component for them.
    return number if number <= POSTGRES_INTEGER_MAX else None


def _street_number_suffix(value: str) -> str | None:
    stripped = value.strip().upper()
    digits = str(_street_number_first(stripped) or "")
    if not digits or not stripped.startswith(digits):
        return None
    suffix = ""
    for character in stripped[len(digits) :]:
        if character.isalpha():
            suffix += character
        else:
            break
    return suffix or None


def _street_number_last(value: str) -> int | None:
    stripped = value.strip()
    if "-" not in stripped:
        return None
    remainder = stripped.split("-", 1)[1].strip()
    digits = ""
    for character in remainder:
        if character.isdigit():
            digits += character
        elif digits:
            break
    if not digits:
        return None
    number = int(digits)
    return number if number <= POSTGRES_INTEGER_MAX else None


@lru_cache(maxsize=4_096)
def _source_datetime(value: str) -> datetime | None:
    if not value.strip():
        return None
    for pattern in ("%Y%m%d %H:%M", "%Y%m%d%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(value.strip(), pattern)
        except ValueError:
            continue
    return None


@lru_cache(maxsize=32_768)
def _date(value: str, patterns: tuple[str, ...]) -> date | None:
    if not value.strip():
        return None
    for pattern in patterns:
        try:
            result = datetime.strptime(value.strip(), pattern).date()
            if 1900 <= result.year <= 2100:
                return result
            raise ValueError("PSI date is outside the registered range")
        except ValueError:
            continue
    raise ValueError("PSI date is malformed")


def _source_date(value: str, patterns: tuple[str, ...]) -> date | None:
    """Parse an official archive date while retaining rows with publisher defects.

    The public archives contain a small number of impossible eight-digit values
    such as ``10210906``.  They cannot be corrected without guessing.  Canonical
    archive ingestion therefore records the date as unknown while retaining the
    sale and its source identity.  Direct/fixture parsing remains fail-closed via
    ``_date`` so malformed caller-supplied data is still rejected.
    """
    try:
        return _date(value, patterns)
    except ValueError:
        return None


def _integer(value: str) -> int | None:
    if not value.strip():
        return None
    if not value.strip().isdigit():
        raise ValueError("PSI integer is malformed")
    return int(value)


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value) if value.strip() else None
    except InvalidOperation as exc:
        raise ValueError("PSI decimal is malformed") from exc


def _square_metres(value: str, unit: str) -> Decimal | None:
    """Convert documented PSI area units without inventing source semantics.

    The publisher documents ``M`` and ``H``, but its historical archives contain
    a handful of non-empty ``U`` values.  Preserve those original facts through
    ``area_original``/``area_unit`` and leave the derived metric value unset.
    Rejecting one undocumented code would otherwise discard an entire annual
    partition.
    """
    amount = _decimal(value)
    if amount is None:
        return None
    if unit.upper() == "M":
        return amount
    if unit.upper() == "H":
        return amount * 10_000
    return None
