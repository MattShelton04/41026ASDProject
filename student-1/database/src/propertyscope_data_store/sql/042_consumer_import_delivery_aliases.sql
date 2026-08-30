-- Bind every producer delivery key and activation retry to durable immutable evidence.

ALTER TABLE ops.consumer_import_operation
    ADD COLUMN activation_attempt INTEGER NOT NULL DEFAULT 1 CHECK (activation_attempt > 0),
    ADD CONSTRAINT consumer_import_operation_id_target_uq UNIQUE (id, target_feature);

CREATE TABLE ops.consumer_import_delivery_alias (
    target_feature TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    consumer_import_operation_id UUID NOT NULL,
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    dataset_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    content_sha256 TEXT NOT NULL CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    record_count BIGINT NOT NULL CHECK (record_count >= 0),
    artifact_path TEXT NOT NULL,
    expected_release_version INTEGER NOT NULL CHECK (expected_release_version > 0),
    review_comment TEXT NOT NULL,
    request_id TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (target_feature, idempotency_key),
    FOREIGN KEY (consumer_import_operation_id, target_feature)
        REFERENCES ops.consumer_import_operation(id, target_feature) ON DELETE RESTRICT
);

CREATE INDEX consumer_import_delivery_alias_operation_idx
    ON ops.consumer_import_delivery_alias (consumer_import_operation_id);

INSERT INTO ops.consumer_import_delivery_alias (
    target_feature,idempotency_key,consumer_import_operation_id,dataset_release_id,dataset_id,
    schema_version,content_sha256,record_count,artifact_path,expected_release_version,
    review_comment,request_id,requested_at
)
SELECT
    target_feature,idempotency_key,id,dataset_release_id,dataset_id,schema_version,
    content_sha256,record_count,artifact_path,expected_release_version,review_comment,
    request_id,requested_at
FROM ops.consumer_import_operation;
