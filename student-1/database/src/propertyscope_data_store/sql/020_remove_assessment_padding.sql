-- Remove catalogue and orchestration rows that existed only to pad every showcase table.
-- The deterministic fixture-property product remains available for repeatable offline runs.
CREATE TEMP TABLE retired_assessment_source (id UUID PRIMARY KEY) ON COMMIT DROP;
INSERT INTO retired_assessment_source (id) VALUES
    ('10000000-0000-0000-0000-000000000005'),
    ('10000000-0000-0000-0000-000000000006'),
    ('10000000-0000-0000-0000-000000000007'),
    ('10000000-0000-0000-0000-000000000008'),
    ('10000000-0000-0000-0000-000000000009');

DELETE FROM serving.property_coverage coverage
USING ops.dataset_release release,retired_assessment_source source
WHERE coverage.dataset_release_id=release.id
  AND release.source_definition_id=source.id;

DELETE FROM serving.accepted_generation accepted
USING ops.dataset_release release,retired_assessment_source source
WHERE accepted.dataset_release_id=release.id
  AND release.source_definition_id=source.id;

DELETE FROM warehouse.spatial_feature feature
USING ops.dataset_release release,retired_assessment_source source
WHERE feature.dataset_release_id=release.id
  AND release.source_definition_id=source.id;

DELETE FROM ops.publication_receipt receipt
USING ops.dataset_release release,retired_assessment_source source
WHERE receipt.dataset_release_id=release.id
  AND release.source_definition_id=source.id;

DELETE FROM ops.quality_result quality
USING ops.ingestion_run run,retired_assessment_source source
WHERE quality.ingestion_run_id=run.id
  AND run.source_definition_id=source.id;

DELETE FROM ops.import_operation operation
USING ops.ingestion_run run,retired_assessment_source source
WHERE operation.ingestion_run_id=run.id
  AND run.source_definition_id=source.id;

DELETE FROM ops.dataset_release release
USING retired_assessment_source source
WHERE release.source_definition_id=source.id;

UPDATE ops.run_task task
SET input_artifact_id=NULL,output_artifact_id=NULL
FROM ops.ingestion_run run,retired_assessment_source source
WHERE task.ingestion_run_id=run.id
  AND run.source_definition_id=source.id;

DELETE FROM ops.artifact_record artifact
USING ops.ingestion_run run,retired_assessment_source source
WHERE artifact.ingestion_run_id=run.id
  AND run.source_definition_id=source.id;

DELETE FROM ops.run_task task
USING ops.ingestion_run run,retired_assessment_source source
WHERE task.ingestion_run_id=run.id
  AND run.source_definition_id=source.id;

DELETE FROM ops.ingestion_run run
USING retired_assessment_source source
WHERE run.source_definition_id=source.id;

DELETE FROM ops.job_definition job
USING retired_assessment_source source
WHERE job.source_definition_id=source.id;

DELETE FROM ops.source_definition definition
USING retired_assessment_source source
WHERE definition.id=source.id;
