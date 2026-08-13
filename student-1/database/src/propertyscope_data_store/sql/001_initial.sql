CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS registry;
CREATE SCHEMA IF NOT EXISTS warehouse;
CREATE SCHEMA IF NOT EXISTS serving;
CREATE SCHEMA IF NOT EXISTS stage;

CREATE TABLE ops.source_definition (
    id UUID PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    publisher TEXT NOT NULL,
    source_url TEXT NOT NULL,
    adapter_key TEXT NOT NULL,
    cadence TEXT NOT NULL,
    licence_id TEXT NOT NULL,
    licence_url TEXT NOT NULL,
    redistribution_policy TEXT NOT NULL,
    target_features_json JSONB NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK (status IN ('draft','active','disabled','retired')),
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)
);

CREATE TABLE ops.job_definition (
    id UUID PRIMARY KEY,
    source_definition_id UUID NOT NULL REFERENCES ops.source_definition(id) ON DELETE RESTRICT,
    name TEXT NOT NULL UNIQUE,
    profile_key TEXT NOT NULL,
    profile_version TEXT NOT NULL,
    adapter_key TEXT NOT NULL,
    release_builder_key TEXT NOT NULL,
    import_profile_key TEXT NOT NULL,
    import_profile_version TEXT NOT NULL,
    target_feature TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    refresh_strategy TEXT NOT NULL CHECK (refresh_strategy IN ('full_snapshot','append_only_partitioned','partitioned_snapshot','manual_versioned_import')),
    default_run_mode TEXT NOT NULL CHECK (default_run_mode IN ('full_refresh','reprocess_cached')),
    scope_json JSONB NOT NULL,
    quality_policy_key TEXT NOT NULL,
    quality_policy_version TEXT NOT NULL,
    max_parallelism INTEGER NOT NULL CHECK (max_parallelism BETWEEN 1 AND 16),
    timeout_seconds INTEGER NOT NULL CHECK (timeout_seconds BETWEEN 1 AND 86400),
    max_objects INTEGER NOT NULL CHECK (max_objects BETWEEN 1 AND 100000),
    max_bytes BIGINT NOT NULL CHECK (max_bytes > 0),
    max_rows BIGINT NOT NULL CHECK (max_rows > 0),
    status TEXT NOT NULL CHECK (status IN ('draft','active','disabled','retired')),
    schedule_text TEXT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    UNIQUE (profile_key, profile_version)
);

CREATE TABLE ops.ingestion_run (
    id UUID PRIMARY KEY,
    job_definition_id UUID NOT NULL REFERENCES ops.job_definition(id) ON DELETE RESTRICT,
    source_definition_id UUID NOT NULL REFERENCES ops.source_definition(id) ON DELETE RESTRICT,
    adapter_version TEXT NOT NULL,
    release_builder_version TEXT NOT NULL,
    import_profile_version TEXT NOT NULL,
    normalisation_version TEXT NOT NULL,
    profile_key TEXT NOT NULL,
    run_mode TEXT NOT NULL CHECK (run_mode IN ('full_refresh','reprocess_cached')),
    requested_scope_json JSONB NOT NULL,
    source_snapshot_json JSONB,
    input_checkpoint_json JSONB,
    output_checkpoint_json JSONB,
    accepted_watermark_json JSONB,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    parent_run_id UUID REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    requested_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('queued','planning','discovering','acquiring','staging','normalising','validating','building_release','succeeded','failed','cancelled','interrupted')),
    rows_discovered BIGINT NOT NULL DEFAULT 0 CHECK (rows_discovered >= 0),
    rows_staged BIGINT NOT NULL DEFAULT 0 CHECK (rows_staged >= 0),
    rows_accepted BIGINT NOT NULL DEFAULT 0 CHECK (rows_accepted >= 0),
    rows_rejected BIGINT NOT NULL DEFAULT 0 CHECK (rows_rejected >= 0),
    error_json JSONB,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    cancel_requested_at TIMESTAMPTZ,
    request_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (job_definition_id, idempotency_key),
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);

