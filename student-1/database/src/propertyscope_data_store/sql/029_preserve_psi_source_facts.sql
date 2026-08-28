-- Preserve the official historical/current PSI B-record facts needed by Feature 2 and support a
-- conservative unique exact-address match against the accepted PropertyScope registry.
ALTER TABLE warehouse.psi_sale
    ADD COLUMN source_system TEXT,
    ADD COLUMN valuation_number TEXT,
    ADD COLUMN source_downloaded_at TIMESTAMP,
    ADD COLUMN property_name TEXT,
    ADD COLUMN unit_number TEXT,
    ADD COLUMN house_number TEXT,
    ADD COLUMN street_number_first INTEGER,
    ADD COLUMN street_number_suffix TEXT,
    ADD COLUMN street_name TEXT,
    ADD COLUMN street_name_normalised TEXT,
    ADD COLUMN street_type TEXT,
    ADD COLUMN locality TEXT,
    ADD COLUMN postcode TEXT,
    ADD COLUMN land_description TEXT,
    ADD COLUMN dimensions TEXT,
    ADD COLUMN zoning_code TEXT,
    ADD COLUMN nature_code TEXT,
    ADD COLUMN primary_purpose TEXT,
    ADD COLUMN strata_lot_number TEXT,
    ADD COLUMN component_code TEXT,
    ADD COLUMN sale_code TEXT,
    ADD COLUMN interest_of_sale TEXT;

ALTER TABLE warehouse.psi_sale
    ADD CONSTRAINT psi_sale_postcode_check
    CHECK (postcode IS NULL OR postcode ~ '^[0-9]{4}$') NOT VALID;

CREATE INDEX psi_sale_release_locality_date_idx
    ON warehouse.psi_sale (dataset_release_id, postcode, locality, contract_date);

CREATE INDEX property_exact_address_components_idx
    ON registry.property (
        postcode,
        locality,
        street_name,
        street_type,
        street_number_first,
        unit_number
    );
