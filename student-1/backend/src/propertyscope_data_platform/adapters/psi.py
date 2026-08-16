"""NSW Valuer-General PSI source-era helpers and stable source identity."""

from __future__ import annotations

import hashlib
import io
import json
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from zipfile import BadZipFile, ZipFile, ZipInfo


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
    maximum_members: int = 100_000,
    maximum_uncompressed_bytes: int = 750_000_000,
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
    maximum_members: int = 100_000,
    maximum_uncompressed_bytes: int = 750_000_000,
) -> Iterator[PsiSale]:
    """Yield every unique sale in an annual or standalone weekly PSI archive.

    ``maximum_records`` exists only for deterministic fixtures and targeted previews.
    Production full-data acquisition passes ``None`` and never truncates a partition.
    """
    if maximum_records is not None and maximum_records < 1:
        raise ValueError("PSI maximum_records must be positive")
    seen: set[tuple[str, str]] = set()
    yielded = 0
    try:
        with ZipFile(io.BytesIO(content)) as archive:
            for raw in _dat_payloads(
                archive,
                maximum_members=maximum_members,
                maximum_uncompressed_bytes=maximum_uncompressed_bytes,
            ):
                for fields in _b_records(raw):
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
    except BadZipFile as exc:
        raise ValueError("PSI source is not a valid ZIP archive") from exc
    if not seen:
        raise ValueError("PSI archive contains no supported B records")


def _sale_fingerprint(sale: PsiSale) -> str:
    """Distinguish corrected retransmissions while collapsing byte-equivalent source facts."""
    payload = {
        name: str(value) if isinstance(value, (date, Decimal)) else value
        for name, value in asdict(sale).items()
        if name != "source_business_key"
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _dat_payloads(
    archive: ZipFile, *, maximum_members: int, maximum_uncompressed_bytes: int
) -> Iterator[bytes]:
    members = [item for item in archive.infolist() if not item.is_dir()]
    if not members or len(members) > maximum_members:
        raise ValueError("PSI archive member count is outside the registered limit")
    _validate_members(members, maximum_uncompressed_bytes=maximum_uncompressed_bytes)
    for member in members:
        if member.filename.upper().endswith(".DAT"):
            yield archive.read(member)
        elif member.filename.lower().endswith(".zip"):
            try:
                with ZipFile(io.BytesIO(archive.read(member))) as nested:
                    nested_members = [item for item in nested.infolist() if not item.is_dir()]
                    if len(nested_members) > maximum_members:
                        raise ValueError("PSI nested archive exceeds the member limit")
                    _validate_members(
                        nested_members,
                        maximum_uncompressed_bytes=maximum_uncompressed_bytes,
                    )
                    for nested_member in nested_members:
                        if nested_member.filename.upper().endswith(".DAT"):
                            yield nested.read(nested_member)
            except BadZipFile as exc:
                raise ValueError("PSI archive contains an invalid nested ZIP") from exc


def _validate_members(members: list[ZipInfo], *, maximum_uncompressed_bytes: int) -> None:
    total = 0
    for member in members:
        parts = member.filename.replace("\\", "/").split("/")
        if member.filename.startswith("/") or ".." in parts:
            raise ValueError("PSI archive contains an unsafe member path")
        total += member.file_size
        if total > maximum_uncompressed_bytes:
            raise ValueError("PSI archive exceeds the uncompressed byte limit")


def _b_records(raw: bytes) -> Iterator[tuple[str, ...]]:
    text = raw.decode("latin-1", errors="replace").lstrip("\ufeff")
    for line in text.splitlines():
        fields = tuple(value.strip() for value in line.split(";"))
        if fields and fields[0] == "B":
            yield fields


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
            _date(padded[10], ("%d/%m/%Y", "%d%m%Y", "%Y%m%d")),
            None,
            _integer(padded[11]),
            _decimal(padded[13]),
            padded[14] or None,
            _square_metres(padded[13], padded[14]),
            None,
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
        _date(padded[13], ("%Y%m%d", "%d%m%Y")),
        _date(padded[14], ("%Y%m%d", "%d%m%Y")),
        _integer(padded[15]),
        _decimal(padded[11]),
        padded[12] or None,
        _square_metres(padded[11], padded[12]),
        padded[23] or None,
    )


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
    amount = _decimal(value)
    if amount is None:
        return None
    if unit.upper() == "M":
        return amount
    if unit.upper() == "H":
        return amount * 10_000
    raise ValueError("PSI area unit is malformed")
