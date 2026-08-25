-- Treat live BOCSAR acquisition as a source-scale stream. The source archive remains
-- restricted to 50 MB by its registered transport; the larger bound covers canonical
-- sparse NDJSON produced from every geography/category/month in that archive.
UPDATE ops.job_definition
SET max_bytes=2500000000,
    timeout_seconds=86400,
    updated_at='2026-08-25T00:00:00Z',
    version=version+1
WHERE id='20000000-0000-0000-0000-000000000003';
