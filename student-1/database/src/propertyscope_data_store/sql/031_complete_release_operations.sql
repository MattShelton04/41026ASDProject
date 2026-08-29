-- Complete release exports, truthful durable progress, terminal candidates, and physical deduplication.

ALTER TABLE ops.dataset_release DROP CONSTRAINT IF EXISTS dataset_release_status_check;
ALTER TABLE ops.dataset_release ADD CONSTRAINT dataset_release_status_check
    CHECK (status IN ('draft','candidate','awaiting_review','accepted','rejected','superseded','abandoned'));
ALTER TABLE ops.dataset_release ADD COLUMN terminal_reason_json JSONB;
ALTER TABLE ops.dataset_release ADD CONSTRAINT dataset_release_terminal_reason_check CHECK (
    (status = 'abandoned' AND terminal_reason_json IS NOT NULL)
    OR (status <> 'abandoned' AND terminal_reason_json IS NULL)
);

ALTER TABLE ops.run_task
    ADD COLUMN progress_phase TEXT,
    ADD COLUMN progress_rows BIGINT NOT NULL DEFAULT 0 CHECK (progress_rows >= 0),
    ADD COLUMN progress_bytes BIGINT NOT NULL DEFAULT 0 CHECK (progress_bytes >= 0),
    ADD COLUMN progress_total_rows BIGINT CHECK (progress_total_rows IS NULL OR progress_total_rows >= 0),
    ADD COLUMN progress_total_bytes BIGINT CHECK (progress_total_bytes IS NULL OR progress_total_bytes >= 0),
    ADD COLUMN progress_updated_at TIMESTAMPTZ;

ALTER TABLE ops.import_operation
    ADD COLUMN progress_phase TEXT,
    ADD COLUMN progress_rows BIGINT NOT NULL DEFAULT 0 CHECK (progress_rows >= 0),
    ADD COLUMN progress_bytes BIGINT NOT NULL DEFAULT 0 CHECK (progress_bytes >= 0),
    ADD COLUMN progress_total_rows BIGINT CHECK (progress_total_rows IS NULL OR progress_total_rows >= 0),
    ADD COLUMN progress_total_bytes BIGINT CHECK (progress_total_bytes IS NULL OR progress_total_bytes >= 0),
    ADD COLUMN progress_updated_at TIMESTAMPTZ;

-- Artifact records are lineage references. Multiple runs may point at one immutable
-- content-addressed storage key without copying the physical bytes.
ALTER TABLE ops.artifact_record
    DROP CONSTRAINT IF EXISTS artifact_record_content_sha256_artifact_kind_key,
    DROP CONSTRAINT IF EXISTS artifact_record_storage_key_key;
CREATE UNIQUE INDEX artifact_record_run_logical_kind_idx
    ON ops.artifact_record (ingestion_run_id, logical_key, artifact_kind);
CREATE INDEX artifact_record_storage_reference_idx
    ON ops.artifact_record (storage_key, content_sha256);

-- Existing cancelled/failed ingestion-owned empty drafts are audit evidence, not
-- manually actionable drafts. The runtime applies the same transition immediately.
UPDATE ops.dataset_release release
SET status='abandoned',
    terminal_reason_json=jsonb_build_object(
        'code', CASE WHEN run.status='cancelled' THEN 'ingestion_cancelled' ELSE 'ingestion_failed' END,
        'message', 'Candidate release was abandoned because its owning ingestion did not complete',
        'ingestion_run_id', run.id,
        'run_status', run.status,
        'bounded_error', COALESCE(run.error_json, '{}'::jsonb)
    ),
    review_comment='System-terminalized ingestion candidate; retained for audit evidence.',
    updated_at=GREATEST(release.updated_at,COALESCE(run.finished_at,now())),
    version=release.version+1
FROM ops.ingestion_run run
WHERE release.ingestion_run_id=run.id
  AND release.status IN ('draft','candidate')
  AND run.status IN ('cancelled','failed')
  AND NOT EXISTS (
      SELECT 1 FROM ops.publication_receipt receipt
      WHERE receipt.dataset_release_id=release.id
  );
