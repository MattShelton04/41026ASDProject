-- Publication belongs to the producer; consumer delivery is an independent outbox.
ALTER TABLE ops.consumer_import_operation
    ADD COLUMN delivery_only BOOLEAN NOT NULL DEFAULT FALSE,
    DROP CONSTRAINT consumer_import_operation_status_check;
ALTER TABLE ops.consumer_import_operation
    ADD CONSTRAINT consumer_import_operation_status_check CHECK (status IN (
        'queued','claimed','polling','receipt_pending','activation_pending',
        'activation_queued','published','delivered','rejected','failed','interrupted'
    ));
