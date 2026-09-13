-- Equality lookups must stop at the candidate window in a repeatable order.
-- Replace the shorter indexes instead of retaining redundant write/storage cost.
DROP INDEX warehouse.gnaf_address_release_street_number_idx;
DROP INDEX warehouse.gnaf_address_release_postcode_idx;

CREATE INDEX gnaf_address_release_street_number_idx
    ON warehouse.gnaf_address (dataset_release_id, street_number_first, gnaf_pid)
    WHERE published AND street_number_first IS NOT NULL;
CREATE INDEX gnaf_address_release_postcode_idx
    ON warehouse.gnaf_address (dataset_release_id, postcode, gnaf_pid)
    WHERE published;
CREATE INDEX gnaf_address_release_locality_order_idx
    ON warehouse.gnaf_address (dataset_release_id, locality, gnaf_pid)
    WHERE published;
