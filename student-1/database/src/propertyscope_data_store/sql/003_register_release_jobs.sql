-- Align deterministic showcase jobs with the same reviewed profile keys used by source-scale runs.
UPDATE ops.job_definition SET
    profile_key = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'gnaf-nsw-address-registry'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'nsw-psi-sales-year'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'bocsar-crime-quarterly'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'nsw-government-schools-master'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'fixture-property-full'
        ELSE profile_key END,
    adapter_key = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'gnaf-bulk'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'psi-bulk'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'bocsar-bulk'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'schools-csv'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'fixture-snapshot'
        ELSE adapter_key END,
    import_profile_key = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'gnaf-nsw'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'psi-sales'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'bocsar-sparse'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'schools-master'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'property-fixture'
        ELSE import_profile_key END,
    status = CASE
        WHEN id IN (
            '20000000-0000-0000-0000-000000000005',
            '20000000-0000-0000-0000-000000000006',
            '20000000-0000-0000-0000-000000000007'
        ) THEN 'draft'
        ELSE status END,
    updated_at = '2026-08-13T00:00:00Z'
WHERE id IN (
    '20000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000005',
    '20000000-0000-0000-0000-000000000006',
    '20000000-0000-0000-0000-000000000007',
    '20000000-0000-0000-0000-000000000010'
);
