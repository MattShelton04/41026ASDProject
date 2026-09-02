-- Register and store the complete NSW subset of the official ABS SEIFA 2021 SAL workbook.

CREATE TABLE warehouse.seifa_sal (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    sal_code TEXT NOT NULL CHECK (sal_code ~ '^1[0-9]{4}$'),
    sal_name TEXT NOT NULL,
    locality_name TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state = 'NSW'),
    reference_year SMALLINT NOT NULL CHECK (reference_year = 2021),
    irsd_score NUMERIC,
    irsd_australia_decile SMALLINT CHECK (irsd_australia_decile BETWEEN 1 AND 10),
    irsad_score NUMERIC,
    irsad_australia_decile SMALLINT CHECK (irsad_australia_decile BETWEEN 1 AND 10),
    ier_score NUMERIC,
    ier_australia_decile SMALLINT CHECK (ier_australia_decile BETWEEN 1 AND 10),
    ieo_score NUMERIC,
    ieo_australia_decile SMALLINT CHECK (ieo_australia_decile BETWEEN 1 AND 10),
    usual_resident_population BIGINT NOT NULL CHECK (usual_resident_population >= 0),
    source_row_sha256 TEXT NOT NULL CHECK (source_row_sha256 ~ '^[0-9a-f]{64}$'),
    normalisation_version TEXT NOT NULL,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dataset_release_id, sal_code),
    CHECK ((irsd_score IS NULL) = (irsd_australia_decile IS NULL)),
    CHECK ((irsad_score IS NULL) = (irsad_australia_decile IS NULL)),
    CHECK ((ier_score IS NULL) = (ier_australia_decile IS NULL)),
    CHECK ((ieo_score IS NULL) = (ieo_australia_decile IS NULL))
);
CREATE INDEX seifa_sal_locality_release_idx
    ON warehouse.seifa_sal (locality_name, dataset_release_id);

INSERT INTO ops.source_definition (
    id,name,publisher,source_url,adapter_key,cadence,licence_id,licence_url,
    redistribution_policy,target_features_json,status,notes,created_at,updated_at,version
) VALUES (
    '10000000-0000-0000-0000-000000000011',
    'ABS SEIFA 2021 NSW Suburbs and Localities',
    'Australian Bureau of Statistics',
    'https://www.abs.gov.au/statistics/people/people-and-communities/socio-economic-indexes-areas-seifa-australia/2021',
    'abs-seifa-xlsx','census-release-driven','cc-by-4-0',
    'https://www.abs.gov.au/website-privacy-copyright-and-disclaimer',
    'attributed-derived-release','["feature-1"]'::jsonb,'active',
    'Complete NSW subset of the national 2021 SAL index workbook. Based on Australian Bureau of Statistics data.',
    now(),now(),1
) ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.job_definition (
    id,source_definition_id,name,profile_key,profile_version,adapter_key,adapter_version,
    release_builder_key,release_builder_version,import_profile_key,import_profile_version,
    target_feature,dataset_id,refresh_strategy,default_run_mode,
    quality_policy_key,quality_policy_version,status,schedule_text,created_at,updated_at,version
) VALUES (
    '20000000-0000-0000-0000-000000000011',
    '10000000-0000-0000-0000-000000000011',
    'ABS SEIFA 2021 NSW suburb and locality indexes','abs-seifa-2021-sal-nsw','1.0.0',
    'abs-seifa-xlsx','1.0.0','seifa-area','1.0.0','seifa-2021-sal-nsw','1.0.0',
    'feature-1','abs-seifa-2021','full_snapshot','full_refresh',
    'abs-seifa-2021-sal-nsw','1.0.0','active',NULL,
    now(),now(),1
) ON CONFLICT (id) DO NOTHING;

-- Keep the new registration aligned if an operator created the stable job ID manually before
-- this migration. Earlier migration files remain immutable because deployed checksums are durable.
UPDATE ops.job_definition
SET release_builder_version = '1.0.0', updated_at = now(), version = version + 1
WHERE release_builder_key = 'seifa-area' AND release_builder_version <> '1.0.0';
