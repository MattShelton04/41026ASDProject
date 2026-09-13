-- Feature 1 owns publisher reference facts. Consumer interpretation is deliberately separate.
CREATE TABLE warehouse.reference_feature (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    record_id TEXT NOT NULL,
    layer TEXT NOT NULL,
    name TEXT,
    geometry_json JSONB,
    geom geometry(Geometry,4326),
    geometry_status TEXT GENERATED ALWAYS AS (
        CASE WHEN geom IS NULL THEN 'not_provided'
             WHEN ST_IsValid(geom) THEN 'valid' ELSE 'invalid' END
    ) STORED,
    attributes JSONB NOT NULL CHECK (jsonb_typeof(attributes)='object'),
    source_url TEXT NOT NULL,
    source_crs TEXT NOT NULL,
    source_updated_at TEXT,
    valid_from TEXT,
    valid_to TEXT,
    source_row_sha256 TEXT NOT NULL CHECK (source_row_sha256 ~ '^[0-9a-f]{64}$'),
    normalisation_version TEXT NOT NULL,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (dataset_release_id,layer,record_id),
    CHECK ((geometry_json IS NULL)=(geom IS NULL))
);
CREATE INDEX reference_feature_geom_idx ON warehouse.reference_feature USING gist(geom)
    WHERE geometry_status='valid';

