-- Publication receipts are durable before a release is activated. Source-scale registry
-- materialisation is separately leased to the serial database loader so an HTTP request never
-- owns a multi-million-row transaction or the accepted-generation lock.
CREATE TABLE ops.release_activation (
    id UUID PRIMARY KEY,
    dataset_release_id UUID NOT NULL REFERENCES ops.dataset_release(id) ON DELETE RESTRICT,
    publication_receipt_id UUID NOT NULL REFERENCES ops.publication_receipt(id) ON DELETE RESTRICT,
    expected_release_version INTEGER NOT NULL CHECK (expected_release_version > 0),
    review_comment TEXT NOT NULL CHECK (length(btrim(review_comment)) > 0),
    status TEXT NOT NULL CHECK (status IN
        ('queued','claimed','running','succeeded','failed','interrupted')),
    attempt_number INTEGER NOT NULL DEFAULT 1 CHECK (attempt_number BETWEEN 1 AND 3),
    idempotency_key TEXT NOT NULL UNIQUE,
    lease_owner TEXT,
    lease_token TEXT,
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    requested_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    materialized_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_json JSONB,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    UNIQUE (dataset_release_id, publication_receipt_id),
    CHECK ((lease_owner IS NULL) = (lease_expires_at IS NULL))
);

CREATE INDEX release_activation_claim_idx
    ON ops.release_activation (status, requested_at);

-- Accepted-generation filtering probes identifiers by property and release. The original unique
-- source-identifier index cannot serve that access path efficiently at G-NAF scale.
CREATE INDEX property_identifier_current_property_release_idx
    ON registry.property_identifier (property_ref, source_release_id)
    WHERE is_current;
