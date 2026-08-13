-- Replace scaffold labels and attribution placeholders for the executable R0 source catalogue.
UPDATE ops.job_definition
SET name = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'G-NAF NSW address registry'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'NSW property sales yearly backfill'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'BOCSAR crime quarterly snapshot'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'NSW government schools master snapshot'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'Deterministic property critical-path fixture'
        ELSE name
    END,
    updated_at = '2026-08-13T00:00:00Z'
WHERE id IN (
    '20000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000004',
    '20000000-0000-0000-0000-000000000010'
);

UPDATE ops.source_definition
SET source_url = CASE id
        WHEN '10000000-0000-0000-0000-000000000001' THEN
            'https://data.gov.au/data/dataset/geocoded-national-address-file-g-naf'
        WHEN '10000000-0000-0000-0000-000000000002' THEN
            'https://valuation.property.nsw.gov.au/embed/propertySalesInformation'
        WHEN '10000000-0000-0000-0000-000000000003' THEN
            'https://bocsar.nsw.gov.au/statistics-dashboards/open-datasets.html'
        WHEN '10000000-0000-0000-0000-000000000004' THEN
            'https://data.nsw.gov.au/data/dataset/nsw-education-data-hub'
        ELSE source_url
    END,
    notes = CASE id
        WHEN '10000000-0000-0000-0000-000000000004' THEN
            'Live transport connected through a registered bounded Data.NSW resource URL.'
        ELSE 'Catalogue and attribution metadata; live transport is not connected in Release 0.'
    END,
    updated_at = '2026-08-13T00:00:00Z'
WHERE id IN (
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000004'
);
