"""Typed source-scale staging and fixed PSI/BOCSAR materialisation SQL."""

from __future__ import annotations

PSI_STREAM_COLUMNS = (
    "ordinal",
    "source_business_key",
    "source_revision",
    "source_era",
    "source_partition_year",
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
    "street_number_last",
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
    "area_original",
    "area_unit",
    "area_square_metres",
    "property_ref",
    "match_tier",
    "match_confidence",
    "geographic_precision",
    "source_row_sha256",
)

PSI_STAGE_SQL = """
    CREATE TEMP TABLE propertyscope_psi_import_stage (
        ordinal BIGINT NOT NULL,
        source_business_key TEXT NOT NULL,
        source_revision INTEGER NOT NULL,
        source_era TEXT NOT NULL,
        source_partition_year INTEGER NOT NULL,
        district_code TEXT,
        property_id TEXT,
        dealing_id TEXT,
        source_system TEXT,
        valuation_number TEXT,
        source_downloaded_at TIMESTAMP,
        property_name TEXT,
        unit_number TEXT,
        house_number TEXT,
        street_number_first INTEGER,
        street_number_last INTEGER,
        street_number_suffix TEXT,
        street_name TEXT,
        street_name_normalised TEXT,
        street_type TEXT,
        locality TEXT,
        postcode TEXT,
        land_description TEXT,
        dimensions TEXT,
        zoning_code TEXT,
        nature_code TEXT,
        primary_purpose TEXT,
        strata_lot_number TEXT,
        component_code TEXT,
        sale_code TEXT,
        interest_of_sale TEXT,
        contract_date DATE,
        settlement_date DATE,
        price_aud BIGINT,
        area_original NUMERIC,
        area_unit TEXT,
        area_square_metres NUMERIC,
        property_ref UUID,
        match_tier TEXT NOT NULL,
        match_confidence NUMERIC(5,4) NOT NULL,
        geographic_precision TEXT NOT NULL,
        source_row_sha256 TEXT NOT NULL
    ) ON COMMIT DROP
"""

PSI_COPY_SQL = """
    COPY propertyscope_psi_import_stage (
        ordinal,source_business_key,source_revision,source_era,source_partition_year,
        district_code,property_id,dealing_id,source_system,valuation_number,
        source_downloaded_at,property_name,unit_number,house_number,street_number_first,
        street_number_last,street_number_suffix,street_name,street_name_normalised,street_type,
        locality,postcode,land_description,dimensions,zoning_code,nature_code,primary_purpose,
        strata_lot_number,component_code,sale_code,interest_of_sale,contract_date,settlement_date,
        price_aud,area_original,area_unit,area_square_metres,property_ref,match_tier,
        match_confidence,geographic_precision,source_row_sha256
    ) FROM STDIN WITH (FREEZE TRUE)
"""

PSI_IDENTITY_SQL = """
    CREATE TEMP TABLE propertyscope_psi_identity_stage ON COMMIT DROP AS
    WITH first_transmissions AS (
        SELECT source_business_key,source_row_sha256,min(ordinal) AS first_ordinal
        FROM propertyscope_psi_import_stage
        GROUP BY source_business_key,source_row_sha256
    )
    SELECT source_business_key,source_row_sha256,first_ordinal,
        row_number() OVER (
            PARTITION BY source_business_key ORDER BY first_ordinal
        )::integer AS derived_revision
    FROM first_transmissions
"""

