-- G-NAF compatibility guards must recognise current and historical identity anchors.
-- The existing property/release index covers only is_current identifiers and cannot
-- serve this predicate after an accepted-generation change.
CREATE INDEX property_identifier_gnaf_property_idx
    ON registry.property_identifier (property_ref)
    WHERE scheme='gnaf_pid';
