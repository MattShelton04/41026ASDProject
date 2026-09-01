-- Student 4 - Site, Planning, and Building Due Diligence: initial schema.
--
-- These are deliberately minimal starter tables. As you build out branches 2+
-- (see student-4/README.md), expand the columns, constraints and relationships to
-- fully satisfy the approved feature scope in
-- docs/architecture/registered-feature-scope.md.

CREATE SCHEMA IF NOT EXISTS due_diligence;

-- User-owned due-diligence workspace record (the CRUD anchor for this feature).
CREATE TABLE IF NOT EXISTS due_diligence.site_review (
    id                     uuid PRIMARY KEY,
    property_ref           text NOT NULL,
    address_display        text NOT NULL,
    title                  text NOT NULL,
    status                 text NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'in_review', 'completed', 'archived')),
    disposition            text NOT NULL DEFAULT 'undecided'
        CHECK (disposition IN ('undecided', 'proceed', 'hold', 'do_not_proceed')),
    checklist              jsonb NOT NULL DEFAULT '[]'::jsonb,
    verification_questions jsonb NOT NULL DEFAULT '[]'::jsonb,
    notes                  text NOT NULL DEFAULT '',
    ai_run_ref             text,
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    version                integer NOT NULL DEFAULT 1
);

-- Planning / environmental evidence (zoning, heritage, floor-space ratio, height,
-- flood, bushfire, ...). Evidence state distinguishes confirmed observations,
-- non-intersections, partial coverage and unavailable coverage.
CREATE TABLE IF NOT EXISTS due_diligence.constraint_observation (
    id                 uuid PRIMARY KEY,
    property_ref       text NOT NULL,
    constraint_type    text NOT NULL,
    evidence_state     text NOT NULL
        CHECK (evidence_state IN
            ('confirmed', 'non_intersection', 'partial_coverage', 'unavailable')),
    source_name        text NOT NULL,
    source_url         text,
    summary            text NOT NULL,
    observed_value     text,
    match_method       text,
    confidence         numeric(4, 3),
    dataset_release_id text,
    created_at         timestamptz NOT NULL DEFAULT now()
);

-- Strata, building-order, undertaking and tribunal evidence.
CREATE TABLE IF NOT EXISTS due_diligence.building_observation (
    id             uuid PRIMARY KEY,
    property_ref   text NOT NULL,
    record_type    text NOT NULL,
    evidence_state text NOT NULL
        CHECK (evidence_state IN
            ('confirmed', 'non_intersection', 'partial_coverage', 'unavailable')),
    reference_code text,
    source_name    text NOT NULL,
    source_url     text,
    summary        text NOT NULL,
    match_method   text,
    confidence     numeric(4, 3),
    observed_on    date,
    created_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS site_review_property_ref_idx
    ON due_diligence.site_review (property_ref);
CREATE INDEX IF NOT EXISTS constraint_observation_property_ref_idx
    ON due_diligence.constraint_observation (property_ref);
CREATE INDEX IF NOT EXISTS building_observation_property_ref_idx
    ON due_diligence.building_observation (property_ref);
