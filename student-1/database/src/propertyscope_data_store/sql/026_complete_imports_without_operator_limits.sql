-- Feature 1 imports the complete registered source without operator data-volume ceilings.
UPDATE ops.job_definition
SET scope_json = CASE import_profile_key
        WHEN 'bocsar-sparse' THEN '{"profile":"full-data","geography_kinds":["postcode","suburb"],"all_records":true,"release_scope":{"maximum_records":50000}}'::jsonb
        WHEN 'gnaf-nsw' THEN '{"profile":"full-data","state":"NSW","all_records":true,"release_scope":{"maximum_records":50000}}'::jsonb
        WHEN 'psi-sales' THEN '{"profile":"full-data","all_records":true,"all_history":true,"include_current_weekly":true,"release_scope":{"years":[2025],"maximum_records":250000}}'::jsonb
        WHEN 'schools-master' THEN '{"profile":"full-data","all_records":true,"release_scope":{"maximum_records":5000}}'::jsonb
        ELSE '{"profile":"full-data","all_records":true}'::jsonb
    END,
    updated_at = '2026-08-28T00:00:00Z',
    version = version + 1;

ALTER TABLE ops.job_definition
    DROP COLUMN max_parallelism,
    DROP COLUMN timeout_seconds,
    DROP COLUMN max_objects,
    DROP COLUMN max_bytes,
    DROP COLUMN max_rows;
