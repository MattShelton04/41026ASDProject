CREATE TABLE IF NOT EXISTS sale_observation (
    id TEXT PRIMARY KEY,
    source_business_key TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision >= 1),
    source_era TEXT NOT NULL,
    property_ref TEXT,
    address_display TEXT NOT NULL,
    contract_date TEXT,
    settlement_date TEXT,
    price_aud INTEGER,
    area_square_metres REAL,
    locality TEXT,
    postcode TEXT,
    sale_code TEXT,
    interest_of_sale TEXT,
    match_tier TEXT NOT NULL,
    match_confidence REAL NOT NULL CHECK (match_confidence BETWEEN 0 AND 1),
    geographic_precision TEXT NOT NULL,
    release_id TEXT NOT NULL,
    release_version TEXT NOT NULL,
    source_record_sha256 TEXT NOT NULL CHECK (length(source_record_sha256) = 64),
    normalisation_version TEXT NOT NULL,
    synthetic INTEGER NOT NULL DEFAULT 0 CHECK (synthetic IN (0, 1)),
    created_at TEXT NOT NULL,
    UNIQUE (source_business_key, source_revision, release_id)
);

CREATE INDEX IF NOT EXISTS idx_sale_property_date ON sale_observation (property_ref, contract_date);

CREATE TABLE IF NOT EXISTS market_case (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(name) BETWEEN 1 AND 120),
    property_ref TEXT NOT NULL,
    address_display TEXT NOT NULL,
    date_from TEXT NOT NULL,
    date_to TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'complete', 'archived')),
    notes TEXT NOT NULL DEFAULT '',
    filters_json TEXT NOT NULL DEFAULT '{}',
    ai_run_ref TEXT,
    property_validation_state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1)
);
