-- Provenance is constant within an import batch. Validate and retain it once,
-- rather than firing three metadata foreign-key triggers for every warehouse row.
-- Only the owning database loader writes warehouse facts; it registers this batch
-- in the same transaction before COPY. Row-level property identity FKs remain.
CREATE TABLE warehouse.import_batch (
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    artifact_record_id UUID NOT NULL REFERENCES ops.artifact_record(id) ON DELETE RESTRICT,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE RESTRICT,
    PRIMARY KEY (dataset_release_id, artifact_record_id, ingestion_run_id)
);

DO $$
DECLARE
    target TEXT;
BEGIN
    FOREACH target IN ARRAY ARRAY[
        'gnaf_address', 'psi_sale', 'bocsar_observation', 'bocsar_coverage',
        'school', 'spatial_feature', 'seifa_sal'
    ] LOOP
        EXECUTE format(
            'INSERT INTO warehouse.import_batch SELECT DISTINCT dataset_release_id, '
            'artifact_record_id, ingestion_run_id FROM warehouse.%I ON CONFLICT DO NOTHING',
            target
        );
        EXECUTE format(
            'ALTER TABLE warehouse.%I DROP CONSTRAINT %I, DROP CONSTRAINT %I, DROP CONSTRAINT %I',
            target, target || '_dataset_release_id_fkey',
            target || '_artifact_record_id_fkey', target || '_ingestion_run_id_fkey'
        );
    END LOOP;
END $$;
