-- Preserve the parsed address components needed to publish a stable property spine.
ALTER TABLE warehouse.gnaf_address
    ADD COLUMN IF NOT EXISTS flat_type TEXT,
    ADD COLUMN IF NOT EXISTS unit_number TEXT,
    ADD COLUMN IF NOT EXISTS street_number_first INTEGER,
    ADD COLUMN IF NOT EXISTS street_number_suffix TEXT,
    ADD COLUMN IF NOT EXISTS street_number_last INTEGER,
    ADD COLUMN IF NOT EXISTS street_name TEXT,
    ADD COLUMN IF NOT EXISTS street_type TEXT;
