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
        WHERE source.property_ref IS NULL
          AND source.postcode IS NOT NULL
          AND source.locality IS NOT NULL
          AND source.street_name_normalised IS NOT NULL
          AND source.street_type IS NOT NULL
          AND source.street_number_first IS NOT NULL
          AND source.house_number ~ '^[0-9]+[A-Z]?(-[0-9]+)?$'
    )
    SELECT eligible.postcode,eligible.locality,eligible.street_name_normalised,
        eligible.street_type,eligible.street_number_first,eligible.street_number_last,
        eligible.street_number_suffix,eligible.unit_number,
        CASE WHEN gnaf_match.match_count>0
            THEN gnaf_match.match_count ELSE registry_match.match_count END AS match_count,
        CASE WHEN gnaf_match.match_count>0
            THEN gnaf_match.exact_property_ref ELSE registry_match.exact_property_ref
        END AS exact_property_ref,
        gnaf_match.gnaf_pid,gnaf_match.gnaf_release_id
    FROM eligible_addresses eligible
    CROSS JOIN LATERAL (
        SELECT count(DISTINCT COALESCE(address.property_ref,
                md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid))::integer AS match_count,
            CASE WHEN count(DISTINCT COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid))=1
                THEN min(COALESCE(address.property_ref,
                    md5('propertyscope-gnaf:' || address.gnaf_pid)::uuid)::text)::uuid
                ELSE NULL
            END AS exact_property_ref,
            min(address.gnaf_pid) AS gnaf_pid,
            min(address.dataset_release_id::text)::uuid AS gnaf_release_id
        FROM warehouse.gnaf_address address
        WHERE address.dataset_release_id=(
                SELECT accepted.dataset_release_id
                FROM serving.accepted_generation accepted
                WHERE accepted.dataset_id='gnaf-nsw'
            )
          AND address.published
          AND address.street_name IS NOT NULL
          AND address.street_type IS NOT NULL
          AND address.street_number_first IS NOT NULL
          AND address.postcode=eligible.postcode
          AND address.locality=eligible.locality
          AND address.street_name=eligible.street_name_normalised
          AND address.street_type=ANY(ARRAY[eligible.street_type,
              CASE eligible.street_type
                  WHEN 'AV' THEN 'AVENUE' WHEN 'CL' THEN 'CLOSE'
                  WHEN 'CT' THEN 'COURT' WHEN 'CR' THEN 'CRESCENT'
                  WHEN 'DR' THEN 'DRIVE' WHEN 'HWY' THEN 'HIGHWAY'
                  WHEN 'LANE' THEN 'LANE' WHEN 'PDE' THEN 'PARADE'
                  WHEN 'PL' THEN 'PLACE' WHEN 'RD' THEN 'ROAD'
                  WHEN 'ST' THEN 'STREET' WHEN 'TCE' THEN 'TERRACE'
              END])
          AND address.street_number_first=eligible.street_number_first
          AND COALESCE(address.street_number_last,-1)=COALESCE(
              eligible.street_number_last,-1)
          AND COALESCE(address.street_number_suffix,'')=COALESCE(
              eligible.street_number_suffix,'')
          AND COALESCE(address.unit_number,'')=COALESCE(eligible.unit_number,'')
    ) gnaf_match
    CROSS JOIN LATERAL (
        SELECT count(DISTINCT property.property_ref)::integer AS match_count,
            CASE WHEN count(DISTINCT property.property_ref)=1
                THEN min(property.property_ref::text)::uuid ELSE NULL
            END AS exact_property_ref
        FROM registry.property property
        WHERE gnaf_match.match_count=0
          AND NOT EXISTS (
              SELECT 1 FROM registry.property_identifier identifier
              WHERE identifier.property_ref=property.property_ref AND identifier.scheme='gnaf_pid'
          )
          AND property.postcode=eligible.postcode
          AND property.locality=eligible.locality
          AND property.street_name=eligible.street_name_normalised
          AND property.street_type=eligible.street_type
          AND property.street_number_first=eligible.street_number_first
          AND COALESCE(property.street_number_last,-1)=COALESCE(
              eligible.street_number_last,-1)
          AND COALESCE(property.street_number_suffix,'')=COALESCE(
              eligible.street_number_suffix,'')
          AND COALESCE(property.unit_number,'')=COALESCE(eligible.unit_number,'')
    ) registry_match
