-- Align persisted operator limits with the reviewed R0 job profiles.
UPDATE ops.job_definition
SET max_bytes=2500000000,max_rows=6500000,timeout_seconds=86400,updated_at=now(),version=version+1
WHERE id='20000000-0000-0000-0000-000000000001';

UPDATE ops.job_definition
SET max_bytes=5000000000,max_rows=10000000,timeout_seconds=86400,updated_at=now(),version=version+1
WHERE id='20000000-0000-0000-0000-000000000002';

UPDATE ops.job_definition
SET max_bytes=50000000,max_rows=100000,timeout_seconds=900,updated_at=now(),version=version+1
WHERE id='20000000-0000-0000-0000-000000000003';

UPDATE ops.job_definition
SET max_bytes=25000000,max_rows=5000,timeout_seconds=300,updated_at=now(),version=version+1
WHERE id='20000000-0000-0000-0000-000000000004';
