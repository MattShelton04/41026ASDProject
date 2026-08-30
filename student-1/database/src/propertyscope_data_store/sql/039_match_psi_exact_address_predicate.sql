-- Match PSI's measured exact-address equality predicate, including null-equivalent components.
-- The property reference is covered because ambiguity detection needs only the key and this value.
DROP INDEX registry.property_exact_address_components_idx;

CREATE INDEX property_exact_address_components_idx
    ON registry.property (
        postcode,
        locality,
        street_name,
        street_type,
        street_number_first,
        (COALESCE(street_number_last,-1)),
        (COALESCE(street_number_suffix,'')),
        (COALESCE(unit_number,''))
    ) INCLUDE (property_ref);
