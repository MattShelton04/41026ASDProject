-- Accepted property discovery reads the immutable release generation through the atomic
-- accepted_generation pointer. Expression indexes preserve fast free-text and detail lookup
-- without rewriting source rows or copying millions of candidates into global registry tables.
CREATE INDEX gnaf_address_search_document_trgm_idx
    ON warehouse.gnaf_address USING gin
    ((trim(regexp_replace(lower(address_display), '[^a-z0-9]+', ' ', 'g'))) gin_trgm_ops);

CREATE INDEX gnaf_address_stable_property_ref_idx
    ON warehouse.gnaf_address
    ((COALESCE(property_ref, md5('propertyscope-gnaf:' || gnaf_pid)::uuid)));
