-- The legacy run 11 also owns publication evidence, so keep it terminal and introduce a
-- dedicated interruption example with no release/import side effects.
UPDATE ops.run_task
SET status = 'skipped', finished_at = COALESCE(finished_at, '2026-08-13T00:10:00Z'),
    updated_at = '2026-08-13T00:10:00Z', version = version + 1
WHERE ingestion_run_id = '30000000-0000-0000-0000-000000000011'
  AND logical_key LIKE '__/%' AND status = 'pending';

UPDATE ops.ingestion_run
SET status = 'failed', finished_at = COALESCE(finished_at, '2026-08-13T00:10:00Z'),
    error_json = jsonb_build_object(
        'code', 'legacy_showcase_evidence',
        'message', 'Retained legacy run is not resumable; use the dedicated recovery example'
    )
WHERE id = '30000000-0000-0000-0000-000000000011';

INSERT INTO ops.ingestion_run (
    id, job_definition_id, source_definition_id, adapter_version, release_builder_version,
    import_profile_version, normalisation_version, profile_key, run_mode,
    requested_scope_json, source_snapshot_json, input_checkpoint_json, output_checkpoint_json,
    accepted_watermark_json, attempt_number, requested_at, status, rows_discovered,
    rows_staged, rows_accepted, rows_rejected, error_json, request_id, idempotency_key, created_at
) VALUES (
    'c0000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000010',
    '10000000-0000-0000-0000-000000000010',
    '1.0.0', '1.0.0', '1.0.0', '1.0.0', 'fixture-property-full', 'full_refresh',
    '{"profile":"showcase","scenario":"recovery-example"}', '{}', '{}', '{}', '{}',
    1, '2026-08-13T00:20:00Z', 'interrupted', 0, 0, 0, 0,
    '{"code":"task_lease_expired","message":"Worker heartbeat expired; explicit resume is required","retryable":true}',
    'seed-recovery-example', 'seed-recovery-example', '2026-08-13T00:20:00Z'
) ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.run_task (
    id, ingestion_run_id, logical_key, partition_json, stage, status, attempt_number,
    rows_in, rows_out, created_at, updated_at, version
)
SELECT ('c1000000-0000-0000-0000-' || lpad(sequence::text, 12, '0'))::uuid,
       'c0000000-0000-0000-0000-000000000001'::uuid,
       lpad((sequence - 1)::text, 2, '0') || '/' || stage,
       '{"profile":"showcase","scenario":"recovery-example"}'::jsonb,
       stage,
       CASE WHEN sequence = 1 THEN 'claimed' ELSE 'pending' END,
       1, 0, 0, '2026-08-13T00:20:00Z'::timestamptz + sequence * interval '1 second',
       '2026-08-13T00:20:00Z', 1
FROM unnest(ARRAY[
    'discover', 'acquire', 'validate_artifact', 'import', 'normalise', 'quality', 'build_release'
]) WITH ORDINALITY AS stages(stage, sequence)
ON CONFLICT (id) DO NOTHING;
