"""Guard source identity and date semantics while eliminating repeated parser work."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pytest

from propertyscope_data_platform.adapters.psi import (
    PsiSale,
    _date,
    _sale_fingerprint,
    _source_date,
)


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"source_downloaded_at": datetime(2025, 2, 3, 4, 5), "area_original": Decimal("1.5000")},
        {"property_name": 'Café "Terrace"', "unit_number": " 01 ", "price_aud": 2**63 - 1},
    ],
)
def test_shallow_fingerprint_matches_historical_recursive_projection(
    changes: dict[str, Any],
) -> None:
    sale = replace(
        PsiSale(
            "001:P1:1",
            "post-2001",
            "001",
            "P1",
            "1",
            date(2025, 1, 1),
            None,
            800_000,
            None,
            None,
            None,
            None,
        ),
        **changes,
    )
    historical = {
        name: str(value) if isinstance(value, (date, Decimal)) else value
        for name, value in asdict(sale).items()
        if name != "source_business_key"
    }
    expected = hashlib.sha256(
        json.dumps(historical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert _sale_fingerprint(sale) == expected
    assert _sale_fingerprint(replace(sale, source_business_key="different-key")) == expected


def test_cached_dates_preserve_format_order_and_strict_source_distinction() -> None:
    for _ in range(2):
        assert _date("01022025", ("%d%m%Y", "%m%d%Y")) == date(2025, 2, 1)
        assert _date("01022025", ("%m%d%Y", "%d%m%Y")) == date(2025, 1, 2)
        assert _source_date("20250230", ("%Y%m%d",)) is None
        with pytest.raises(ValueError, match="PSI date is malformed"):
            _date("20250230", ("%Y%m%d",))
