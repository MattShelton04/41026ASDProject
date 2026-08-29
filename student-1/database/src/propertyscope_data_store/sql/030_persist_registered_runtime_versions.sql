-- A run must snapshot the registered adapter and builder versions instead of assuming every
-- implementation remains at 1.0.0.
ALTER TABLE ops.job_definition
    ADD COLUMN adapter_version TEXT NOT NULL DEFAULT '1.0.0',
    ADD COLUMN release_builder_version TEXT NOT NULL DEFAULT '1.0.0';

UPDATE ops.job_definition
SET release_builder_version='2.0.0',updated_at=now(),version=version+1
WHERE release_builder_key='property-sales';
