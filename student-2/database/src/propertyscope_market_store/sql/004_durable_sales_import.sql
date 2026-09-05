CREATE TABLE sales_import_generation (
    release_id TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count >= 0),
    stored_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sales_import_operation (
    id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL REFERENCES sales_import_generation(release_id),
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','running','accepted','rejected','failed')),
    attempt INTEGER NOT NULL DEFAULT 1,
    rows_staged INTEGER NOT NULL DEFAULT 0,
    lease_token TEXT,
    lease_until REAL,
    next_attempt_at REAL NOT NULL,
    created_at REAL NOT NULL,
    completed_at REAL,
    error_json TEXT
);
CREATE UNIQUE INDEX sales_import_active_release ON sales_import_operation(release_id)
    WHERE status IN ('queued','running','accepted');
CREATE TABLE sales_import_alias (
    idempotency_key TEXT PRIMARY KEY,
    operation_id TEXT NOT NULL REFERENCES sales_import_operation(id),
    payload_json TEXT NOT NULL
);

-- Invisible until the constant-time accepted pointer switch. Retain exact staging on retry.
CREATE TABLE sale_generation_record (
    release_id TEXT NOT NULL REFERENCES sales_import_generation(release_id),
    ordinal INTEGER NOT NULL,
    source_business_key TEXT NOT NULL,
    source_revision INTEGER NOT NULL,
    property_ref TEXT,
    contract_date TEXT,
    record_sha256 TEXT NOT NULL,
    record_json TEXT NOT NULL,
    PRIMARY KEY (release_id,ordinal),
    UNIQUE (release_id,source_business_key,source_revision)
);
CREATE INDEX sale_generation_property_date
    ON sale_generation_record(release_id,property_ref,contract_date,source_business_key);
CREATE TABLE sales_current_generation (
    dataset_id TEXT PRIMARY KEY,
    release_id TEXT NOT NULL REFERENCES sales_import_generation(release_id),
    operation_id TEXT NOT NULL REFERENCES sales_import_operation(id)
);
