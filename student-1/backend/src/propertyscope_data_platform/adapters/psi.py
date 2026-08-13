"""NSW Valuer-General PSI source-era helpers and stable source identity."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation


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


def _date(value: str, patterns: tuple[str, ...]) -> date | None:
    if not value.strip():
        return None
    for pattern in patterns:
        try:
            result = datetime.strptime(value.strip(), pattern).date()
            if 1900 <= result.year <= date.today().year + 1:
                return result
            return None
        except ValueError:
            continue
    return None


def _integer(value: str) -> int | None:
    return int(value) if value.strip().isdigit() else None


def _decimal(value: str) -> Decimal | None:
    try:
        return Decimal(value) if value.strip() else None
    except InvalidOperation:
        return None


def _square_metres(value: str, unit: str) -> Decimal | None:
    amount = _decimal(value)
    if amount is None:
        return None
    if unit.upper() == "M":
        return amount
    if unit.upper() == "H":
        return amount * 10_000
    return None
