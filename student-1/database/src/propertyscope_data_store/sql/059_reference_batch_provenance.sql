-- Apply the existing warehouse provenance policy (050) to reference features too.
-- The owning loader validates the three metadata references once in the same transaction.
INSERT INTO warehouse.import_batch (dataset_release_id,artifact_record_id,ingestion_run_id)
SELECT DISTINCT dataset_release_id,artifact_record_id,ingestion_run_id
FROM warehouse.reference_feature ON CONFLICT DO NOTHING;

ALTER TABLE warehouse.reference_feature
    DROP CONSTRAINT reference_feature_dataset_release_id_fkey,
    DROP CONSTRAINT reference_feature_artifact_record_id_fkey,
    DROP CONSTRAINT reference_feature_ingestion_run_id_fkey;