CREATE TABLE ops.run_task (
    id UUID PRIMARY KEY,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL,
    partition_json JSONB NOT NULL,
    stage TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','claimed','running','retry_wait','succeeded','failed','cancelled','skipped')),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    input_artifact_id UUID,
    output_artifact_id UUID,
    rows_in BIGINT NOT NULL DEFAULT 0 CHECK (rows_in >= 0),
    rows_out BIGINT NOT NULL DEFAULT 0 CHECK (rows_out >= 0),
    error_json JSONB,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    UNIQUE (ingestion_run_id, logical_key, stage),
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);

CREATE TABLE ops.artifact_record (
    id UUID PRIMARY KEY,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    run_task_id UUID REFERENCES ops.run_task(id) ON DELETE RESTRICT,
    logical_key TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    source_uri_redacted TEXT,
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    media_type TEXT NOT NULL,
    bytes BIGINT NOT NULL CHECK (bytes >= 0),
    etag TEXT,
    source_last_modified TIMESTAMPTZ,
    schema_version TEXT,
    retention_class TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (content_sha256, artifact_kind),
    UNIQUE (storage_key)
);

ALTER TABLE ops.run_task
    ADD CONSTRAINT run_task_input_artifact_fk FOREIGN KEY (input_artifact_id) REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ADD CONSTRAINT run_task_output_artifact_fk FOREIGN KEY (output_artifact_id) REFERENCES ops.artifact_record(id) ON DELETE RESTRICT;

CREATE TABLE ops.dataset_release (
    id UUID PRIMARY KEY,
    dataset_id TEXT NOT NULL,
    source_definition_id UUID NOT NULL REFERENCES ops.source_definition(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    target_feature TEXT NOT NULL,
    release_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    coverage_json JSONB NOT NULL,
    record_count BIGINT NOT NULL CHECK (record_count >= 0),
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    manifest_json JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft','candidate','awaiting_review','accepted','rejected','superseded')),
    review_comment TEXT,
    accepted_at TIMESTAMPTZ,
    supersedes_release_id UUID REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    UNIQUE (dataset_id, target_feature, release_version)
);
CREATE UNIQUE INDEX dataset_release_one_accepted_idx
    ON ops.dataset_release (target_feature, dataset_id) WHERE status = 'accepted';

CREATE TABLE ops.import_operation (
    id UUID PRIMARY KEY,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    run_task_id UUID NOT NULL UNIQUE REFERENCES ops.run_task(id) ON DELETE RESTRICT,
    candidate_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    import_profile_key TEXT NOT NULL,
    import_profile_version TEXT NOT NULL,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN ('planned','queued','claimed','running','succeeded','failed','cancelled','interrupted')),
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    requested_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    rows_in BIGINT NOT NULL DEFAULT 0 CHECK (rows_in >= 0),
    rows_staged BIGINT NOT NULL DEFAULT 0 CHECK (rows_staged >= 0),
    rows_accepted BIGINT NOT NULL DEFAULT 0 CHECK (rows_accepted >= 0),
    rows_rejected BIGINT NOT NULL DEFAULT 0 CHECK (rows_rejected >= 0),
    result_json JSONB,
    error_json JSONB,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);

CREATE TABLE ops.quality_result (
    id UUID PRIMARY KEY,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    dataset_release_id UUID REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    rule_key TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    dimension TEXT NOT NULL CHECK (dimension IN ('schema','conformance','completeness','validity','uniqueness','consistency','timeliness','freshness','coverage','referential','match_quality','distribution','drift','lineage','reproducibility')),
    severity TEXT NOT NULL CHECK (severity IN ('info','warning','blocking')),
    status TEXT NOT NULL CHECK (status IN ('pass','warn','fail','skipped_with_reason')),
    observed_value_json JSONB NOT NULL,
    expected_value_json JSONB,
    message TEXT NOT NULL,
    sample_json JSONB,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (ingestion_run_id, rule_key)
);

CREATE TABLE ops.publication_receipt (
    id UUID PRIMARY KEY,
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    target_feature TEXT NOT NULL,
    consumer_operation_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending','accepted','rejected','failed')),
    schema_version TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    rows_received BIGINT NOT NULL CHECK (rows_received >= 0),
    rows_accepted BIGINT NOT NULL CHECK (rows_accepted >= 0),
    rows_rejected BIGINT NOT NULL CHECK (rows_rejected >= 0),
    error_json JSONB,
    request_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    UNIQUE (target_feature, consumer_operation_id)
);

