-- Replace the accidental showcase truncation with a complete, streaming PSI profile.
UPDATE ops.job_definition
SET name='NSW property sales complete history',
    scope_json='{"profile":"showcase","years":[2025],"partition_type":"source_year"}'::jsonb,
    max_objects=1000,
    max_bytes=20000000000,
    max_rows=100000000,
    timeout_seconds=86400,
    updated_at=now(),
    version=version+1
WHERE id='20000000-0000-0000-0000-000000000002';
