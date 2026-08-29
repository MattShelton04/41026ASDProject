-- Cached reprocessing discovers records by verifying the retained canonical artifact rather
-- than rerunning acquisition. Keep the operator headline consistent with that evidence.

UPDATE ops.ingestion_run
SET rows_discovered = rows_staged
WHERE run_mode = 'reprocess_cached'
  AND rows_discovered = 0
  AND rows_staged > 0;
