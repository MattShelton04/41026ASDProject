-- Parser work-unit heartbeats may exceed canonical output; terminal summaries use task output.

UPDATE ops.ingestion_run run
SET rows_discovered = completed.rows_out
FROM (
    SELECT ingestion_run_id, max(rows_out) AS rows_out
    FROM ops.run_task
    WHERE stage = 'acquire' AND status = 'succeeded'
    GROUP BY ingestion_run_id
) completed
WHERE run.id = completed.ingestion_run_id
  AND run.status IN ('cancelled', 'failed', 'interrupted')
  AND run.rows_discovered <> completed.rows_out;
