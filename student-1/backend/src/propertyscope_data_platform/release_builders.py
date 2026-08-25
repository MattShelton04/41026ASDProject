"""Deterministic, bounded builders for versioned downstream data products."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from .configuration import (
    ConfigurationError,
    JobProfile,
    SourceRegisterEntry,
    load_adapter_register,
    load_job_profiles,
    load_source_register,
    validate_job_profile,
)
from .domain import ConsumerPublicationRequest, PublicationReceiptResult

PUBLIC_REDISTRIBUTION_POLICIES = frozenset(
    {
        "committed-synthetic-fixture",
        "bounded-derived-release",
        "approved-bounded-extract",
    }
)
RESTRICTED_REDISTRIBUTION_POLICIES = frozenset({"licence-controlled"})
SAFE_REDISTRIBUTION_POLICIES = PUBLIC_REDISTRIBUTION_POLICIES | RESTRICTED_REDISTRIBUTION_POLICIES
DEFAULT_PUBLIC_ARTIFACT_BYTES = 50_000_000
MAX_PUBLIC_ARTIFACT_BYTES = 250_000_000


class ProductModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProductProvenance(ProductModel):
    release_id: uuid.UUID
    release_version: str = Field(min_length=1, max_length=150)
    candidate_generation_id: uuid.UUID
    source_record_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    normalisation_version: str = Field(pattern=r"^\d+\.\d+\.\d+$")


class PropertySnapshotRecord(ProductModel):
    property_ref: uuid.UUID
    source_address_id: str = Field(min_length=1, max_length=200)
    display_address: str = Field(min_length=1, max_length=500)
    flat_type: str | None = None
    unit_number: str | None = None
    street_number_first: int | None = Field(default=None, ge=0)
    street_number_suffix: str | None = None
    street_number_last: int | None = Field(default=None, ge=0)
    street_name: str | None = None
    street_type: str | None = None
    locality: str = Field(min_length=1, max_length=100)
    state: str = Field(pattern=r"^NSW$")
    postcode: str = Field(pattern=r"^\d{4}$")
    latitude: float = Field(ge=-38, le=-27)
    longitude: float = Field(ge=140, le=160)
    source_status: str = Field(min_length=1, max_length=100)
    geocode_type: str | None = Field(default=None, max_length=100)
    geocode_precision: str | None = Field(default=None, max_length=100)
    source_crs: str = Field(min_length=1, max_length=30)
    transformation_version: str = Field(min_length=1, max_length=100)
    provenance: ProductProvenance


class PropertySaleRecord(ProductModel):
    source_business_key: str = Field(min_length=1, max_length=300)
    source_revision: int = Field(ge=1)
    source_era: str = Field(min_length=1, max_length=100)
    district_code: str | None = None
    source_property_id: str | None = None
    dealing_id: str | None = None
    contract_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    settlement_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    price_aud: int | None = Field(default=None, ge=0)
    area_original: str | None = None
    area_unit: str | None = None
    area_square_metres: str | None = None
    property_ref: uuid.UUID | None = None
    match_tier: str = Field(min_length=1, max_length=20)
    match_confidence: str = Field(pattern=r"^(0(\.\d{1,4})?|1(\.0{1,4})?)$")
    geographic_precision: str = Field(min_length=1, max_length=100)
    provenance: ProductProvenance


class CrimeObservation(ProductModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    count: int = Field(gt=0)
    source_row_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CrimeSeriesRecord(ProductModel):
    geography_kind: str = Field(pattern=r"^(postcode|suburb)$")
    geography_value: str = Field(min_length=1, max_length=100)
    state: str = Field(pattern=r"^NSW$")
    source_category_key: str = Field(min_length=1, max_length=200)
    offence_label: str | None = None
    subcategory_label: str | None = None
    observed_months: tuple[str, ...] = Field(min_length=1, max_length=600)
    first_month: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    last_month: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    month_count: int = Field(ge=1, le=600)
    blank_means_observed_zero: bool
    completeness_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observations: tuple[CrimeObservation, ...] = Field(max_length=600)
    provenance: ProductProvenance

    @model_validator(mode="after")
    def coherent_coverage(self) -> CrimeSeriesRecord:
        if self.observed_months != tuple(sorted(set(self.observed_months))):
            raise ValueError("observed_months must be sorted and unique")
        if self.month_count != len(self.observed_months):
            raise ValueError("month_count must equal the exact observed-month count")
        if (
            self.first_month != self.observed_months[0]
            or self.last_month != self.observed_months[-1]
        ):
            raise ValueError("coverage bounds must match observed_months")
        if any(item.month not in self.observed_months for item in self.observations):
            raise ValueError("an observation month is outside the coverage universe")
        expected_hash = hashlib.sha256(
            json.dumps(self.observed_months, separators=(",", ":")).encode()
        ).hexdigest()
        if self.completeness_sha256 != expected_hash:
            raise ValueError("completeness_sha256 does not match observed_months")
        return self


class SchoolPointRecord(ProductModel):
    school_code: str = Field(min_length=1, max_length=100)
    school_name: str = Field(min_length=1, max_length=300)
    school_type: str = Field(min_length=1, max_length=100)
    operational_status: str = Field(min_length=1, max_length=100)
    locality_original: str = Field(min_length=1, max_length=100)
    locality_normalised: str = Field(min_length=1, max_length=100)
    state: str = Field(pattern=r"^NSW$")
    lga: str | None = None
    latitude: float = Field(ge=-38, le=-27)
    longitude: float = Field(ge=140, le=160)
    provenance: ProductProvenance


class ProductEnvelope(ProductModel):
    schema_version: str
    release_id: uuid.UUID
    release_version: str = Field(min_length=1, max_length=150)
    dataset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    target_feature: str = Field(pattern=r"^feature-[1-5]$")
    candidate_generation_id: uuid.UUID
    records: tuple[dict[str, Any], ...]


class PropertySnapshotProduct(ProductModel):
    schema_version: str = Field(pattern=r"^propertyscope\.property-snapshot\.v1$")
    release_id: uuid.UUID
    release_version: str
    dataset_id: str
    target_feature: str = Field(pattern=r"^feature-1$")
    candidate_generation_id: uuid.UUID
    records: tuple[PropertySnapshotRecord, ...]


class PropertySalesProduct(ProductModel):
    schema_version: str = Field(pattern=r"^propertyscope\.property-sales\.v1$")
    release_id: uuid.UUID
    release_version: str
    dataset_id: str
    target_feature: str = Field(pattern=r"^feature-2$")
    candidate_generation_id: uuid.UUID
    records: tuple[PropertySaleRecord, ...]


class CrimeSeriesProduct(ProductModel):
    schema_version: str = Field(pattern=r"^propertyscope\.crime-series\.v1$")
    release_id: uuid.UUID
    release_version: str
    dataset_id: str
    target_feature: str = Field(pattern=r"^feature-3$")
    candidate_generation_id: uuid.UUID
    records: tuple[CrimeSeriesRecord, ...]


class SchoolPointsProduct(ProductModel):
    schema_version: str = Field(pattern=r"^propertyscope\.school-points\.v1$")
    release_id: uuid.UUID
    release_version: str
    dataset_id: str
    target_feature: str = Field(pattern=r"^feature-3$")
    candidate_generation_id: uuid.UUID
    records: tuple[SchoolPointRecord, ...]


class ReleaseManifestV1(ProductModel):
    manifest_schema_version: str = Field(pattern=r"^propertyscope\.release-manifest\.v1$")
    product_schema_version: str
    release_id: uuid.UUID
    release_version: str
    dataset_id: str
    target_feature: str = Field(pattern=r"^feature-[1-5]$")
    builder_key: str
    builder_version: str
    import_profile: str
    normalisation_version: str
    publisher: str
    source: str
    source_release: str
    source_retrieved_at: datetime | None = None
    source_effective_at: datetime | None = None
    candidate_generation_id: uuid.UUID
    record_count: int = Field(ge=0)
    record_count_definition: str
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: str
    content_encoding: str | None = None
    byte_count: int = Field(ge=1, le=MAX_PUBLIC_ARTIFACT_BYTES)
    geography_coverage: tuple[str, ...]
    temporal_coverage: dict[str, str] | None = None
    measures: tuple[str, ...]
    entity_types: tuple[str, ...]
    source_licence: str
    licence_url: str
    redistribution_decision: str
    download_permitted: bool
    known_limitations: tuple[str, ...]
    created_at: datetime
    supersedes_release_id: uuid.UUID | None = None


class DataProductCatalogueEntry(ProductModel):
    dataset_id: str
    display_name: str
    source_key: str
    job_profile: str
    import_profile: str
    target_feature: str
    product_schema_version: str
    builder_key: str
    builder_version: str
    supported_scope_profiles: tuple[str, ...]
    redistribution_decision: str
    download_permitted: bool
    capability_state: str = Field(
        pattern=r"^(registered|fixture_backed|executable_cached|executable_live|blocked|deferred|catalogued)$"
    )
    ordering_rule: str
    max_rows: int
    max_bytes: int
    known_limitations: tuple[str, ...]
    latest_accepted_release: dict[str, Any] | None = None


class ReleaseDetailContract(ProductModel):
    id: uuid.UUID
    dataset_id: str
    target_feature: str
    release_version: str
    schema_version: str
    status: str = Field(pattern=r"^(draft|candidate|awaiting_review|accepted|rejected|superseded)$")
    record_count: int = Field(ge=0)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_json: ReleaseManifestV1
    supersedes_release_id: uuid.UUID | None = None
    version: int = Field(ge=1)
    receipts: tuple[PublicationReceiptResult, ...] = ()


class BuildContext(ProductModel):
    release_id: uuid.UUID
    release_version: str
    dataset_id: str
    target_feature: str
    candidate_generation_id: uuid.UUID
    import_profile: str
    normalisation_version: str
    publisher: str
    source: str
    source_release: str
    source_licence: str
    licence_url: str
    redistribution_policy: str
    source_retrieved_at: datetime | None = None
    source_effective_at: datetime | None = None
    scope: dict[str, Any] = Field(default_factory=dict)
    supersedes_release_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class BuiltProduct:
    content: bytes
    manifest: ReleaseManifestV1


@dataclass(frozen=True, slots=True)
class ReleaseBuilderSpec:
    key: str
    version: str
    import_profiles: frozenset[str]
    contract: str
    target_feature: str
    media_type: str
    content_encoding: str | None
    ordering_rule: str
    max_rows: int
    max_bytes: int
    redistribution_policies: frozenset[str]
    record_adapter: TypeAdapter[Any]


class ReleaseBuilder(Protocol):
    spec: ReleaseBuilderSpec

    def build(
        self, context: BuildContext, rows: Iterable[Mapping[str, Any]], *, created_at: datetime
    ) -> BuiltProduct: ...


def _stable_property_ref(source_id: str) -> uuid.UUID:
    digest = hashlib.md5(
        f"propertyscope-gnaf:{source_id}".encode(), usedforsecurity=False
    ).hexdigest()
    return uuid.UUID(digest)


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _point(row: Mapping[str, Any]) -> tuple[float, float]:
    geometry = row.get("geometry")
    if not isinstance(geometry, Mapping) or geometry.get("type") != "Point":
        raise ValueError("release projection must contain a GeoJSON Point")
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list | tuple) or len(coordinates) != 2:
        raise ValueError("release projection point coordinates are invalid")
    return float(coordinates[1]), float(coordinates[0])


def _provenance(context: BuildContext, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "release_id": str(context.release_id),
        "release_version": context.release_version,
        "candidate_generation_id": str(context.candidate_generation_id),
        "source_record_sha256": str(row["source_row_sha256"]),
        "normalisation_version": str(row["normalisation_version"]),
    }


class RegisteredReleaseBuilder:
    def __init__(self, spec: ReleaseBuilderSpec) -> None:
        self.spec = spec

    def build(
        self, context: BuildContext, rows: Iterable[Mapping[str, Any]], *, created_at: datetime
    ) -> BuiltProduct:
        if context.import_profile not in self.spec.import_profiles:
            raise ValueError("release builder/import profile mismatch")
        if context.target_feature != self.spec.target_feature:
            raise ValueError("release builder/target feature mismatch")
        if context.redistribution_policy not in self.spec.redistribution_policies:
            raise ValueError("release builder/redistribution policy mismatch")
        records = self._records(context, rows)
        if not records:
            raise ValueError("release product must not be empty")
        if len(records) > self.spec.max_rows:
            raise ValueError("release product exceeds the registered row bound; narrow its scope")
        envelope = ProductEnvelope(
            schema_version=self.spec.contract,
            release_id=context.release_id,
            release_version=context.release_version,
            dataset_id=context.dataset_id,
            target_feature=context.target_feature,
            candidate_generation_id=context.candidate_generation_id,
            records=tuple(records),
        )
        content = _canonical_bytes(envelope.model_dump(mode="json"))
        if len(content) > self.spec.max_bytes:
            raise ValueError("release product exceeds the registered byte bound; narrow its scope")
        digest = hashlib.sha256(content).hexdigest()
        geographies, temporal, measures, entities, count_definition, limitations = self._summary(
            context, records
        )
        decision = context.redistribution_policy
        manifest = ReleaseManifestV1(
            manifest_schema_version="propertyscope.release-manifest.v1",
            product_schema_version=self.spec.contract,
            release_id=context.release_id,
            release_version=context.release_version,
            dataset_id=context.dataset_id,
            target_feature=context.target_feature,
            builder_key=self.spec.key,
            builder_version=self.spec.version,
            import_profile=context.import_profile,
            normalisation_version=context.normalisation_version,
            publisher=context.publisher,
            source=context.source,
            source_release=context.source_release,
            source_retrieved_at=context.source_retrieved_at,
            source_effective_at=context.source_effective_at,
            candidate_generation_id=context.candidate_generation_id,
            record_count=len(records),
            record_count_definition=count_definition,
            content_sha256=digest,
            media_type=self.spec.media_type,
            content_encoding=self.spec.content_encoding,
            byte_count=len(content),
            geography_coverage=tuple(sorted(geographies)),
            temporal_coverage=temporal,
            measures=tuple(sorted(measures)),
            entity_types=tuple(sorted(entities)),
            source_licence=context.source_licence,
            licence_url=context.licence_url,
            redistribution_decision=decision,
            download_permitted=decision in PUBLIC_REDISTRIBUTION_POLICIES,
            known_limitations=tuple(limitations),
            created_at=created_at,
            supersedes_release_id=context.supersedes_release_id,
        )
        return BuiltProduct(content=content, manifest=manifest)

    def _records(
        self, context: BuildContext, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        if self.spec.key == "property-snapshot":
            return self._property_records(context, rows)
        if self.spec.key == "property-sales":
            return self._sale_records(context, rows)
        if self.spec.key == "crime-series":
            return self._crime_records(context, rows)
        if self.spec.key == "school-points":
            return self._school_records(context, rows)
        raise AssertionError("unreachable registered release builder")

    def _property_records(
        self, context: BuildContext, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for row in rows:
            latitude, longitude = _point(row)
            source_id = str(row["source_address_id"])
            record = PropertySnapshotRecord(
                property_ref=uuid.UUID(
                    str(row.get("property_ref") or _stable_property_ref(source_id))
                ),
                source_address_id=source_id,
                display_address=str(row["address_display"]),
                flat_type=row.get("flat_type"),
                unit_number=row.get("unit_number"),
                street_number_first=row.get("street_number_first"),
                street_number_suffix=row.get("street_number_suffix"),
                street_number_last=row.get("street_number_last"),
                street_name=row.get("street_name"),
                street_type=row.get("street_type"),
                locality=str(row["locality"]),
                state="NSW",
                postcode=str(row["postcode"]),
                latitude=latitude,
                longitude=longitude,
                source_status=str(row["source_status"]),
                geocode_type=str(row["geocode_type"]) if row.get("geocode_type") else None,
                geocode_precision=str(row["geocode_precision"])
                if row.get("geocode_precision")
                else None,
                source_crs=str(row["source_crs"]),
                transformation_version="postgis-st_transform-1.0.0",
                provenance=ProductProvenance.model_validate(_provenance(context, row)),
            )
            result.append(record.model_dump(mode="json"))
        result.sort(key=lambda item: (item["property_ref"], item["source_address_id"]))
        return result

    def _sale_records(
        self, context: BuildContext, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        result = []
        for row in rows:
            confidence = format(Decimal(str(row["match_confidence"])), "f")
            record = PropertySaleRecord(
                source_business_key=str(row["source_business_key"]),
                source_revision=int(row["source_revision"]),
                source_era=str(row["source_era"]),
                district_code=row.get("district_code"),
                source_property_id=row.get("property_id"),
                dealing_id=row.get("dealing_id"),
                contract_date=row.get("contract_date"),
                settlement_date=row.get("settlement_date"),
                price_aud=row.get("price_aud"),
                area_original=str(row["area_original"])
                if row.get("area_original") is not None
                else None,
                area_unit=row.get("area_unit"),
                area_square_metres=str(row["area_square_metres"])
                if row.get("area_square_metres") is not None
                else None,
                property_ref=row.get("property_ref"),
                match_tier=str(row["match_tier"]),
                match_confidence=confidence,
                geographic_precision=str(row["geographic_precision"]),
                provenance=ProductProvenance.model_validate(_provenance(context, row)),
            )
            result.append(record.model_dump(mode="json"))
        result.sort(key=lambda item: (item["source_business_key"], item["source_revision"]))
        if len({(item["source_business_key"], item["source_revision"]) for item in result}) != len(
            result
        ):
            raise ValueError("release product contains a duplicate sale revision")
        return result

    def _crime_records(
        self, context: BuildContext, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        materialised = list(rows)
        observations: dict[tuple[str, str, str], list[Mapping[str, Any]]] = {}
        coverage_rows: list[Mapping[str, Any]] = []
        for row in materialised:
            key = (
                str(row["geography_kind"]),
                str(row["geography_value"]),
                str(row["source_category_key"]),
            )
            if row.get("record_kind") == "coverage":
                coverage_rows.append(row)
            else:
                observations.setdefault(key, []).append(row)
        result = []
        for coverage in coverage_rows:
            key = (
                str(coverage["geography_kind"]),
                str(coverage["geography_value"]),
                str(coverage["source_category_key"]),
            )
            members = sorted(observations.get(key, []), key=lambda item: str(item["month"]))
            record = CrimeSeriesRecord(
                geography_kind=key[0],
                geography_value=key[1],
                state="NSW",
                source_category_key=key[2],
                offence_label=str(members[0]["offence_label"]) if members else None,
                subcategory_label=str(members[0]["subcategory_label"]) if members else None,
                observed_months=tuple(str(value) for value in coverage["observed_months"]),
                first_month=str(coverage["first_month"]),
                last_month=str(coverage["last_month"]),
                month_count=int(coverage["month_count"]),
                blank_means_observed_zero=bool(coverage["blank_means_observed_zero"]),
                completeness_sha256=str(coverage["completeness_sha256"]),
                observations=tuple(
                    CrimeObservation(
                        month=str(item["month"]),
                        count=int(item["count"]),
                        source_row_sha256=str(item["source_row_sha256"]),
                    )
                    for item in members
                ),
                provenance=ProductProvenance.model_validate(_provenance(context, coverage)),
            )
            result.append(record.model_dump(mode="json"))
        if observations.keys() - {
            (item["geography_kind"], item["geography_value"], item["source_category_key"])
            for item in result
        }:
            raise ValueError("crime observations are missing an exact coverage record")
        result.sort(
            key=lambda item: (
                item["geography_kind"],
                item["geography_value"],
                item["source_category_key"],
            )
        )
        return result

    def _school_records(
        self, context: BuildContext, rows: Iterable[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        result = []
        for row in rows:
            latitude, longitude = _point(row)
            record = SchoolPointRecord(
                school_code=str(row["school_code"]),
                school_name=str(row["school_name"]),
                school_type=str(row["school_type"]),
                operational_status=str(row["status"]),
                locality_original=str(row["locality_original"]),
                locality_normalised=str(row["locality_normalised"]),
                state="NSW",
                lga=row.get("lga_name"),
                latitude=latitude,
                longitude=longitude,
                provenance=ProductProvenance.model_validate(_provenance(context, row)),
            )
            result.append(record.model_dump(mode="json"))
        result.sort(key=lambda item: item["school_code"])
        if len({item["school_code"] for item in result}) != len(result):
            raise ValueError("release product contains duplicate school codes")
        return result

    def _summary(
        self, context: BuildContext, records: list[dict[str, Any]]
    ) -> tuple[set[str], dict[str, str] | None, set[str], set[str], str, tuple[str, ...]]:
        if self.spec.key == "property-snapshot":
            return (
                {f"NSW:{item['locality']}:{item['postcode']}" for item in records},
                None,
                set(),
                {"property_address"},
                "number of source-aligned property/address records in records",
                (
                    "Address identity is not legal title, parcel, ownership, "
                    "valuation, or occupancy evidence.",
                ),
            )
        if self.spec.key == "property-sales":
            dates = sorted(
                item["contract_date"] for item in records if item.get("contract_date") is not None
            )
            temporal = {"from": dates[0], "to": dates[-1]} if dates else None
            return (
                {"NSW"},
                temporal,
                {"price_aud", "area_square_metres"},
                {"property_sale"},
                "number of unique source business-key and revision pairs in records",
                (
                    "Source-aligned sales include unusual and unmatched records; "
                    "consumers own analytical exclusions.",
                    "This product is not a valuation, forecast, comparable set, "
                    "or investment recommendation.",
                ),
            )
        if self.spec.key == "crime-series":
            months = sorted(month for item in records for month in item["observed_months"])
            return (
                {f"{item['geography_kind']}:{item['geography_value']}" for item in records},
                {"from": months[0], "to": months[-1]} if months else None,
                {"recorded_count"},
                {"crime_series"},
                "number of geography/category series records with exact coverage universes",
                (
                    "R0 comparisons must use the declared geography kind; postcode is not suburb.",
                    "Missing is zero only inside observed_months when "
                    "blank_means_observed_zero is true.",
                    "Counts do not establish rates, causes, predictions, safety, or desirability.",
                ),
            )
        return (
            {f"NSW:{item['locality_normalised']}" for item in records},
            None,
            set(),
            {"government_school_point"},
            "number of source school-code records in records",
            (
                "School proximity does not establish catchment, eligibility, quality, "
                "or recommendation.",
            ),
        )


def default_release_builders() -> Mapping[str, RegisteredReleaseBuilder]:
    definitions = (
        ReleaseBuilderSpec(
            "property-snapshot",
            "1.0.0",
            frozenset({"property-fixture", "gnaf-nsw"}),
            "propertyscope.property-snapshot.v1",
            "feature-1",
            "application/json",
            None,
            "property_ref, source_address_id",
            50_000,
            DEFAULT_PUBLIC_ARTIFACT_BYTES,
            frozenset({"committed-synthetic-fixture", "licence-controlled"}),
            TypeAdapter(PropertySnapshotRecord),
        ),
        ReleaseBuilderSpec(
            "property-sales",
            "1.0.0",
            frozenset({"psi-sales"}),
            "propertyscope.property-sales.v1",
            "feature-2",
            "application/json",
            None,
            "source_business_key, source_revision",
            250_000,
            MAX_PUBLIC_ARTIFACT_BYTES,
            frozenset({"bounded-derived-release"}),
            TypeAdapter(PropertySaleRecord),
        ),
        ReleaseBuilderSpec(
            "crime-series",
            "1.0.0",
            frozenset({"bocsar-sparse"}),
            "propertyscope.crime-series.v1",
            "feature-3",
            "application/json",
            None,
            "geography_kind, geography_value, source_category_key",
            50_000,
            DEFAULT_PUBLIC_ARTIFACT_BYTES,
            frozenset({"approved-bounded-extract"}),
            TypeAdapter(CrimeSeriesRecord),
        ),
        ReleaseBuilderSpec(
            "school-points",
            "1.0.0",
            frozenset({"schools-master"}),
            "propertyscope.school-points.v1",
            "feature-3",
            "application/json",
            None,
            "school_code",
            5_000,
            DEFAULT_PUBLIC_ARTIFACT_BYTES,
            frozenset({"approved-bounded-extract"}),
            TypeAdapter(SchoolPointRecord),
        ),
    )
    return MappingProxyType({item.key: RegisteredReleaseBuilder(item) for item in definitions})


def resolve_release_builder(
    key: str, version: str, builders: Mapping[str, RegisteredReleaseBuilder] | None = None
) -> RegisteredReleaseBuilder:
    registry = builders or default_release_builders()
    try:
        builder = registry[key]
    except KeyError as exc:
        raise ConfigurationError(f"unknown release builder: {key}") from exc
    if builder.spec.version != version:
        raise ConfigurationError(f"unsupported release builder version: {key} {version}")
    return builder


def validate_release_job(
    profile: JobProfile,
    *,
    source: SourceRegisterEntry,
    schema_names: Iterable[str],
    builders: Mapping[str, RegisteredReleaseBuilder] | None = None,
) -> None:
    builder = resolve_release_builder(
        profile.release_builder.key, profile.release_builder.version, builders
    )
    spec = builder.spec
    if profile.import_profile.key not in spec.import_profiles:
        raise ConfigurationError("job import profile does not match its release builder")
    if profile.target.contract != spec.contract:
        raise ConfigurationError("job target contract does not match its release builder")
    if profile.target.feature != spec.target_feature:
        raise ConfigurationError("job target feature does not match its release builder")
    if spec.contract not in set(schema_names):
        raise ConfigurationError("release builder contract schema is absent")
    if spec.media_type != "application/json" or spec.content_encoding is not None:
        raise ConfigurationError("release builder media type or encoding is unsupported")
    if source.redistribution_policy not in SAFE_REDISTRIBUTION_POLICIES:
        raise ConfigurationError("source redistribution policy is unsafe or unknown")
    if source.redistribution_policy not in spec.redistribution_policies:
        raise ConfigurationError("source redistribution policy does not match the release builder")
    for scope_name, scope in profile.scope_profiles.items():
        product_scope = scope.get("release_scope", scope)
        if not isinstance(product_scope, dict):
            raise ConfigurationError(f"job scope {scope_name} has an invalid release scope")
        maximum = product_scope.get("maximum_records")
        if maximum is None or not isinstance(maximum, int) or maximum < 1:
            raise ConfigurationError(f"job scope {scope_name} is not explicitly row bounded")
        if maximum > spec.max_rows:
            raise ConfigurationError(f"job scope {scope_name} exceeds the release row bound")


def validate_product_record(schema_version: str, payload: Mapping[str, Any]) -> None:
    adapters: dict[str, TypeAdapter[Any]] = {
        "propertyscope.property-snapshot.v1": TypeAdapter(PropertySnapshotRecord),
        "propertyscope.property-sales.v1": TypeAdapter(PropertySaleRecord),
        "propertyscope.crime-series.v1": TypeAdapter(CrimeSeriesRecord),
        "propertyscope.school-points.v1": TypeAdapter(SchoolPointRecord),
    }
    adapter = adapters.get(schema_version)
    if adapter is None:
        raise ValueError("unknown product schema")
    try:
        adapter.validate_python(payload)
    except ValidationError as exc:
        raise ValueError("product record does not match its registered schema") from exc


def product_schema_documents() -> dict[str, dict[str, Any]]:
    """Return the checked-in JSON Schema source documents for drift validation."""
    models: dict[str, type[BaseModel]] = {
        "property-snapshot.v1.schema.json": PropertySnapshotProduct,
        "property-sales.v1.schema.json": PropertySalesProduct,
        "crime-series.v1.schema.json": CrimeSeriesProduct,
        "school-points.v1.schema.json": SchoolPointsProduct,
        "release-manifest.v1.schema.json": ReleaseManifestV1,
        "data-product-catalogue-entry.v1.schema.json": DataProductCatalogueEntry,
        "release-detail.v1.schema.json": ReleaseDetailContract,
        "consumer-publication-request.v1.schema.json": ConsumerPublicationRequest,
        "consumer-publication-receipt.v1.schema.json": PublicationReceiptResult,
    }
    documents: dict[str, dict[str, Any]] = {}
    for filename, model in models.items():
        schema = model.model_json_schema(mode="validation")
        if filename == "consumer-publication-request.v1.schema.json":
            schema["properties"]["manifest"] = ReleaseManifestV1.model_json_schema(
                mode="validation"
            )
        schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
        schema["$id"] = f"https://propertyscope.local/contracts/{filename}"
        documents[filename] = schema
    return documents


def validate_feature_registration(feature_root: Path) -> None:
    """Fail startup when declarative jobs, builders, contracts, or policies drift."""
    config_root = feature_root / "config"
    contracts_root = feature_root / "contracts"
    jobs = load_job_profiles(config_root / "job-profiles")
    sources = load_source_register(config_root / "source-register.yaml")
    adapters = load_adapter_register(config_root / "adapter-register.yaml")
    documents = product_schema_documents()
    for filename, expected in documents.items():
        path = contracts_root / filename
        if not path.is_file():
            raise ConfigurationError(f"release contract schema is absent: {filename}")
        try:
            actual = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"release contract schema is invalid: {filename}") from exc
        if actual != expected:
            raise ConfigurationError(f"release contract schema has drifted: {filename}")
    schema_names = {builder.spec.contract for builder in default_release_builders().values()}
    for key in jobs:
        job = jobs.get_profile(key)
        validate_job_profile(job, sources=sources, adapters=adapters)
        validate_release_job(
            job,
            source=sources.get_profile(job.source_key),
            schema_names=schema_names,
        )


def data_product_catalogue(feature_root: Path) -> tuple[DataProductCatalogueEntry, ...]:
    jobs = load_job_profiles(feature_root / "config" / "job-profiles")
    sources = load_source_register(feature_root / "config" / "source-register.yaml")
    entries: list[DataProductCatalogueEntry] = []
    limitations = {
        "property-snapshot": (
            "Address identity is not legal title, parcel, ownership, valuation, "
            "or occupancy evidence.",
        ),
        "property-sales": (
            "Feature 2 owns analytical exclusions, comparables, calculations, and presentation.",
        ),
        "crime-series": (
            "R0 uses the declared source geography without translating postcode to suburb.",
            "Missing and recorded zero follow the exact coverage-universe fields.",
        ),
        "school-points": (
            "School proximity does not establish catchment, eligibility, quality, "
            "or recommendation.",
        ),
    }
    for key in jobs:
        job = jobs.get_profile(key)
        source = sources.get_profile(job.source_key)
        builder = resolve_release_builder(job.release_builder.key, job.release_builder.version)
        entries.append(
            DataProductCatalogueEntry(
                dataset_id=job.source_key,
                display_name=job.display_name,
                source_key=job.source_key,
                job_profile=job.key,
                import_profile=job.import_profile.key,
                target_feature=job.target.feature,
                product_schema_version=job.target.contract,
                builder_key=builder.spec.key,
                builder_version=builder.spec.version,
                supported_scope_profiles=tuple(sorted(job.scope_profiles)),
                redistribution_decision=source.redistribution_policy,
                download_permitted=source.redistribution_policy in PUBLIC_REDISTRIBUTION_POLICIES,
                capability_state=source.catalogue_status,
                ordering_rule=builder.spec.ordering_rule,
                max_rows=builder.spec.max_rows,
                max_bytes=builder.spec.max_bytes,
                known_limitations=limitations[builder.spec.key],
            )
        )
    return tuple(sorted(entries, key=lambda item: (item.target_feature, item.dataset_id)))
