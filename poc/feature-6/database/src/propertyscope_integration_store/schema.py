"""Idempotent SQLite schema owned exclusively by the POC database service."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migration (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS release_import (
    target_feature TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_sha256 TEXT NOT NULL,
    provider_release_id TEXT NOT NULL,
    dataset_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    record_count INTEGER NOT NULL CHECK (record_count >= 0),
    request_json TEXT NOT NULL,
    rows_accepted INTEGER NOT NULL CHECK (rows_accepted >= 0),
    status TEXT NOT NULL CHECK (status IN ('accepted', 'rejected')),
    receipt_json TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    PRIMARY KEY (target_feature, idempotency_key),
    UNIQUE (dataset_id, provider_release_id)
);

CREATE TABLE IF NOT EXISTS sale_observation (
    provider_release_id TEXT NOT NULL,
    source_business_key TEXT NOT NULL,
    source_revision INTEGER NOT NULL CHECK (source_revision >= 1),
    property_ref TEXT,
    contract_date TEXT,
    settlement_date TEXT,
    price_aud INTEGER CHECK (price_aud IS NULL OR price_aud >= 0),
    locality TEXT,
    postcode TEXT,
    match_tier TEXT,
    provenance_json TEXT NOT NULL,
    source_json TEXT NOT NULL,
    PRIMARY KEY (provider_release_id, source_business_key, source_revision)
);
CREATE INDEX IF NOT EXISTS sale_property_date_idx
    ON sale_observation (property_ref, contract_date);

CREATE TABLE IF NOT EXISTS crime_series (
    provider_release_id TEXT NOT NULL,
    postcode TEXT NOT NULL,
    source_category_key TEXT NOT NULL,
    offence_label TEXT NOT NULL,
    subcategory_label TEXT,
    first_month TEXT NOT NULL,
    last_month TEXT NOT NULL,
    observed_months_json TEXT NOT NULL,
    blank_means_observed_zero INTEGER NOT NULL CHECK (blank_means_observed_zero IN (0, 1)),
    observations_json TEXT NOT NULL,
    provenance_json TEXT NOT NULL,
    PRIMARY KEY (provider_release_id, postcode, source_category_key)
);
CREATE INDEX IF NOT EXISTS crime_postcode_idx ON crime_series (postcode);

CREATE TABLE IF NOT EXISTS school_point (
    provider_release_id TEXT NOT NULL,
    school_code TEXT NOT NULL,
    school_name TEXT NOT NULL,
    school_type TEXT NOT NULL,
    operational_status TEXT NOT NULL,
    locality TEXT NOT NULL,
    lga TEXT,
    latitude REAL NOT NULL CHECK (latitude BETWEEN -90 AND 90),
    longitude REAL NOT NULL CHECK (longitude BETWEEN -180 AND 180),
    provenance_json TEXT NOT NULL,
    PRIMARY KEY (provider_release_id, school_code)
);
CREATE INDEX IF NOT EXISTS school_locality_idx ON school_point (locality);

CREATE TABLE IF NOT EXISTS market_case (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    property_ref TEXT NOT NULL,
    date_from TEXT,
    date_to TEXT,
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL CHECK (status IN ('draft', 'active', 'complete', 'archived')),
    filters_json TEXT NOT NULL DEFAULT '{}',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS saved_place (
    id TEXT PRIMARY KEY,
    actor_ref TEXT NOT NULL,
    locality TEXT NOT NULL,
    postcode TEXT NOT NULL,
    favourite INTEGER NOT NULL CHECK (favourite IN (0, 1)),
    notes TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_review (
    id TEXT PRIMARY KEY,
    property_ref TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'in_review', 'complete', 'archived')),
    disposition TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS site_review_item (
    id TEXT PRIMARY KEY,
    site_review_id TEXT NOT NULL REFERENCES site_review(id) ON DELETE CASCADE,
    item_kind TEXT NOT NULL CHECK (item_kind IN ('check', 'question')),
    text TEXT NOT NULL,
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS buyer_case (
    id TEXT PRIMARY KEY,
    actor_ref TEXT NOT NULL,
    name TEXT NOT NULL,
    budget_min INTEGER CHECK (budget_min IS NULL OR budget_min >= 0),
    budget_max INTEGER CHECK (budget_max IS NULL OR budget_max >= 0),
    target_suburbs_json TEXT NOT NULL DEFAULT '[]',
    preferences_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('active', 'paused', 'closed', 'archived')),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_property (
    id TEXT PRIMARY KEY,
    buyer_case_id TEXT NOT NULL REFERENCES buyer_case(id) ON DELETE CASCADE,
    property_ref TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN (
        'shortlisted', 'inspecting', 'reviewing', 'offer_considered', 'closed'
    )),
    rating INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (buyer_case_id, property_ref)
);

CREATE TABLE IF NOT EXISTS case_note (
    id TEXT PRIMARY KEY,
    buyer_case_id TEXT NOT NULL REFERENCES buyer_case(id) ON DELETE CASCADE,
    case_property_id TEXT REFERENCES case_property(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS case_task (
    id TEXT PRIMARY KEY,
    buyer_case_id TEXT NOT NULL REFERENCES buyer_case(id) ON DELETE CASCADE,
    case_property_id TEXT REFERENCES case_property(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    due_date TEXT,
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def migrate(connection: sqlite3.Connection) -> None:
    """Apply the complete idempotent schema to one owned database."""
    connection.executescript(SCHEMA)
    connection.execute(
        "INSERT OR IGNORE INTO schema_migration(version, applied_at) VALUES (?, datetime('now'))",
        (SCHEMA_VERSION,),
    )
    connection.commit()
