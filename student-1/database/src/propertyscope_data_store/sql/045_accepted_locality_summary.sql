-- Forward-safe completion for development databases that may have applied an early 044 draft
-- before its second index was added. Fresh databases create this in 044 and skip the duplicate.
CREATE INDEX IF NOT EXISTS gnaf_address_release_exact_components_idx
    ON warehouse.gnaf_address (
        dataset_release_id,
        postcode,
        locality,
        street_name,
        street_type,
        street_number_first,
        (COALESCE(street_number_last,-1)),
        (COALESCE(street_number_suffix,'')),
        (COALESCE(unit_number,''))
    ) INCLUDE (gnaf_pid,property_ref)
    WHERE published
      AND street_name IS NOT NULL
      AND street_type IS NOT NULL
      AND street_number_first IS NOT NULL;

-- Locality and postcode summaries use exact accepted-generation predicates rather than the
-- bounded fuzzy-search candidate window.
CREATE INDEX gnaf_address_release_locality_postcode_idx
    ON warehouse.gnaf_address (dataset_release_id, locality, postcode)
    WHERE published;
