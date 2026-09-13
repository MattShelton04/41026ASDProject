-- Street-name discovery and partition feeds must not scan other names/years.
CREATE INDEX gnaf_address_release_street_name_order_idx
    ON warehouse.gnaf_address (dataset_release_id, street_name, gnaf_pid)
    WHERE published;
CREATE INDEX psi_sale_release_source_year_order_idx
    ON warehouse.psi_sale
    (dataset_release_id, source_partition_year, source_business_key, source_revision);
