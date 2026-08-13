-- Repair retained showcase volumes where the interrupted recovery example was resumed by
-- an older implementation that could not reset its cancelled unfinished task.
UPDATE ops.ingestion_run run
SET status = 'interrupted', finished_at = NULL,
    error_json = jsonb_build_object(
        'code', 'task_lease_expired',
        'message', 'Worker heartbeat expired; explicit resume is required',
        'retryable', true
    )
WHERE run.id = '30000000-0000-0000-0000-000000000011'
  AND run.status = 'queued'
  AND NOT EXISTS (
      SELECT 1 FROM ops.run_task task
      WHERE task.ingestion_run_id = run.id
        AND task.status IN ('pending', 'claimed', 'running', 'retry_wait')
  );
