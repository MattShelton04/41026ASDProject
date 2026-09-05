"""Validated inputs and deterministic market evidence calculations."""

from __future__ import annotations

import gzip
import json
from collections import Counter
from datetime import date
from statistics import median
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FEATURE_KEY = "student-2-market-intelligence"
TOOL_ALLOWLIST = ("market.cases.inspect.v1", "market.sales.summary.v1")
SALES_SCHEMA_VERSION = "propertyscope.property-sales.v3"


class FeatureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MarketCaseCreate(FeatureModel):
    name: str = Field(min_length=1, max_length=120)
    property_ref: UUID
    address_display: str = Field(min_length=1, max_length=500)
    date_from: date
    date_to: date
    status: Literal["draft", "active", "complete", "archived"] = "draft"
    notes: str = Field(default="", max_length=4000)
    filters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name", "address_display", "notes", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def ordered_dates(self) -> MarketCaseCreate:
        if self.date_from > self.date_to:
            raise ValueError("date_from must be on or before date_to")
        return self


class MarketCaseUpdate(FeatureModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    address_display: str | None = Field(default=None, min_length=1, max_length=500)
    date_from: date | None = None
    date_to: date | None = None
    status: Literal["draft", "active", "complete", "archived"] | None = None
    notes: str | None = Field(default=None, max_length=4000)
    filters: dict[str, Any] | None = None
    ai_run_ref: UUID | None = None

    @field_validator("name", "address_display", "notes", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class AssistantTurn(FeatureModel):
    case_id: UUID
    message: str = Field(min_length=2, max_length=2000)

    @field_validator("message", mode="before")
    @classmethod
    def strip_message(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ProvenanceV3(FeatureModel):
    release_id: UUID
    release_version: str = Field(min_length=1, max_length=150)
    candidate_generation_id: UUID
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalisation_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


class SaleRecordV3(BaseModel):
    model_config = ConfigDict(extra="ignore")

    source_business_key: str = Field(min_length=1, max_length=300)
    source_revision: int = Field(ge=1)
    source_era: str = Field(min_length=1, max_length=100)
    property_ref: UUID | None = None
    contract_date: date | None = None
    settlement_date: date | None = None
    price_aud: int | None = Field(default=None, ge=0)
    area_square_metres: str | None = None
    property_name: str | None = None
    unit_number: str | None = None
    house_number: str | None = None
    street_number_first: int | None = Field(default=None, ge=0)
    street_number_suffix: str | None = None
    street_name: str | None = None
    street_type: str | None = None
    locality: str | None = None
    postcode: str | None = Field(default=None, pattern=r"^\d{4}$")
    sale_code: str | None = None
    interest_of_sale: str | None = None
    match_tier: str = Field(min_length=1, max_length=20)
    match_confidence: str = Field(pattern=r"^(0(\.\d{1,4})?|1(\.0{1,4})?)$")
    geographic_precision: str = Field(min_length=1, max_length=100)
    provenance: ProvenanceV3

    def normalized(self, *, synthetic: bool) -> dict[str, Any]:
        street_number = self.house_number or (
            str(self.street_number_first) if self.street_number_first is not None else ""
        )
        street = " ".join(
            part for part in (street_number, self.street_name or "", self.street_type or "") if part
        )
        locality = " ".join(part for part in (self.locality or "", self.postcode or "") if part)
        address = ", ".join(part for part in (self.property_name or street, locality) if part)
        area: float | None
        try:
            area = float(self.area_square_metres) if self.area_square_metres is not None else None
        except ValueError:
            area = None
        return {
            "source_business_key": self.source_business_key,
            "source_revision": self.source_revision,
            "source_era": self.source_era,
            "property_ref": str(self.property_ref) if self.property_ref else None,
            "address_display": address or "Address not supplied in source",
            "contract_date": self.contract_date.isoformat() if self.contract_date else None,
            "settlement_date": self.settlement_date.isoformat() if self.settlement_date else None,
            "price_aud": self.price_aud,
            "area_square_metres": area,
            "locality": self.locality,
            "postcode": self.postcode,
            "sale_code": self.sale_code,
            "interest_of_sale": self.interest_of_sale,
            "match_tier": self.match_tier,
            "match_confidence": float(self.match_confidence),
            "geographic_precision": self.geographic_precision,
            "release_id": str(self.provenance.release_id),
            "release_version": self.provenance.release_version,
            "source_record_sha256": self.provenance.source_record_sha256,
            "normalisation_version": self.provenance.normalisation_version,
            "synthetic": synthetic,
        }


class PublicationRequest(FeatureModel):
    release_id: UUID
    dataset_id: Literal["nsw-psi-sales"]
    schema_version: Literal["propertyscope.property-sales.v3"]
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_count: int = Field(ge=0)
    manifest: dict[str, Any]
    artifact_path: str = Field(
        pattern=r"^/api/data-platform/v1/dataset-releases/[0-9a-f-]+/artifact$"
    )
    idempotency_key: str = Field(min_length=8, max_length=200)

    @model_validator(mode="after")
    def consistent_manifest(self) -> PublicationRequest:
        expected = {
            "product_schema_version": self.schema_version,
            "release_id": str(self.release_id),
            "dataset_id": self.dataset_id,
            "target_feature": "feature-2",
            "record_count": self.record_count,
            "content_sha256": self.content_sha256,
        }
        for key, value in expected.items():
            if self.manifest.get(key) != value:
                raise ValueError(f"manifest {key} does not match publication envelope")
        if self.manifest.get("content_encoding") != "gzip":
            raise ValueError("only gzip sales artifacts are accepted")
        if (
            self.artifact_path
            != f"/api/data-platform/v1/dataset-releases/{self.release_id}/artifact"
        ):
            raise ValueError("artifact path does not match the release")
        byte_count = self.manifest.get("byte_count")
        if byte_count is not None and (type(byte_count) is not int or byte_count < 1):
            raise ValueError("manifest byte_count must be a positive integer")
        return self


def decode_sales_artifact(
    publication: PublicationRequest, compressed: bytes
) -> list[dict[str, Any]]:
    """Decode an in-memory fixture; live imports use the bounded streaming worker."""

    try:
        expanded = gzip.decompress(compressed)
    except (gzip.BadGzipFile, OSError) as exc:
        raise ValueError("sales artifact is not valid gzip data") from exc
    lines = expanded.splitlines()
    if len(lines) != publication.record_count:
        raise ValueError("sales artifact record count does not match publication envelope")
    synthetic = "synthetic" in str(publication.manifest.get("source", "")).lower()
    normalized: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        try:
            raw = json.loads(line)
            record = SaleRecordV3.model_validate(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ValueError(f"sales artifact record {index} is contract-invalid") from exc
        if record.provenance.release_id != publication.release_id:
            raise ValueError(f"sales artifact record {index} has the wrong release_id")
        normalized.append(record.normalized(synthetic=synthetic))
    return normalized


def summarize_sales(case: dict[str, Any], sales: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute explainable market facts; no model performs arithmetic or valuation."""

    minimum_tier = str(case.get("filters", {}).get("minimum_match_tier", "B")).upper()
    ranking = {"A": 3, "B": 2, "C": 1}
    threshold = ranking.get(minimum_tier, 2)
    accepted: list[dict[str, Any]] = []
    exclusions: Counter[str] = Counter()
    for sale in sales:
        contract_date = sale.get("contract_date")
        price = sale.get("price_aud")
        tier = str(sale.get("match_tier", "")).upper()
        if not isinstance(contract_date, str):
            exclusions["missing_contract_date"] += 1
        elif contract_date < case["date_from"] or contract_date > case["date_to"]:
            exclusions["outside_case_period"] += 1
        elif not isinstance(price, int) or price <= 0:
            exclusions["missing_or_zero_price"] += 1
        elif ranking.get(tier, 0) < threshold:
            exclusions["below_match_threshold"] += 1
        else:
            accepted.append(sale)
    prices = [int(item["price_aud"]) for item in accepted]
    volumes = Counter(str(item["contract_date"])[:4] for item in accepted)
    source_releases = sorted({str(item["release_id"]) for item in accepted})
    limitations: list[str] = []
    if len(accepted) < 3:
        limitations.append("Fewer than three eligible sales; treat this as insufficient evidence.")
    if exclusions:
        limitations.append("Some source records were excluded by the case window or quality rules.")
    if any(bool(item.get("synthetic")) for item in accepted):
        limitations.append("This case currently includes deterministic synthetic showcase data.")
    limitations.append(
        "Recorded sales are historical evidence, not a valuation or buying recommendation."
    )
    return {
        "eligible_sale_count": len(accepted),
        "median_price_aud": int(median(prices)) if prices else None,
        "transaction_volume": [
            {"period": period, "transactions": volumes[period]} for period in sorted(volumes)
        ],
        "excluded_sale_count": sum(exclusions.values()),
        "exclusion_reasons": dict(sorted(exclusions.items())),
        "source_release_ids": source_releases,
        "date_from": case["date_from"],
        "date_to": case["date_to"],
        "minimum_match_tier": minimum_tier,
        "limitations": limitations,
    }
