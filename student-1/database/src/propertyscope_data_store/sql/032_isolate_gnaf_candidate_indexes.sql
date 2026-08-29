-- Candidate G-NAF rows maintain only their generation key. Expensive search/geometry
-- indexes are populated during reviewed activation, so a cancelled import cannot bloat them.

ALTER TABLE warehouse.gnaf_address
    ADD COLUMN published BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE warehouse.gnaf_address address
SET published=TRUE
FROM ops.dataset_release release
WHERE release.id=address.dataset_release_id AND release.status='accepted';

DROP INDEX warehouse.gnaf_address_geom_idx;
DROP INDEX warehouse.gnaf_address_lookup_idx;
DROP INDEX warehouse.gnaf_address_search_document_trgm_idx;
DROP INDEX warehouse.gnaf_address_stable_property_ref_idx;
DROP INDEX warehouse.gnaf_address_release_street_number_idx;
DROP INDEX warehouse.gnaf_address_release_postcode_idx;

CREATE INDEX gnaf_address_geom_idx ON warehouse.gnaf_address USING gist (geom)
    WHERE published;
CREATE INDEX gnaf_address_lookup_idx ON warehouse.gnaf_address (postcode,locality,gnaf_pid)
    WHERE published;
CREATE INDEX gnaf_address_search_document_trgm_idx
    ON warehouse.gnaf_address USING gin
    ((trim(regexp_replace(lower(address_display), '[^a-z0-9]+', ' ', 'g'))) gin_trgm_ops)
    WHERE published;
CREATE INDEX gnaf_address_stable_property_ref_idx
    ON warehouse.gnaf_address
    ((COALESCE(property_ref,md5('propertyscope-gnaf:' || gnaf_pid)::uuid)))
    WHERE published;
CREATE INDEX gnaf_address_release_street_number_idx
    ON warehouse.gnaf_address (dataset_release_id,street_number_first)
    WHERE published AND street_number_first IS NOT NULL;
CREATE INDEX gnaf_address_release_postcode_idx
    ON warehouse.gnaf_address (dataset_release_id,postcode)
    WHERE published;
