-- Locality and postcode summaries use exact accepted-generation predicates rather than the
-- bounded fuzzy-search candidate window.
CREATE INDEX gnaf_address_release_locality_postcode_idx
    ON warehouse.gnaf_address (dataset_release_id, locality, postcode)
    WHERE published;
