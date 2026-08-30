-- Stable loader phase keys and conservative rollback space-recovery evidence.
-- Recovery is intentionally an operator-visible policy marker: this migration does not run
-- VACUUM FULL, REINDEX, or any other broad/destructive maintenance automatically.

ALTER TABLE ops.run_task
    ADD COLUMN progress_phase_key TEXT;

ALTER TABLE ops.import_operation
    ADD COLUMN progress_phase_key TEXT,
    ADD COLUMN space_recovery_status TEXT NOT NULL DEFAULT 'not_required'
        CHECK (space_recovery_status IN ('not_required','needed','completed')),
    ADD COLUMN space_recovery_policy_json JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE ops.release_activation
    ADD COLUMN progress_phase_key TEXT,
    ADD COLUMN progress_phase TEXT,
    ADD COLUMN progress_updated_at TIMESTAMPTZ;