PSI_ADDRESS_RESOLUTION_SQL = """
    CREATE TEMP TABLE propertyscope_psi_address_resolution ON COMMIT DROP AS
    WITH eligible_addresses AS (
        SELECT DISTINCT source.postcode,source.locality,source.street_name_normalised,
            source.street_type,source.street_number_first,source.street_number_last,
            source.street_number_suffix,source.unit_number
        FROM propertyscope_psi_identity_stage identity
        JOIN propertyscope_psi_import_stage source
          ON source.ordinal=identity.first_ordinal
         AND source.source_business_key=identity.source_business_key
         AND source.source_row_sha256=identity.source_row_sha256
        WHERE source.postcode IS NOT NULL
          AND source.locality IS NOT NULL
          AND source.street_name_normalised IS NOT NULL
          AND source.street_type IS NOT NULL
          AND source.street_number_first IS NOT NULL
          AND source.house_number ~ '^[0-9]+[A-Z]?(-[0-9]+)?$'
    )
    SELECT eligible.postcode,eligible.locality,eligible.street_name_normalised,
        eligible.street_type,eligible.street_number_first,eligible.street_number_last,
        eligible.street_number_suffix,eligible.unit_number,
        count(property.property_ref)::integer AS match_count,
        CASE WHEN count(property.property_ref)=1
            THEN min(property.property_ref::text)::uuid ELSE NULL END AS exact_property_ref
    FROM eligible_addresses eligible
    LEFT JOIN registry.property property
      ON property.postcode=eligible.postcode
     AND property.locality=eligible.locality
     AND property.street_name=eligible.street_name_normalised
     AND property.street_type=eligible.street_type
     AND property.street_number_first=eligible.street_number_first
     AND COALESCE(property.street_number_last,-1)=COALESCE(eligible.street_number_last,-1)
     AND COALESCE(property.street_number_suffix,'')=COALESCE(eligible.street_number_suffix,'')
     AND COALESCE(property.unit_number,'')=COALESCE(eligible.unit_number,'')
    GROUP BY eligible.postcode,eligible.locality,eligible.street_name_normalised,
        eligible.street_type,eligible.street_number_first,eligible.street_number_last,
        eligible.street_number_suffix,eligible.unit_number
"""

PSI_TARGET_INSERT_SQL = """
    INSERT INTO warehouse.psi_sale (
        dataset_release_id,source_business_key,source_revision,source_era,
        source_partition_year,district_code,property_id,dealing_id,source_system,
        valuation_number,source_downloaded_at,property_name,unit_number,house_number,
        street_number_first,street_number_last,street_number_suffix,street_name,
        street_name_normalised,street_type,locality,postcode,land_description,dimensions,
        zoning_code,nature_code,primary_purpose,strata_lot_number,component_code,sale_code,
        interest_of_sale,contract_date,settlement_date,price_aud,area_original,area_unit,
        area_square_metres,property_ref,match_tier,match_confidence,geographic_precision,
        source_row_sha256,normalisation_version,artifact_record_id,ingestion_run_id,created_at
    ) SELECT %s,identity.source_business_key,identity.derived_revision,source.source_era,
        source.source_partition_year,source.district_code,source.property_id,source.dealing_id,
        source.source_system,source.valuation_number,source.source_downloaded_at,
        source.property_name,source.unit_number,source.house_number,source.street_number_first,
        source.street_number_last,source.street_number_suffix,source.street_name,
        source.street_name_normalised,source.street_type,source.locality,source.postcode,
        source.land_description,source.dimensions,source.zoning_code,source.nature_code,
        source.primary_purpose,source.strata_lot_number,source.component_code,source.sale_code,
        source.interest_of_sale,source.contract_date,source.settlement_date,source.price_aud,
        source.area_original,source.area_unit,source.area_square_metres,
        COALESCE(source.property_ref,resolution.exact_property_ref),
        CASE WHEN COALESCE(source.property_ref,resolution.exact_property_ref) IS NOT NULL
            THEN 'A' ELSE source.match_tier END,
        CASE WHEN COALESCE(source.property_ref,resolution.exact_property_ref) IS NOT NULL
            THEN 1 ELSE source.match_confidence END,
        CASE WHEN COALESCE(source.property_ref,resolution.exact_property_ref) IS NOT NULL
            THEN 'exact_address' ELSE source.geographic_precision END,
        identity.source_row_sha256,'1.0.0',%s,%s,now()
    FROM propertyscope_psi_identity_stage identity
    JOIN propertyscope_psi_import_stage source
      ON source.ordinal=identity.first_ordinal
     AND source.source_business_key=identity.source_business_key
     AND source.source_row_sha256=identity.source_row_sha256
    LEFT JOIN propertyscope_psi_address_resolution resolution
      ON resolution.postcode=source.postcode
     AND resolution.locality=source.locality
     AND resolution.street_name_normalised=source.street_name_normalised
     AND resolution.street_type=source.street_type
     AND resolution.street_number_first=source.street_number_first
     AND COALESCE(resolution.street_number_last,-1)=COALESCE(source.street_number_last,-1)
     AND COALESCE(resolution.street_number_suffix,'')=COALESCE(source.street_number_suffix,'')
     AND COALESCE(resolution.unit_number,'')=COALESCE(source.unit_number,'')
     AND source.postcode IS NOT NULL
     AND source.locality IS NOT NULL
     AND source.street_name_normalised IS NOT NULL
     AND source.street_type IS NOT NULL
     AND source.street_number_first IS NOT NULL
     AND source.house_number ~ '^[0-9]+[A-Z]?(-[0-9]+)?$'
    ON CONFLICT (dataset_release_id,source_business_key,source_revision) DO NOTHING
"""

