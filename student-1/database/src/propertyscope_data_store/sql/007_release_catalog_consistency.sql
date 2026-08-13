-- Replace generic seed dataset identities with their registered R0 product identities.
UPDATE ops.job_definition
SET dataset_id = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'property-address-registry'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'nsw-property-sales'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'bocsar-crime'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'nsw-government-schools'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'property-fixture'
        ELSE dataset_id
    END,
    target_feature = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'feature-1'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'feature-2'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'feature-3'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'feature-3'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'feature-1'
        ELSE target_feature
    END,
    release_builder_key = CASE id
        WHEN '20000000-0000-0000-0000-000000000001' THEN 'property-snapshot'
        WHEN '20000000-0000-0000-0000-000000000002' THEN 'sales-partitions'
        WHEN '20000000-0000-0000-0000-000000000003' THEN 'crime-series'
        WHEN '20000000-0000-0000-0000-000000000004' THEN 'school-points'
        WHEN '20000000-0000-0000-0000-000000000010' THEN 'property-snapshot'
        ELSE release_builder_key
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
SET redistribution_policy = 'approved-bounded-extract', updated_at = '2026-08-13T00:00:00Z'
WHERE id = '10000000-0000-0000-0000-000000000004';

UPDATE ops.dataset_release release
SET dataset_id = CASE release.source_definition_id
        WHEN '10000000-0000-0000-0000-000000000001' THEN 'property-address-registry'
        WHEN '10000000-0000-0000-0000-000000000002' THEN 'nsw-property-sales'
        WHEN '10000000-0000-0000-0000-000000000003' THEN 'bocsar-crime'
        WHEN '10000000-0000-0000-0000-000000000004' THEN 'nsw-government-schools'
        WHEN '10000000-0000-0000-0000-000000000010' THEN 'property-fixture'
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
                WHEN '10000000-0000-0000-0000-000000000001' THEN 'property-address-registry'
                WHEN '10000000-0000-0000-0000-000000000002' THEN 'nsw-property-sales'
                WHEN '10000000-0000-0000-0000-000000000003' THEN 'bocsar-crime'
                WHEN '10000000-0000-0000-0000-000000000004' THEN 'nsw-government-schools'
                WHEN '10000000-0000-0000-0000-000000000010' THEN 'property-fixture'
                ELSE release.dataset_id
            END),
            true
        ),
        '{record_count}',
        to_jsonb(release.record_count),
        true
    ),
    updated_at = '2026-08-13T00:00:00Z'
WHERE source_definition_id IN (
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000010'
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

UPDATE ops.publication_receipt receipt
SET target_feature = release.target_feature
FROM ops.dataset_release release
WHERE release.id = receipt.dataset_release_id
  AND receipt.target_feature IS DISTINCT FROM release.target_feature;
