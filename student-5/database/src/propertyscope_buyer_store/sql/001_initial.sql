PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS buyer_case (
    id TEXT PRIMARY KEY,
    owner_ref TEXT NOT NULL CHECK (length(trim(owner_ref)) BETWEEN 1 AND 120),
    name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
    preferences_json TEXT NOT NULL DEFAULT '{}'
        CHECK (json_valid(preferences_json) AND json_type(preferences_json) = 'object'),
    budget_min_aud INTEGER CHECK (budget_min_aud IS NULL OR budget_min_aud >= 0),
    budget_max_aud INTEGER CHECK (budget_max_aud IS NULL OR budget_max_aud >= 0),
    target_suburbs_json TEXT NOT NULL DEFAULT '[]'
        CHECK (json_valid(target_suburbs_json) AND json_type(target_suburbs_json) = 'array'),
    status TEXT NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'closed')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??Z'),
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '????-??-??T??:??:??Z'),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    CHECK (
        budget_min_aud IS NULL OR budget_max_aud IS NULL OR budget_max_aud >= budget_min_aud
    )
);

CREATE INDEX IF NOT EXISTS idx_buyer_case_owner_updated
    ON buyer_case (owner_ref, updated_at DESC, id);

CREATE TABLE IF NOT EXISTS case_property (
    id TEXT PRIMARY KEY,
    buyer_case_id TEXT NOT NULL,
    property_ref TEXT NOT NULL CHECK (length(trim(property_ref)) BETWEEN 1 AND 200),
    property_label TEXT CHECK (
        property_label IS NULL OR length(trim(property_label)) BETWEEN 1 AND 500
    ),
    property_validation_state TEXT NOT NULL DEFAULT 'pending'
        CHECK (property_validation_state IN ('validated', 'pending', 'unavailable')),
    journey_stage TEXT NOT NULL DEFAULT 'Shortlisted'
        CHECK (
            journey_stage IN (
                'Shortlisted', 'Inspecting', 'Reviewing', 'Offer Considered', 'Closed'
            )
        ),
    rating INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    priority TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high')),
    created_at TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??Z'),
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '????-??-??T??:??:??Z'),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    FOREIGN KEY (buyer_case_id) REFERENCES buyer_case(id) ON DELETE CASCADE,
    UNIQUE (buyer_case_id, property_ref),
    UNIQUE (id, buyer_case_id)
);

CREATE INDEX IF NOT EXISTS idx_case_property_case_stage
    ON case_property (buyer_case_id, journey_stage, priority, id);
CREATE INDEX IF NOT EXISTS idx_case_property_ref ON case_property (property_ref);

CREATE TABLE IF NOT EXISTS case_note (
    id TEXT PRIMARY KEY,
    buyer_case_id TEXT NOT NULL,
    case_property_id TEXT,
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 4000),
    created_at TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??Z'),
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '????-??-??T??:??:??Z'),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    FOREIGN KEY (buyer_case_id) REFERENCES buyer_case(id) ON DELETE CASCADE,
    FOREIGN KEY (case_property_id) REFERENCES case_property(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_case_note_case_updated
    ON case_note (buyer_case_id, updated_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_case_note_property ON case_note (case_property_id);

CREATE TABLE IF NOT EXISTS case_task (
    id TEXT PRIMARY KEY,
    buyer_case_id TEXT NOT NULL,
    case_property_id TEXT,
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 300),
    due_date TEXT CHECK (
        due_date IS NULL OR (
            due_date GLOB '????-??-??' AND date(due_date) = due_date
        )
    ),
    completed INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    created_at TEXT NOT NULL CHECK (created_at GLOB '????-??-??T??:??:??Z'),
    updated_at TEXT NOT NULL CHECK (updated_at GLOB '????-??-??T??:??:??Z'),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
    FOREIGN KEY (buyer_case_id) REFERENCES buyer_case(id) ON DELETE CASCADE,
    FOREIGN KEY (case_property_id) REFERENCES case_property(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_case_task_case_completion_due
    ON case_task (buyer_case_id, completed, due_date, id);
CREATE INDEX IF NOT EXISTS idx_case_task_property ON case_task (case_property_id);

CREATE TRIGGER IF NOT EXISTS trg_case_note_property_same_case_insert
BEFORE INSERT ON case_note
WHEN NEW.case_property_id IS NOT NULL
     AND NOT EXISTS (
        SELECT 1 FROM case_property
        WHERE id = NEW.case_property_id AND buyer_case_id = NEW.buyer_case_id
     )
BEGIN
    SELECT RAISE(ABORT, 'case_property_case_mismatch');
END;

CREATE TRIGGER IF NOT EXISTS trg_case_note_property_same_case_update
BEFORE UPDATE OF buyer_case_id, case_property_id ON case_note
WHEN NEW.case_property_id IS NOT NULL
     AND NOT EXISTS (
        SELECT 1 FROM case_property
        WHERE id = NEW.case_property_id AND buyer_case_id = NEW.buyer_case_id
     )
BEGIN
    SELECT RAISE(ABORT, 'case_property_case_mismatch');
END;

CREATE TRIGGER IF NOT EXISTS trg_case_task_property_same_case_insert
BEFORE INSERT ON case_task
WHEN NEW.case_property_id IS NOT NULL
     AND NOT EXISTS (
        SELECT 1 FROM case_property
        WHERE id = NEW.case_property_id AND buyer_case_id = NEW.buyer_case_id
     )
BEGIN
    SELECT RAISE(ABORT, 'case_property_case_mismatch');
END;

CREATE TRIGGER IF NOT EXISTS trg_case_task_property_same_case_update
BEFORE UPDATE OF buyer_case_id, case_property_id ON case_task
WHEN NEW.case_property_id IS NOT NULL
     AND NOT EXISTS (
        SELECT 1 FROM case_property
        WHERE id = NEW.case_property_id AND buyer_case_id = NEW.buyer_case_id
     )
BEGIN
    SELECT RAISE(ABORT, 'case_property_case_mismatch');
END;
