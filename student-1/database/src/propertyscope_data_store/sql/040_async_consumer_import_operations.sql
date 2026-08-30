-- Durable outbound consumer imports separate immutable release evidence from delivery work.

CREATE TABLE ops.consumer_import_operation (
    id UUID PRIMARY KEY,
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    dataset_id TEXT NOT NULL,
    target_feature TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    record_count BIGINT NOT NULL CHECK (record_count >= 0),
    manifest_json JSONB NOT NULL,
    artifact_path TEXT NOT NULL,
    expected_release_version INTEGER NOT NULL CHECK (expected_release_version > 0),
    review_comment TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    consumer_operation_id TEXT,
    publication_receipt_id UUID REFERENCES ops.publication_receipt(id) ON DELETE RESTRICT,
    release_activation_id UUID REFERENCES ops.release_activation(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK (status IN (
        'queued','claimed','polling','receipt_pending','activation_pending',
        'succeeded','rejected','failed','interrupted'
    )),
    phase_key TEXT NOT NULL CHECK (phase_key IN (
        'connect','poll','record_receipt','queue_activation','complete'
    )),
    remote_status TEXT,
    result_json JSONB,
    error_json JSONB,
    attempt_number INTEGER NOT NULL DEFAULT 1 CHECK (attempt_number > 0),
    next_attempt_at TIMESTAMPTZ NOT NULL,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    request_id TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    UNIQUE (target_feature, idempotency_key),
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL)),
    CHECK (consumer_operation_id IS NOT NULL OR phase_key = 'connect'),
    CHECK (publication_receipt_id IS NULL OR phase_key IN ('queue_activation','complete')),
    CHECK (release_activation_id IS NULL OR phase_key = 'complete')
);

CREATE UNIQUE INDEX consumer_import_remote_operation_uq
    ON ops.consumer_import_operation (target_feature, consumer_operation_id)
    WHERE consumer_operation_id IS NOT NULL;

CREATE INDEX consumer_import_claim_idx
    ON ops.consumer_import_operation (status, next_attempt_at, requested_at)
    WHERE status IN ('queued','polling','receipt_pending','activation_pending','interrupted','claimed');
