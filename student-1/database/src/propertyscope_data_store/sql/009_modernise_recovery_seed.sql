-- Modernise the original interrupted showcase fixture to the production seven-stage plan.
-- Its historical two generated task rows remain as skipped evidence rather than being deleted.
UPDATE ops.run_task
SET status = 'skipped', finished_at = COALESCE(finished_at, '2026-08-13T00:00:00Z'),
    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL, heartbeat_at = NULL,
    updated_at = '2026-08-13T00:00:00Z', version = version + 1
WHERE ingestion_run_id = '30000000-0000-0000-0000-000000000011'
  AND logical_key LIKE 'fixture/object-%';

INSERT INTO ops.run_task (
    id, ingestion_run_id, logical_key, partition_json, stage, status, attempt_number,
    rows_in, rows_out, created_at, updated_at, version
)
SELECT ('b0000000-0000-0000-0000-' || lpad(sequence::text, 12, '0'))::uuid,
       '30000000-0000-0000-0000-000000000011'::uuid,
       lpad((sequence - 1)::text, 2, '0') || '/' || stage,
       jsonb_build_object('profile', 'showcase', 'partition', 11),
       stage, 'pending', 1, 0, 0,
       '2026-08-13T00:00:00Z'::timestamptz + sequence * interval '1 second',
       '2026-08-13T00:00:00Z', 1
FROM unnest(ARRAY[
    'discover', 'acquire', 'validate_artifact', 'import', 'normalise', 'quality', 'build_release'
]) WITH ORDINALITY AS stages(stage, sequence)
ON CONFLICT (id) DO NOTHING;

UPDATE ops.ingestion_run
SET status = 'interrupted', finished_at = NULL, rows_discovered = 0, rows_staged = 0,
    rows_accepted = 0, rows_rejected = 0, cancel_requested_at = NULL,
    error_json = jsonb_build_object(
        'code', 'task_lease_expired',
        'message', 'Worker heartbeat expired; explicit resume is required',
        'retryable', true
    )
WHERE id = '30000000-0000-0000-0000-000000000011';
