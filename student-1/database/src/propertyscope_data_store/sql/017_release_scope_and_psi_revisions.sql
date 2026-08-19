-- Keep executable job defaults aligned with the reviewed YAML registrations and preserve
-- source partition membership independently of nullable sale dates.
ALTER TABLE warehouse.psi_sale
ADD COLUMN source_partition_year INTEGER;

UPDATE warehouse.psi_sale
SET source_partition_year = EXTRACT(YEAR FROM COALESCE(contract_date, settlement_date))::integer
WHERE source_partition_year IS NULL;

ALTER TABLE warehouse.psi_sale
ADD CONSTRAINT psi_sale_source_partition_year_check
CHECK (source_partition_year BETWEEN 1990 AND 2100) NOT VALID;

UPDATE ops.job_definition SET
    scope_json='{"profile":"showcase","state":"NSW","localities":["PARRAMATTA","MOSMAN","WOLLONGONG"],"maximum_records":5000}'::jsonb,
    updated_at='2026-08-16T00:00:00Z',version=version+1
WHERE id='20000000-0000-0000-0000-000000000001';

UPDATE ops.job_definition SET
    scope_json='{"profile":"showcase","years":[2025],"maximum_records":250000}'::jsonb,
    updated_at='2026-08-16T00:00:00Z',version=version+1
WHERE id='20000000-0000-0000-0000-000000000002';

UPDATE ops.job_definition SET
    scope_json='{"profile":"showcase","geography_kind":"postcode","geography_values":["2000","2007","2010"],"start_month":"2021-01","end_month":"2025-12","maximum_records":50000}'::jsonb,
    updated_at='2026-08-16T00:00:00Z',version=version+1
WHERE id='20000000-0000-0000-0000-000000000003';

UPDATE ops.job_definition SET
    scope_json='{"profile":"showcase","maximum_records":2500}'::jsonb,
    updated_at='2026-08-16T00:00:00Z',version=version+1
WHERE id='20000000-0000-0000-0000-000000000004';

UPDATE ops.job_definition SET
    scope_json='{"profile":"showcase","localities":["PARRAMATTA","MOSMAN","WOLLONGONG"],"maximum_records":100}'::jsonb,
    updated_at='2026-08-16T00:00:00Z',version=version+1
WHERE id='20000000-0000-0000-0000-000000000010';
