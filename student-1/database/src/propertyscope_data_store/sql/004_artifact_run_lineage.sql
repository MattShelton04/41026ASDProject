-- The content-addressed physical object may be shared, but every run retains its own
-- immutable lineage record. The original global unique constraints made a repeated
-- payload incorrectly resolve to an artifact owned by an earlier run.
ALTER TABLE ops.artifact_record
    DROP CONSTRAINT IF EXISTS artifact_record_content_sha256_artifact_kind_key,
    DROP CONSTRAINT IF EXISTS artifact_record_storage_key_key;

CREATE UNIQUE INDEX artifact_record_run_logical_kind_uq
    ON ops.artifact_record (ingestion_run_id, logical_key, artifact_kind);

CREATE INDEX artifact_record_content_lookup_idx
    ON ops.artifact_record (content_sha256, artifact_kind);

CREATE INDEX artifact_record_storage_lookup_idx
    ON ops.artifact_record (storage_key);
