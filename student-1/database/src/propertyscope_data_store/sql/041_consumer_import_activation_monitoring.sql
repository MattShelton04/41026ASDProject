-- Extend the initial durable delivery state machine without rewriting applied migration 040.

ALTER TABLE ops.consumer_import_operation
    DROP CONSTRAINT consumer_import_operation_status_check,
    DROP CONSTRAINT consumer_import_operation_phase_key_check,
    DROP CONSTRAINT consumer_import_operation_check1,
    DROP CONSTRAINT consumer_import_operation_check2,
    DROP CONSTRAINT consumer_import_operation_check3;

UPDATE ops.consumer_import_operation
SET status = 'published'
WHERE status = 'succeeded';

ALTER TABLE ops.consumer_import_operation
    ADD CONSTRAINT consumer_import_operation_status_check CHECK (status IN (
        'queued','claimed','polling','receipt_pending','activation_pending',
        'activation_queued','published','rejected','failed','interrupted'
    )),
    ADD CONSTRAINT consumer_import_operation_phase_key_check CHECK (phase_key IN (
        'connect','poll','record_receipt','queue_activation','wait_activation','complete'
    )),
    ADD CONSTRAINT consumer_import_operation_consumer_identity_check CHECK (
        consumer_operation_id IS NOT NULL OR phase_key IN ('connect','complete')
    ),
    ADD CONSTRAINT consumer_import_operation_receipt_phase_check CHECK (
        publication_receipt_id IS NULL OR phase_key IN (
            'queue_activation','wait_activation','complete'
        )
    ),
    ADD CONSTRAINT consumer_import_operation_activation_phase_check CHECK (
        release_activation_id IS NULL OR phase_key IN ('wait_activation','complete')
    );

CREATE UNIQUE INDEX consumer_import_active_release_identity_uq
    ON ops.consumer_import_operation (
        dataset_release_id,dataset_id,target_feature,schema_version,content_sha256,record_count
    )
    WHERE status NOT IN ('failed','rejected');

DROP INDEX ops.consumer_import_claim_idx;

CREATE INDEX consumer_import_claim_idx
    ON ops.consumer_import_operation (status, next_attempt_at, requested_at)
    WHERE status IN (
        'queued','polling','receipt_pending','activation_pending','activation_queued',
        'interrupted','claimed'
    );
