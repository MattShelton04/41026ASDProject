-- Small, bounded operator log. Keep credentials, source records and raw errors out.
CREATE TABLE ops.run_activity (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id UUID NOT NULL REFERENCES ops.ingestion_run(id) ON DELETE CASCADE,
    task_id UUID NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    stage TEXT NOT NULL,
    status TEXT NOT NULL,
    attempt_number INTEGER NOT NULL,
    phase TEXT,
    rows_processed BIGINT NOT NULL,
    bytes_processed BIGINT NOT NULL,
    error_code TEXT,
    event_kind TEXT NOT NULL DEFAULT 'change'
);
CREATE INDEX run_activity_recent ON ops.run_activity(ingestion_run_id, id DESC);

CREATE FUNCTION ops.record_run_activity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'UPDATE' AND
       (NEW.status, NEW.attempt_number, NEW.progress_phase, NEW.progress_rows,
        NEW.progress_bytes, NEW.error_json->>'code') IS NOT DISTINCT FROM
       (OLD.status, OLD.attempt_number, OLD.progress_phase, OLD.progress_rows,
        OLD.progress_bytes, OLD.error_json->>'code') THEN
        RETURN NEW;
    END IF;
    INSERT INTO ops.run_activity(ingestion_run_id,task_id,stage,status,attempt_number,
        phase,rows_processed,bytes_processed,error_code)
    VALUES (NEW.ingestion_run_id,NEW.id,NEW.stage,NEW.status,NEW.attempt_number,
        left(NEW.progress_phase,100),NEW.progress_rows,NEW.progress_bytes,
        left(NEW.error_json->>'code',120));
    -- Bounded retention and indexed lookup; heartbeat-only updates write no events.
    DELETE FROM ops.run_activity WHERE ingestion_run_id=NEW.ingestion_run_id AND id < (
        SELECT id FROM ops.run_activity WHERE ingestion_run_id=NEW.ingestion_run_id
        ORDER BY id DESC OFFSET 999 LIMIT 1
    );
    RETURN NEW;
END;
$$;
CREATE TRIGGER run_activity_changed AFTER INSERT OR UPDATE ON ops.run_task
    FOR EACH ROW EXECUTE FUNCTION ops.record_run_activity();

-- Existing runs get a clearly identified snapshot, not invented historical events.
INSERT INTO ops.run_activity(ingestion_run_id,task_id,stage,status,attempt_number,
    phase,rows_processed,bytes_processed,error_code,event_kind)
SELECT ingestion_run_id,id,stage,status,attempt_number,left(progress_phase,100),
    progress_rows,progress_bytes,left(error_json->>'code',120),'snapshot'
FROM ops.run_task;
