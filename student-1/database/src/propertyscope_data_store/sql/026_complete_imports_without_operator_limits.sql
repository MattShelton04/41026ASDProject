-- Feature 1 imports the complete registered source without operator data-volume ceilings.
ALTER TABLE ops.job_definition
    DROP COLUMN scope_json,
    DROP COLUMN max_parallelism,
    DROP COLUMN timeout_seconds,
    DROP COLUMN max_objects,
    DROP COLUMN max_bytes,
    DROP COLUMN max_rows;
