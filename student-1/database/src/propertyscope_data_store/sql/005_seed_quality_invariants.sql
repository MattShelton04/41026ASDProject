-- Accepted showcase releases must not carry blocking failures. Retain the rows as
-- deterministic positive evidence; candidate release 11 remains the failure vignette.
UPDATE ops.quality_result quality SET
    severity = 'info',
    status = 'pass',
    observed_value_json = '{"value":12}'::jsonb,
    message = 'Accepted showcase release passed the required continuity check.',
    sample_json = NULL
FROM ops.dataset_release release
WHERE release.id = quality.dataset_release_id
  AND release.status = 'accepted'
  AND quality.id IN (
      '80000000-0000-0000-0000-000000000003'::uuid,
      '80000000-0000-0000-0000-000000000019'::uuid
  );
