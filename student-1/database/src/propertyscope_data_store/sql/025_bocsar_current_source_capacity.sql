-- Reconcile the durable BOCSAR job with the current complete-source profile.
-- The August 2026 archives contain 318,122 wide rows and expand to 10,114,565
-- sparse observations plus coverage records before the bounded release projection.
UPDATE ops.job_definition
SET max_objects=4,
    max_bytes=5000000000,
    max_rows=15000000,
    timeout_seconds=86400,
    updated_at='2026-08-25T00:00:00Z',
    version=version+1
WHERE id='20000000-0000-0000-0000-000000000003';