CREATE TABLE registry.property (
    property_ref UUID PRIMARY KEY,
    address_display TEXT NOT NULL,
    flat_type TEXT,
    unit_number TEXT,
    street_number_first INTEGER,
    street_number_suffix TEXT,
    street_number_last INTEGER,
    street_name TEXT NOT NULL,
    street_type TEXT,
    locality TEXT NOT NULL,
    postcode TEXT NOT NULL CHECK (postcode ~ '^[0-9]{4}$'),
    state TEXT NOT NULL CHECK (state = 'NSW'),
    address_search TEXT NOT NULL,
    geom geometry(Point, 4326) NOT NULL,
    resolution_status TEXT NOT NULL CHECK (resolution_status IN ('verified','provisional','unresolved','retired')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    CHECK (ST_X(geom) BETWEEN 140 AND 154),
    CHECK (ST_Y(geom) BETWEEN -38 AND -27)
);
CREATE INDEX property_search_trgm_idx ON registry.property USING gin (address_search gin_trgm_ops);
CREATE INDEX property_geom_gist_idx ON registry.property USING gist (geom);
CREATE INDEX property_locality_postcode_idx ON registry.property (locality, postcode);

CREATE TABLE registry.property_identifier (
    id UUID PRIMARY KEY,
    property_ref UUID NOT NULL REFERENCES registry.property(property_ref) ON DELETE RESTRICT,
    scheme TEXT NOT NULL,
    identifier_value TEXT NOT NULL,
    source_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    is_current BOOLEAN NOT NULL,
    valid_from DATE,
    valid_to DATE,
    match_method TEXT NOT NULL,
    match_confidence NUMERIC(5,4) NOT NULL CHECK (match_confidence BETWEEN 0 AND 1),
    evidence_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (scheme, identifier_value, source_release_id)
);

CREATE TABLE registry.address_alias (
    id UUID PRIMARY KEY,
    property_ref UUID NOT NULL REFERENCES registry.property(property_ref) ON DELETE RESTRICT,
    alias_display TEXT NOT NULL,
    alias_search TEXT NOT NULL,
    alias_kind TEXT NOT NULL,
    source_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    source_identifier TEXT,
    is_current BOOLEAN NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (property_ref, alias_search, source_release_id)
);
CREATE INDEX address_alias_search_trgm_idx ON registry.address_alias USING gin (alias_search gin_trgm_ops);

CREATE TABLE registry.unresolved_match (
    id UUID PRIMARY KEY,
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    source_record_key TEXT NOT NULL,
    source_address_json JSONB NOT NULL,
    candidate_property_refs JSONB NOT NULL,
    reason_code TEXT NOT NULL,
    resolver_key TEXT NOT NULL,
    resolver_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open','resolved','dismissed')),
    review_comment TEXT,
    resolved_property_ref UUID REFERENCES registry.property(property_ref) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    UNIQUE (dataset_release_id, source_record_key)
);

CREATE TABLE warehouse.gnaf_address (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    gnaf_pid TEXT NOT NULL,
    property_ref UUID REFERENCES registry.property(property_ref) ON DELETE RESTRICT,
    address_display TEXT NOT NULL,
    locality TEXT NOT NULL,
    postcode TEXT NOT NULL,
    source_status TEXT NOT NULL,
    geocode_type TEXT NOT NULL,
    source_crs INTEGER NOT NULL,
    geom geometry(Point,4326) NOT NULL,
    source_row_sha256 TEXT NOT NULL,
    normalisation_version TEXT NOT NULL,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dataset_release_id, gnaf_pid)
);
CREATE INDEX gnaf_address_geom_idx ON warehouse.gnaf_address USING gist (geom);
CREATE INDEX gnaf_address_lookup_idx ON warehouse.gnaf_address (postcode, locality, gnaf_pid);

CREATE TABLE warehouse.psi_sale (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    source_business_key TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    source_era TEXT NOT NULL,
    district_code TEXT,
    property_id TEXT,
    dealing_id TEXT,
    contract_date DATE,
    settlement_date DATE,
    price_aud BIGINT,
    area_original NUMERIC,
    area_unit TEXT,
    area_square_metres NUMERIC,
    property_ref UUID REFERENCES registry.property(property_ref) ON DELETE RESTRICT,
    match_tier TEXT NOT NULL,
    match_confidence NUMERIC(5,4) NOT NULL,
    geographic_precision TEXT NOT NULL,
    source_row_sha256 TEXT NOT NULL,
    normalisation_version TEXT NOT NULL,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dataset_release_id, source_business_key, source_revision)
);
CREATE INDEX psi_sale_property_date_idx ON warehouse.psi_sale (property_ref, contract_date);

