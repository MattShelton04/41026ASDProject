-- Persist safe, operator-visible scope defaults that remain meaningful when the UI
-- switches a registered job from showcase to its explicit full-data profile.
UPDATE ops.job_definition
SET scope_json = '{"profile":"showcase","state":"NSW","maximum_records":5000}'::jsonb,
    updated_at = now(), version = version + 1
WHERE id = '20000000-0000-0000-0000-000000000001';

UPDATE ops.job_definition
SET scope_json = '{"profile":"showcase","years":[2025],"partition_type":"source_year","maximum_records":50000}'::jsonb,
    updated_at = now(), version = version + 1
WHERE id = '20000000-0000-0000-0000-000000000002';

UPDATE ops.job_definition
SET scope_json = '{"profile":"showcase","geography_kind":"postcode","geography_values":["2000","2007","2010"],"start_month":"2021-01","end_month":"2026-12","maximum_records":50000}'::jsonb,
    updated_at = now(), version = version + 1
WHERE id = '20000000-0000-0000-0000-000000000003';

UPDATE ops.job_definition
SET scope_json = '{"profile":"showcase","maximum_records":5000}'::jsonb,
    updated_at = now(), version = version + 1
WHERE id = '20000000-0000-0000-0000-000000000004';

UPDATE ops.job_definition
SET scope_json = '{"profile":"showcase","localities":["PARRAMATTA","MOSMAN","WOLLONGONG"],"maximum_records":100}'::jsonb,
    updated_at = now(), version = version + 1
WHERE id = '20000000-0000-0000-0000-000000000010';
