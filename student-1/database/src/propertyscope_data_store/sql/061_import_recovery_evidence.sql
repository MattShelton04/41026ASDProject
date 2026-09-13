-- Recovery can finish after the terminal attempt was recorded. Append each later
-- policy transition separately, retaining both the original failure and recovery.
CREATE TABLE ops.import_recovery_evidence (
    id BIGSERIAL PRIMARY KEY,
    import_operation_id UUID NOT NULL REFERENCES ops.import_operation(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    recovery_status TEXT NOT NULL,
    policy_json JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX import_recovery_evidence_attempt_idx ON ops.import_recovery_evidence
    (import_operation_id,attempt_number,id DESC);

INSERT INTO ops.import_recovery_evidence (
    import_operation_id,attempt_number,recovery_status,policy_json
)
SELECT id,attempt_number,space_recovery_status,space_recovery_policy_json
FROM ops.import_operation
WHERE space_recovery_policy_json IS NOT NULL AND space_recovery_policy_json<>'{}'::jsonb;

CREATE FUNCTION ops.capture_import_recovery_evidence() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.space_recovery_policy_json IS NOT NULL
       AND NEW.space_recovery_policy_json<>'{}'::jsonb
       AND (TG_OP='INSERT' OR
            NEW.space_recovery_policy_json IS DISTINCT FROM OLD.space_recovery_policy_json OR
            NEW.space_recovery_status IS DISTINCT FROM OLD.space_recovery_status) THEN
        INSERT INTO ops.import_recovery_evidence (
            import_operation_id,attempt_number,recovery_status,policy_json
        ) VALUES (
            NEW.id,NEW.attempt_number,NEW.space_recovery_status,NEW.space_recovery_policy_json
        );
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER import_recovery_evidence_capture
AFTER INSERT OR UPDATE OF space_recovery_policy_json,space_recovery_status ON ops.import_operation
FOR EACH ROW EXECUTE FUNCTION ops.capture_import_recovery_evidence();
