"""Allowlisted read projections for release previews."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from propertyscope_data_store.errors import ConflictError


@dataclass(frozen=True, slots=True)
class ReleasePreviewSpec:
    """A fixed query pair and public column contract for one import profile."""

    select_sql: str
    count_sql: str
    columns: tuple[str, ...]


PROPERTY_RECORD_SPEC = ReleasePreviewSpec(
    """SELECT gnaf_pid AS source_address_id,
        COALESCE(property_ref,md5('propertyscope-gnaf:' || gnaf_pid)::uuid) AS property_ref,
        address_display,
        flat_type,unit_number,street_number_first,street_number_suffix,street_number_last,
        street_name,street_type,locality,postcode,source_status,geocode_type,source_crs,
        ST_AsGeoJSON(geom)::jsonb AS geometry,source_row_sha256,normalisation_version
        FROM warehouse.gnaf_address WHERE dataset_release_id=%s
        ORDER BY locality,postcode,address_display,gnaf_pid LIMIT %s OFFSET %s""",
    "SELECT count(*) AS count FROM warehouse.gnaf_address WHERE dataset_release_id=%s",
    (
        "source_address_id",
        "property_ref",
        "address_display",
        "flat_type",
        "unit_number",
        "street_number_first",
        "street_number_suffix",
        "street_number_last",
        "street_name",
        "street_type",
        "locality",
        "postcode",
        "source_status",
        "geocode_type",
        "source_crs",
        "geometry",
        "source_row_sha256",
        "normalisation_version",
    ),
)

PREVIEW_SPECS: dict[str, ReleasePreviewSpec] = {
    "gnaf-nsw": PROPERTY_RECORD_SPEC,
    "psi-sales": ReleasePreviewSpec(
        """SELECT source_business_key,source_revision,source_era,district_code,property_id,
        dealing_id,source_system,valuation_number,source_downloaded_at::text,property_name,
        unit_number,house_number,street_number_first,street_number_suffix,street_name,
        street_name_normalised,street_type,locality,postcode,land_description,dimensions,
        zoning_code,nature_code,primary_purpose,strata_lot_number,component_code,sale_code,
        interest_of_sale,contract_date::text,settlement_date::text,price_aud,
        area_square_metres::text,property_ref,match_tier,match_confidence::float8,
        geographic_precision FROM warehouse.psi_sale WHERE dataset_release_id=%s
        ORDER BY contract_date NULLS LAST,source_business_key,source_revision LIMIT %s OFFSET %s""",
        "SELECT count(*) AS count FROM warehouse.psi_sale WHERE dataset_release_id=%s",
        (
            "source_business_key",
            "source_revision",
            "source_era",
            "district_code",
            "property_id",
            "dealing_id",
            "source_system",
            "valuation_number",
            "source_downloaded_at",
            "property_name",
            "unit_number",
            "house_number",
            "street_number_first",
            "street_number_suffix",
            "street_name",
            "street_name_normalised",
            "street_type",
            "locality",
            "postcode",
            "land_description",
            "dimensions",
            "zoning_code",
            "nature_code",
            "primary_purpose",
            "strata_lot_number",
            "component_code",
            "sale_code",
            "interest_of_sale",
            "contract_date",
            "settlement_date",
            "price_aud",
            "area_square_metres",
            "property_ref",
            "match_tier",
            "match_confidence",
            "geographic_precision",
        ),
    ),
    "bocsar-sparse": ReleasePreviewSpec(
        """SELECT observation.geography_kind,observation.geography_value,
        observation.source_category_key,observation.offence_label,
        observation.subcategory_label,observation.month::text,observation.count,
        coverage.first_month::text,coverage.last_month::text,coverage.month_count,
        coverage.blank_means_observed_zero FROM warehouse.bocsar_observation observation
        LEFT JOIN warehouse.bocsar_coverage coverage
          ON coverage.dataset_release_id=observation.dataset_release_id
         AND coverage.geography_kind=observation.geography_kind
         AND coverage.geography_value=observation.geography_value
         AND coverage.source_category_key=observation.source_category_key
        WHERE observation.dataset_release_id=%s
        ORDER BY observation.geography_kind,observation.geography_value,
        observation.source_category_key,observation.month LIMIT %s OFFSET %s""",
        "SELECT count(*) AS count FROM warehouse.bocsar_observation WHERE dataset_release_id=%s",
        (
            "geography_kind",
            "geography_value",
            "source_category_key",
            "offence_label",
            "subcategory_label",
            "month",
            "count",
            "first_month",
            "last_month",
            "month_count",
            "blank_means_observed_zero",
        ),
    ),
    "schools-master": ReleasePreviewSpec(
        """SELECT school_code,school_name,school_type,status,locality_original,
        locality_normalised,lga_name,ST_AsGeoJSON(geom)::jsonb AS geometry
        FROM warehouse.school WHERE dataset_release_id=%s
        ORDER BY school_name,school_code LIMIT %s OFFSET %s""",
        "SELECT count(*) AS count FROM warehouse.school WHERE dataset_release_id=%s",
        (
            "school_code",
            "school_name",
            "school_type",
            "status",
            "locality_original",
            "locality_normalised",
            "lga_name",
            "geometry",
        ),
    ),
    "property-fixture": PROPERTY_RECORD_SPEC,
}


@dataclass(frozen=True, slots=True)
class ReleaseProductQuery:
    """One generation-scoped query plan consumed by a registered release builder."""

    select_sql: str
    select_params: tuple[Any, ...]
    count_sql: str
    count_params: tuple[Any, ...]


def release_product_query(
    profile: str,
    release_id: uuid.UUID,
    coverage: Mapping[str, Any],
    *,
    limit: int,
    offset: int,
) -> ReleaseProductQuery:
    """Resolve a fixed builder projection without accepting caller-provided SQL."""
    if profile not in {
        "property-fixture",
        "gnaf-nsw",
        "psi-sales",
        "bocsar-sparse",
        "schools-master",
    }:
        raise ConflictError("release import profile has no registered product projection")
    release_scope = coverage.get("release_scope", coverage)
    if not isinstance(release_scope, dict):
        raise ConflictError("release construction requires a registered product scope")
    maximum_records = release_scope.get("maximum_records")
    if (
        not isinstance(maximum_records, int)
        or isinstance(maximum_records, bool)
        or maximum_records < 1
    ):
        raise ConflictError("release construction requires a registered product row bound")
    page_limit = min(limit, max(0, maximum_records - offset))
    if profile in {"property-fixture", "gnaf-nsw"}:
        return ReleaseProductQuery(
            """SELECT COALESCE(property_ref,md5('propertyscope-gnaf:' || gnaf_pid)::uuid)
                AS property_ref,gnaf_pid AS source_address_id,address_display,flat_type,
                unit_number,street_number_first,street_number_suffix,street_number_last,
                street_name,street_type,locality,postcode,source_status,geocode_type,
                source_crs,ST_AsGeoJSON(geom)::jsonb AS geometry,source_row_sha256,
                normalisation_version FROM warehouse.gnaf_address
                WHERE dataset_release_id=%s
                ORDER BY gnaf_pid LIMIT %s OFFSET %s""",
            (release_id, page_limit, offset),
            """SELECT least(count(*),%s) AS count FROM warehouse.gnaf_address
                WHERE dataset_release_id=%s""",
            (maximum_records, release_id),
        )
    if profile == "psi-sales":
        years = release_scope.get("years", [])
        if not isinstance(years, list) or not years:
            raise ConflictError("PSI release construction requires an explicit bounded year scope")
        return ReleaseProductQuery(
            """SELECT source_business_key,source_revision,source_era,district_code,
                property_id,dealing_id,source_system,valuation_number,
                source_downloaded_at::text,property_name,unit_number,house_number,
                street_number_first,street_number_suffix,street_name,street_name_normalised,
                street_type,locality,postcode,land_description,dimensions,zoning_code,
                nature_code,primary_purpose,strata_lot_number,component_code,sale_code,
                interest_of_sale,contract_date::text,settlement_date::text,price_aud,
                area_original::text,area_unit,area_square_metres::text,property_ref,match_tier,
                match_confidence::text,geographic_precision,source_row_sha256,
                normalisation_version FROM warehouse.psi_sale WHERE dataset_release_id=%s
                  AND source_partition_year=ANY(%s)
                ORDER BY source_business_key,source_revision LIMIT %s OFFSET %s""",
            (release_id, years, page_limit, offset),
            """SELECT least(count(*),%s) AS count FROM warehouse.psi_sale
                WHERE dataset_release_id=%s AND source_partition_year=ANY(%s)""",
            (maximum_records, release_id, years),
        )
    if profile == "bocsar-sparse":
        merge_window = offset + page_limit
        return ReleaseProductQuery(
            """SELECT * FROM (
                SELECT * FROM (
                    SELECT 'observation'::text AS record_kind,geography_kind,geography_value,
                    source_category_key,offence_label,subcategory_label,month::text,count,
                    NULL::date[] AS observed_months,NULL::text AS first_month,
                    NULL::text AS last_month,NULL::integer AS month_count,
                    NULL::boolean AS blank_means_observed_zero,
                    NULL::text AS completeness_sha256,source_row_sha256,normalisation_version
                    FROM warehouse.bocsar_observation WHERE dataset_release_id=%s
                    ORDER BY geography_kind,geography_value,source_category_key,month
                    LIMIT %s
                ) observations
                UNION ALL
                SELECT * FROM (
                    SELECT 'coverage'::text,geography_kind,geography_value,source_category_key,
                    NULL::text,NULL::text,NULL::text,NULL::integer,
                    observed_months,first_month::text,last_month::text,
                    month_count,blank_means_observed_zero,completeness_sha256,
                    source_row_sha256,normalisation_version
                    FROM warehouse.bocsar_coverage WHERE dataset_release_id=%s
                    ORDER BY geography_kind,geography_value,source_category_key
                    LIMIT %s
                ) coverage
                ) product ORDER BY geography_kind,geography_value,source_category_key,
                record_kind,month NULLS LAST LIMIT %s OFFSET %s""",
            (release_id, merge_window, release_id, merge_window, page_limit, offset),
            """SELECT least((SELECT count(*) FROM warehouse.bocsar_observation
                WHERE dataset_release_id=%s) +
                (SELECT count(*) FROM warehouse.bocsar_coverage
                WHERE dataset_release_id=%s),%s) AS count""",
            (release_id, release_id, maximum_records),
        )
    if profile == "schools-master":
        return ReleaseProductQuery(
            """SELECT school_code,school_name,school_type,status,locality_original,
                locality_normalised,lga_name,ST_AsGeoJSON(geom)::jsonb AS geometry,
                source_row_sha256,normalisation_version FROM warehouse.school
                WHERE dataset_release_id=%s ORDER BY school_code LIMIT %s OFFSET %s""",
            (release_id, page_limit, offset),
            "SELECT least(count(*),%s) AS count FROM warehouse.school WHERE dataset_release_id=%s",
            (maximum_records, release_id),
        )
    raise AssertionError("unreachable registered product projection")


def normalise_product_rows(profile: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize database-native values included in registered product projections."""
    if profile != "bocsar-sparse":
        return rows
    for row in rows:
        observed_months = row.get("observed_months")
        if observed_months:
            row["observed_months"] = [value.isoformat() for value in observed_months]
    return rows
