-- Migration 061 could observe a retried operation still carrying its prior
-- recovery policy. Preserve its event, but do not guess which attempt owns it.
CREATE TABLE ops.import_recovery_attribution (
    recovery_evidence_id BIGINT PRIMARY KEY REFERENCES ops.import_recovery_evidence(id),
    attribution TEXT NOT NULL CHECK (attribution='legacy_attempt_unverified'),
    reason TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO ops.import_recovery_attribution (recovery_evidence_id,attribution,reason)
SELECT recovery.id,'legacy_attempt_unverified',
    'Migration 061 captured a recovery policy after an earlier terminal attempt; '
    'the recorded attempt may already have advanced, so ownership is unverified.'
FROM ops.import_recovery_evidence recovery
JOIN public.propertyscope_schema_migration migration
    ON migration.version='061_import_recovery_evidence.sql'
    AND recovery.recorded_at=migration.applied_at
WHERE recovery.attempt_number>1 AND EXISTS (
    SELECT 1 FROM ops.import_attempt_evidence earlier
    WHERE earlier.import_operation_id=recovery.import_operation_id
        AND earlier.attempt_number<recovery.attempt_number
);
