-- Keep the ten-row assessment seed while ensuring only registered Release 0 products are public.
UPDATE ops.source_definition
SET name = CASE id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'G-NAF Open NSW'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'NSW Valuer General property sales information'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'BOCSAR recorded crime data'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'NSW government school locations and attributes'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'Deterministic synthetic property snapshot'
        ELSE name
    END,
    publisher = CASE id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'Geoscape Australia'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'NSW Valuer General'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'NSW Bureau of Crime Statistics and Research'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'NSW Department of Education'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'PropertyScope project'
        ELSE publisher
    END,
    source_url = CASE id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'https://data.gov.au/data/dataset/geocoded-national-address-file-g-naf'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'https://valuation.property.nsw.gov.au/embed/propertySalesInformation'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'https://bocsar.nsw.gov.au/statistics-dashboards/open-datasets.html'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'https://data.nsw.gov.au/data/dataset/nsw-education-data-hub'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'https://example.invalid/propertyscope/fixtures/property.csv'
        ELSE source_url
    END,
    licence_url = CASE id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'https://data.gov.au/data/dataset/geocoded-national-address-file-g-naf'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'https://www.nsw.gov.au/departments-and-agencies/valuer-general'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'https://data.nsw.gov.au/data/policy'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'https://data.nsw.gov.au/data/policy'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'https://creativecommons.org/publicdomain/zero/1.0/'
        ELSE licence_url
    END,
    target_features_json = CASE id
        WHEN '10000000-0000-0000-0000-000000000001' THEN '["feature-1"]'::jsonb
        WHEN '10000000-0000-0000-0000-000000000002' THEN '["feature-2"]'::jsonb
        WHEN '10000000-0000-0000-0000-000000000003' THEN '["feature-3"]'::jsonb
        WHEN '10000000-0000-0000-0000-000000000004' THEN '["feature-3"]'::jsonb
        WHEN '10000000-0000-0000-0000-000000000010' THEN '["feature-1"]'::jsonb
        ELSE target_features_json
    END,
    updated_at = '2026-08-22T00:00:00Z',
    version = version + 1
WHERE id IN (
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000010'
);

UPDATE ops.source_definition
SET status = 'retired',
    notes = 'Internal assessment fixture retained only to prove deterministic table volume; not a registered data product.',
    updated_at = '2026-08-22T00:00:00Z',
    version = version + 1
WHERE id IN (
    '10000000-0000-0000-0000-000000000005',
    '10000000-0000-0000-0000-000000000006',
    '10000000-0000-0000-0000-000000000007',
    '10000000-0000-0000-0000-000000000008',
    '10000000-0000-0000-0000-000000000009'
);

UPDATE ops.job_definition
SET name = 'Internal assessment fixture job ' || right(id::text, 2),
    status = 'retired',
    schedule_text = 'Not executable; retained only for deterministic assessment volume.',
    updated_at = '2026-08-22T00:00:00Z',
    version = version + 1
WHERE id IN (
    '20000000-0000-0000-0000-000000000005',
    '20000000-0000-0000-0000-000000000006',
    '20000000-0000-0000-0000-000000000007',
    '20000000-0000-0000-0000-000000000008',
    '20000000-0000-0000-0000-000000000009'
);

UPDATE ops.dataset_release release
SET dataset_id = CASE release.source_definition_id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'gnaf-nsw'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'nsw-psi-sales'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'bocsar-crime'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'nsw-government-schools'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'fixture-property'
        ELSE release.dataset_id
    END,
    target_feature = CASE release.source_definition_id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'feature-1'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'feature-2'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'feature-3'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'feature-3'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'feature-1'
        ELSE release.target_feature
    END,
    manifest_json = jsonb_set(
        jsonb_set(
            release.manifest_json,
            '{dataset_id}',
            to_jsonb(CASE release.source_definition_id
                WHEN '10000000-0000-0000-0000-000000000001' THEN 'gnaf-nsw'
                WHEN '10000000-0000-0000-0000-000000000002' THEN 'nsw-psi-sales'
                WHEN '10000000-0000-0000-0000-000000000003' THEN 'bocsar-crime'
                WHEN '10000000-0000-0000-0000-000000000004' THEN 'nsw-government-schools'
                WHEN '10000000-0000-0000-0000-000000000010' THEN 'fixture-property'
                ELSE release.dataset_id
            END),
            true
        ),
        '{target_feature}',
        to_jsonb(CASE release.source_definition_id
            WHEN '10000000-0000-0000-0000-000000000001' THEN 'feature-1'
            WHEN '10000000-0000-0000-0000-000000000002' THEN 'feature-2'
            WHEN '10000000-0000-0000-0000-000000000003' THEN 'feature-3'
            WHEN '10000000-0000-0000-0000-000000000004' THEN 'feature-3'
            WHEN '10000000-0000-0000-0000-000000000010' THEN 'feature-1'
            ELSE release.target_feature
        END),
        true
    ),
    updated_at = '2026-08-22T00:00:00Z',
    version = version + 1
WHERE source_definition_id IN (
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000010'
);

UPDATE ops.dataset_release
SET status = 'superseded',
    review_comment = 'Internal assessment fixture; never a registered public product.',
    updated_at = '2026-08-22T00:00:00Z',
    version = version + 1
WHERE source_definition_id IN (
    '10000000-0000-0000-0000-000000000005',
    '10000000-0000-0000-0000-000000000006',
    '10000000-0000-0000-0000-000000000007',
    '10000000-0000-0000-0000-000000000008',
    '10000000-0000-0000-0000-000000000009'
) AND status = 'accepted';

DELETE FROM serving.accepted_generation accepted
USING ops.dataset_release release
WHERE accepted.dataset_release_id = release.id
  AND release.source_definition_id IN (
    '10000000-0000-0000-0000-000000000005',
    '10000000-0000-0000-0000-000000000006',
    '10000000-0000-0000-0000-000000000007',
    '10000000-0000-0000-0000-000000000008',
    '10000000-0000-0000-0000-000000000009'
  );

UPDATE serving.accepted_generation accepted
SET dataset_id = release.dataset_id, target_feature = release.target_feature
FROM ops.dataset_release release
WHERE release.id = accepted.dataset_release_id
  AND (accepted.dataset_id, accepted.target_feature)
      IS DISTINCT FROM (release.dataset_id, release.target_feature);

UPDATE serving.property_coverage coverage
SET dataset_id = release.dataset_id, target_feature = release.target_feature
FROM ops.dataset_release release
WHERE release.id = coverage.dataset_release_id
  AND (coverage.dataset_id, coverage.target_feature)
      IS DISTINCT FROM (release.dataset_id, release.target_feature);