"""

# Accepted G-NAF identities are normally virtual. Materialise only the unique identities
# referenced by this import, with provenance, so PSI retains its registry foreign key.
# These anchors never update canonical fields and are excluded from legacy read fallbacks.
PSI_TARGET_INSERT_SQL = """
    WITH matched_addresses AS MATERIALIZED (
        SELECT DISTINCT ON (resolution.exact_property_ref)
            resolution.exact_property_ref,address.*
        FROM propertyscope_psi_address_resolution resolution
        JOIN warehouse.gnaf_address address
          ON address.dataset_release_id=resolution.gnaf_release_id
         AND address.gnaf_pid=resolution.gnaf_pid
        WHERE resolution.match_count=1 AND address.published
        ORDER BY resolution.exact_property_ref,address.gnaf_pid
    ), inserted_properties AS (
        INSERT INTO registry.property (
            property_ref,address_display,flat_type,unit_number,street_number_first,
            street_number_suffix,street_number_last,street_name,street_type,locality,
            postcode,state,address_search,geom,resolution_status,created_at,updated_at,version
        ) SELECT exact_property_ref,address_display,flat_type,unit_number,street_number_first,
            street_number_suffix,street_number_last,COALESCE(street_name,address_display),
            street_type,locality,postcode,'NSW',
            trim(regexp_replace(lower(address_display),'[^a-z0-9]+',' ','g')),geom,
            CASE WHEN source_status='CURRENT' THEN 'verified' ELSE 'retired' END,
            now(),now(),1
        FROM matched_addresses
        ON CONFLICT (property_ref) DO NOTHING
        RETURNING property_ref
    ), inserted_identifiers AS (
        INSERT INTO registry.property_identifier (
            id,property_ref,scheme,identifier_value,source_release_id,is_current,
            valid_from,valid_to,match_method,match_confidence,evidence_json,created_at
        ) SELECT md5('propertyscope-gnaf_pid-identifier:' || address.dataset_release_id::text
                || ':' || address.gnaf_pid)::uuid,
            address.exact_property_ref,'gnaf_pid',address.gnaf_pid,address.dataset_release_id,
            true,now()::date,NULL,'source-authoritative',1,
            jsonb_build_object('identity_anchor','psi-accepted-gnaf',
                'geocode_type',address.geocode_type,'source_crs',address.source_crs),now()
        FROM matched_addresses address
        JOIN inserted_properties inserted ON inserted.property_ref=address.exact_property_ref
        ON CONFLICT (scheme,identifier_value,source_release_id) DO NOTHING
    )
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
    ) WITH first_records AS (
        SELECT geography_kind,geography_value,source_category_key,month,min(ordinal) AS ordinal
        FROM propertyscope_bocsar_import_stage
        WHERE record_kind='observation'
        GROUP BY geography_kind,geography_value,source_category_key,month
    ) SELECT %s,source.geography_kind,source.geography_value,source.source_category_key,
        source.offence_label,source.subcategory_label,source.month,source.count,
        source.source_row_sha256,'1.0.0',%s,%s,now()
    FROM first_records first
    JOIN propertyscope_bocsar_import_stage source USING (
        geography_kind,geography_value,source_category_key,month,ordinal
    )
    ON CONFLICT (dataset_release_id,geography_kind,geography_value,source_category_key,month)
    DO NOTHING
"""

BOCSAR_COVERAGE_INSERT_SQL = """
    INSERT INTO warehouse.bocsar_coverage (
        dataset_release_id,geography_kind,geography_value,source_category_key,observed_months,
        first_month,last_month,month_count,blank_means_observed_zero,completeness_sha256,
        source_row_sha256,normalisation_version,artifact_record_id,ingestion_run_id,created_at
    ) WITH first_records AS (
        SELECT geography_kind,geography_value,source_category_key,min(ordinal) AS ordinal
        FROM propertyscope_bocsar_import_stage
        WHERE record_kind='coverage'
        GROUP BY geography_kind,geography_value,source_category_key
    ) SELECT %s,source.geography_kind,source.geography_value,source.source_category_key,
        source.observed_months,source.first_month,source.last_month,source.month_count,
        source.blank_means_observed_zero,source.completeness_sha256,source.source_row_sha256,
        '1.0.0',%s,%s,now()
    FROM first_records first
    JOIN propertyscope_bocsar_import_stage source USING (
        geography_kind,geography_value,source_category_key,ordinal
    )
    ON CONFLICT (dataset_release_id,geography_kind,geography_value,source_category_key) DO NOTHING
"""
