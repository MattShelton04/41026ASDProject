-- Complete the executable Release 0 data-product registry used by the release builders.
UPDATE ops.source_definition SET
    adapter_key = CASE id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'gnaf-bulk'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'psi-bulk'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'bocsar-bulk'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'schools-csv'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'fixture-snapshot'
        ELSE adapter_key END,
    licence_id = CASE id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'gnaf-end-user-licence'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'nsw-psi-terms'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'nsw-open-data'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'nsw-open-data'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'synthetic-test-data'
        ELSE licence_id END,
    redistribution_policy = CASE id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'licence-controlled'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'bounded-derived-release'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'approved-bounded-extract'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'approved-bounded-extract'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'committed-synthetic-fixture'
        ELSE redistribution_policy END,
    updated_at = '2026-08-16T00:00:00Z', version = version + 1
WHERE id IN (
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000010'
);

UPDATE ops.job_definition SET
    release_builder_key = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'property-snapshot'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'property-sales'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'crime-series'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'school-points'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'property-snapshot'
        ELSE release_builder_key END,
    target_feature = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'feature-1'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'feature-2'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'feature-3'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'feature-3'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'feature-1'
        ELSE target_feature END,
    dataset_id = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'gnaf-nsw'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'nsw-psi-sales'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'bocsar-crime'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'nsw-government-schools'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'fixture-property'
        ELSE dataset_id END,
    updated_at = '2026-08-16T00:00:00Z', version = version + 1
WHERE id IN (
    '20000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000010'
);
