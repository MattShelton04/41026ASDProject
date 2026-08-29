-- Terminal task progress must describe completed output, not the last throttled heartbeat.

UPDATE ops.run_task
SET progress_rows = rows_out,
    progress_total_rows = COALESCE(progress_total_rows, rows_out),
    progress_updated_at = COALESCE(finished_at, updated_at)
WHERE status = 'succeeded'
  AND (progress_rows <> rows_out OR progress_total_rows IS NULL);
