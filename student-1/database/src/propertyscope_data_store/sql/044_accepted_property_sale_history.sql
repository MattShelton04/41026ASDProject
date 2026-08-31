-- Property detail reads pin sales to the accepted immutable PSI generation and collapse
-- retransmissions to the latest revision per source business key.  Lead with the release and
-- canonical property so the bounded read never scans historical candidate generations.
CREATE INDEX psi_sale_release_property_revision_idx
    ON warehouse.psi_sale (
        dataset_release_id,
        property_ref,
        source_business_key,
        source_revision DESC
    )
    WHERE property_ref IS NOT NULL;

-- PSI exact-address resolution uses only the accepted, published G-NAF generation. Cover the
-- stable-id inputs so a full PSI import probes address components instead of scanning display
-- text or copying G-NAF identities into the mutable registry.
CREATE INDEX gnaf_address_release_exact_components_idx
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
