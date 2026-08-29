-- A timed-out browser request can be retried before it learns that publication was queued.
-- Permit only one nonterminal activation for a reviewed release version so a new request key
-- cannot enqueue duplicate source-scale work.
WITH duplicates AS (
    SELECT id,row_number() OVER (
        PARTITION BY dataset_release_id,expected_release_version
        ORDER BY requested_at,id
    ) AS position
    FROM ops.release_activation
    WHERE status IN ('queued','claimed','running','interrupted')
)
UPDATE ops.release_activation operation
SET status='failed',finished_at=now(),lease_owner=NULL,lease_token=NULL,
    lease_expires_at=NULL,heartbeat_at=NULL,version=operation.version+1,
    error_json=jsonb_build_object(
        'code','duplicate_activation_reconciled',
        'message','A prior nonterminal activation owns this reviewed release version',
        'retryable',false
    )
FROM duplicates
WHERE duplicates.id=operation.id AND duplicates.position>1;

CREATE UNIQUE INDEX release_activation_nonterminal_release_version_uq
    ON ops.release_activation (dataset_release_id, expected_release_version)
    WHERE status IN ('queued','claimed','running','interrupted');
