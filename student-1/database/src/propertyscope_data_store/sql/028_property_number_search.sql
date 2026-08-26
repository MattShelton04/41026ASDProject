-- Short numeric searches cannot use trigram indexes. Keep street-number and postcode lookups
-- selective within the accepted immutable release generation instead of scanning address text.
CREATE INDEX gnaf_address_release_street_number_idx
    ON warehouse.gnaf_address (dataset_release_id, street_number_first)
    WHERE street_number_first IS NOT NULL;

CREATE INDEX gnaf_address_release_postcode_idx
    ON warehouse.gnaf_address (dataset_release_id, postcode);

CREATE INDEX property_street_number_idx
    ON registry.property (street_number_first)
    WHERE street_number_first IS NOT NULL;
