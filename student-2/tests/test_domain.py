"""Pure market evidence and import-contract tests."""

from __future__ import annotations

import gzip
import hashlib
import json

import pytest
from pydantic import ValidationError

from propertyscope_market_intelligence.domain import (
    MarketCaseCreate,
    PublicationRequest,
    decode_sales_artifact,
    summarize_sales,
)


def _case() -> dict[str, object]:
    return {
        "date_from": "2024-01-01",
        "date_to": "2025-12-31",
        "filters": {"minimum_match_tier": "B"},
    }


def _sale(price: int, when: str, tier: str = "A") -> dict[str, object]:
    return {
        "contract_date": when,
        "price_aud": price,
        "match_tier": tier,
        "release_id": "50000000-0000-4000-8000-000000000001",
        "synthetic": True,
    }


def test_summary_calculates_median_volume_and_exclusions() -> None:
    summary = summarize_sales(
        _case(),
        [
            _sale(800_000, "2024-02-01"),
            _sale(1_000_000, "2024-08-01"),
            _sale(900_000, "2025-03-01"),
            _sale(0, "2025-04-01"),
            _sale(2_000_000, "2025-05-01", "D"),
            _sale(700_000, "2023-01-01"),
        ],
    )
    assert summary["eligible_sale_count"] == 3
    assert summary["median_price_aud"] == 900_000
    assert summary["transaction_volume"] == [
        {"period": "2024", "transactions": 2},
        {"period": "2025", "transactions": 1},
    ]
    assert summary["excluded_sale_count"] == 3
    assert summary["exclusion_reasons"] == {
        "below_match_threshold": 1,
        "missing_or_zero_price": 1,
        "outside_case_period": 1,
    }
    assert any("not a valuation" in item for item in summary["limitations"])


def test_summary_reports_insufficient_evidence() -> None:
    summary = summarize_sales(_case(), [_sale(800_000, "2024-02-01")])
    assert summary["median_price_aud"] == 800_000
    assert any("Fewer than three" in item for item in summary["limitations"])


def test_market_case_rejects_reversed_dates() -> None:
    with pytest.raises(ValidationError, match="date_from must be on or before date_to"):
        MarketCaseCreate.model_validate(
            {
                "name": "Bad window",
                "property_ref": "11111111-1111-4111-8111-111111111111",
                "address_display": "11 Example Street",
                "date_from": "2025-01-02",
                "date_to": "2025-01-01",
            }
        )


def test_v3_publication_is_decompressed_and_normalized() -> None:
    release_id = "70000000-0000-4000-8000-000000000001"
    record = {
        "source_business_key": "psi:1",
        "source_revision": 1,
        "source_era": "post-2001",
        "property_ref": "11111111-1111-4111-8111-111111111111",
        "contract_date": "2025-01-01",
        "price_aud": 950000,
        "area_square_metres": "480.5",
        "house_number": "11",
        "street_name": "EXAMPLE",
        "street_type": "STREET",
        "locality": "SYDNEY",
        "postcode": "2000",
        "match_tier": "A",
        "match_confidence": "1.0000",
        "geographic_precision": "exact_address",
        "provenance": {
            "release_id": release_id,
            "release_version": "test-r1",
            "candidate_generation_id": release_id,
            "source_record_sha256": "b" * 64,
            "normalisation_version": "1.0.0",
        },
    }
    compressed = gzip.compress((json.dumps(record) + "\n").encode())
    digest = hashlib.sha256(compressed).hexdigest()
    publication = PublicationRequest.model_validate(
        {
            "release_id": release_id,
            "dataset_id": "nsw-psi-sales",
            "schema_version": "propertyscope.property-sales.v3",
            "content_sha256": digest,
            "record_count": 1,
            "manifest": {
                "product_schema_version": "propertyscope.property-sales.v3",
                "release_id": release_id,
                "dataset_id": "nsw-psi-sales",
                "target_feature": "feature-2",
                "record_count": 1,
                "content_sha256": digest,
                "content_encoding": "gzip",
                "source": "Synthetic test fixture",
            },
            "artifact_path": f"/api/data-platform/v1/dataset-releases/{release_id}/artifact",
            "idempotency_key": "feature-2-test-1",
        }
    )
    normalized = decode_sales_artifact(publication, compressed)
    assert normalized[0]["address_display"] == "11 EXAMPLE STREET, SYDNEY 2000"
    assert normalized[0]["area_square_metres"] == 480.5
    assert normalized[0]["synthetic"] is True


def test_publication_manifest_must_match_envelope() -> None:
    with pytest.raises(ValidationError, match="manifest target_feature"):
        PublicationRequest.model_validate(
            {
                "release_id": "70000000-0000-4000-8000-000000000001",
                "dataset_id": "nsw-psi-sales",
                "schema_version": "propertyscope.property-sales.v3",
                "content_sha256": "a" * 64,
                "record_count": 0,
                "manifest": {
                    "product_schema_version": "propertyscope.property-sales.v3",
                    "release_id": "70000000-0000-4000-8000-000000000001",
                    "dataset_id": "nsw-psi-sales",
                    "target_feature": "feature-3",
                    "record_count": 0,
                    "content_sha256": "a" * 64,
                    "content_encoding": "gzip",
                },
                "artifact_path": (
                    "/api/data-platform/v1/dataset-releases/"
                    "70000000-0000-4000-8000-000000000001/artifact"
                ),
                "idempotency_key": "feature-2-test-2",
            }
        )
