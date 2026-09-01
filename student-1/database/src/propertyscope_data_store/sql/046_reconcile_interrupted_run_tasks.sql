-- Keep child task evidence terminal when an expired lease interrupts its parent run.

ALTER TABLE ops.run_task DROP CONSTRAINT run_task_status_check;
ALTER TABLE ops.run_task ADD CONSTRAINT run_task_status_check CHECK (
    status IN (
        'pending','claimed','running','retry_wait','succeeded','failed','cancelled',
        'interrupted','skipped'
    )
);

UPDATE ops.run_task task
SET status = 'interrupted',
    finished_at = COALESCE(
        task.finished_at,
        task.lease_expires_at,
        task.heartbeat_at,
        run.heartbeat_at,
        run.started_at,
        run.requested_at
    ),
    updated_at = GREATEST(
        task.updated_at,
        COALESCE(task.lease_expires_at, task.heartbeat_at, run.heartbeat_at, run.requested_at)
    ),
    error_json = COALESCE(task.error_json, run.error_json, jsonb_build_object(
        'code', 'task_lease_expired',
        'message', 'The worker lease expired before the task completed.'
    )),
    lease_owner = NULL,
    lease_token = NULL,
    lease_expires_at = NULL,
    heartbeat_at = NULL,
    version = task.version + 1
FROM ops.ingestion_run run
WHERE task.ingestion_run_id = run.id
  AND run.status = 'interrupted'
  AND task.status IN ('claimed', 'running');
