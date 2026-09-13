-- Preserve terminal loader attempt evidence before an explicit retry resets its display.
CREATE TABLE ops.import_attempt_evidence (
    import_operation_id UUID NOT NULL REFERENCES ops.import_operation(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('failed','interrupted','cancelled')),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    progress_phase_key TEXT,
    progress_rows BIGINT NOT NULL,
    rows_staged BIGINT NOT NULL,
    rows_accepted BIGINT NOT NULL,
    error_json JSONB,
    space_recovery_policy_json JSONB,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (import_operation_id,attempt_number)
);

INSERT INTO ops.import_attempt_evidence (
    import_operation_id,attempt_number,status,started_at,finished_at,progress_phase_key,
    progress_rows,rows_staged,rows_accepted,error_json,space_recovery_policy_json
)
SELECT id,attempt_number,status,started_at,finished_at,progress_phase_key,
    progress_rows,rows_staged,rows_accepted,error_json,space_recovery_policy_json
FROM ops.import_operation WHERE status IN ('failed','interrupted','cancelled');

CREATE FUNCTION ops.capture_import_attempt_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status IN ('failed','interrupted','cancelled') THEN
        INSERT INTO ops.import_attempt_evidence (
            import_operation_id,attempt_number,status,started_at,finished_at,progress_phase_key,
            progress_rows,rows_staged,rows_accepted,error_json,space_recovery_policy_json
        ) VALUES (
            NEW.id,NEW.attempt_number,NEW.status,NEW.started_at,NEW.finished_at,
            NEW.progress_phase_key,NEW.progress_rows,NEW.rows_staged,NEW.rows_accepted,
            NEW.error_json,NEW.space_recovery_policy_json
        ) ON CONFLICT (import_operation_id,attempt_number) DO NOTHING;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER import_attempt_evidence_capture
AFTER INSERT OR UPDATE OF status ON ops.import_operation
FOR EACH ROW EXECUTE FUNCTION ops.capture_import_attempt_evidence();