CREATE TABLE warehouse.bocsar_observation (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    geography_kind TEXT NOT NULL,
    geography_value TEXT NOT NULL,
    source_category_key TEXT NOT NULL,
    offence_label TEXT NOT NULL,
    subcategory_label TEXT NOT NULL,
    month DATE NOT NULL,
    count INTEGER NOT NULL CHECK (count > 0),
    source_row_sha256 TEXT NOT NULL,
    normalisation_version TEXT NOT NULL,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dataset_release_id, geography_kind, geography_value, source_category_key, month)
);

CREATE TABLE warehouse.bocsar_coverage (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    geography_kind TEXT NOT NULL,
    geography_value TEXT NOT NULL,
    source_category_key TEXT NOT NULL,
    observed_months DATE[] NOT NULL,
    first_month DATE NOT NULL,
    last_month DATE NOT NULL,
    month_count INTEGER NOT NULL CHECK (month_count > 0),
    blank_means_observed_zero BOOLEAN NOT NULL,
    completeness_sha256 TEXT NOT NULL,
    source_row_sha256 TEXT NOT NULL,
    normalisation_version TEXT NOT NULL,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dataset_release_id, geography_kind, geography_value, source_category_key)
);

CREATE TABLE warehouse.school (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    school_code TEXT NOT NULL,
    school_name TEXT NOT NULL,
    school_type TEXT NOT NULL,
    status TEXT NOT NULL,
    locality_original TEXT NOT NULL,
    locality_normalised TEXT NOT NULL,
    lga_name TEXT,
    geom geometry(Point,4326) NOT NULL,
    source_row_sha256 TEXT NOT NULL,
    normalisation_version TEXT NOT NULL,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dataset_release_id, school_code)
);
CREATE INDEX school_geom_idx ON warehouse.school USING gist (geom);

CREATE TABLE warehouse.spatial_feature (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    dataset_key TEXT NOT NULL,
    layer_key TEXT NOT NULL,
    source_feature_key TEXT NOT NULL,
    native_crs INTEGER NOT NULL,
    source_extent_json JSONB NOT NULL,
    source_geom geometry(Geometry),
    wgs84_geom geometry(Geometry,4326) NOT NULL,
    effective_from DATE,
    effective_to DATE,
    source_attributes JSONB NOT NULL,
    geometry_transform_version TEXT NOT NULL,
    source_row_sha256 TEXT NOT NULL,
    normalisation_version TEXT NOT NULL,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (dataset_release_id, dataset_key, layer_key, source_feature_key)
);
CREATE INDEX spatial_feature_geom_idx ON warehouse.spatial_feature USING gist (wgs84_geom);

CREATE TABLE serving.accepted_generation (
    dataset_id TEXT NOT NULL,
    target_feature TEXT NOT NULL,
    dataset_release_id UUID NOT NULL UNIQUE REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    activated_at TIMESTAMPTZ NOT NULL,
    activated_by TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (dataset_id, target_feature)
);

CREATE TABLE serving.property_coverage (
    property_ref UUID NOT NULL REFERENCES registry.property(property_ref) ON DELETE RESTRICT,
    dataset_id TEXT NOT NULL,
    target_feature TEXT NOT NULL,
    dataset_release_id UUID REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    coverage_status TEXT NOT NULL CHECK (coverage_status IN ('supported','partial','unavailable','stale')),
    coverage_scope JSONB NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (property_ref, dataset_id, target_feature)
);

CREATE TABLE ops.idempotency_record (
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    response_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, idempotency_key)
);

CREATE INDEX run_status_requested_idx ON ops.ingestion_run (status, requested_at);
CREATE INDEX task_claim_idx ON ops.run_task (status, created_at);
CREATE INDEX import_claim_idx ON ops.import_operation (status, requested_at);
CREATE INDEX quality_release_idx ON ops.quality_result (dataset_release_id, severity, status);