PSI_PHASE_SQL = (
    ("identity_revision_derivation", PSI_IDENTITY_SQL),
    ("address_resolution", PSI_ADDRESS_RESOLUTION_SQL),
    ("target_materialisation", PSI_TARGET_INSERT_SQL),
)

BOCSAR_STREAM_COLUMNS = (
    "ordinal",
    "record_kind",
    "geography_kind",
    "geography_value",
    "source_category_key",
    "offence_label",
    "subcategory_label",
    "month",
    "count",
    "observed_months",
    "first_month",
    "last_month",
    "month_count",
    "blank_means_observed_zero",
    "completeness_sha256",
    "source_row_sha256",
)

BOCSAR_STAGE_SQL = """
    CREATE TEMP TABLE propertyscope_bocsar_import_stage (
        ordinal BIGINT NOT NULL,
        record_kind TEXT NOT NULL,
        geography_kind TEXT NOT NULL,
        geography_value TEXT NOT NULL,
        source_category_key TEXT NOT NULL,
        offence_label TEXT,
        subcategory_label TEXT,
        month DATE,
        count INTEGER,
        observed_months DATE[],
        first_month DATE,
        last_month DATE,
        month_count INTEGER,
        blank_means_observed_zero BOOLEAN,
        completeness_sha256 TEXT,
        source_row_sha256 TEXT NOT NULL
    ) ON COMMIT DROP
"""

BOCSAR_COPY_SQL = """
    COPY propertyscope_bocsar_import_stage (
        ordinal,record_kind,geography_kind,geography_value,source_category_key,
        offence_label,subcategory_label,month,count,observed_months,first_month,last_month,
        month_count,blank_means_observed_zero,completeness_sha256,source_row_sha256
    ) FROM STDIN WITH (FREEZE TRUE)
"""

BOCSAR_OBSERVATION_INSERT_SQL = """
    INSERT INTO warehouse.bocsar_observation (
        dataset_release_id,geography_kind,geography_value,source_category_key,
        offence_label,subcategory_label,month,count,source_row_sha256,
        normalisation_version,artifact_record_id,ingestion_run_id,created_at
    ) SELECT %s,geography_kind,geography_value,source_category_key,offence_label,
        subcategory_label,month,count,source_row_sha256,'1.0.0',%s,%s,now()
    FROM propertyscope_bocsar_import_stage WHERE record_kind='observation'
    ON CONFLICT (dataset_release_id,geography_kind,geography_value,source_category_key,month)
    DO NOTHING
"""

BOCSAR_COVERAGE_INSERT_SQL = """
    INSERT INTO warehouse.bocsar_coverage (
        dataset_release_id,geography_kind,geography_value,source_category_key,observed_months,
        first_month,last_month,month_count,blank_means_observed_zero,completeness_sha256,
        source_row_sha256,normalisation_version,artifact_record_id,ingestion_run_id,created_at
    ) SELECT %s,geography_kind,geography_value,source_category_key,observed_months,
        first_month,last_month,month_count,blank_means_observed_zero,completeness_sha256,
        source_row_sha256,'1.0.0',%s,%s,now()
    FROM propertyscope_bocsar_import_stage WHERE record_kind='coverage'
    ON CONFLICT (dataset_release_id,geography_kind,geography_value,source_category_key) DO NOTHING
"""
