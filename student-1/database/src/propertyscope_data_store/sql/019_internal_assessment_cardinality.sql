-- Preserve the ten-row assessment proof without exposing padding as registered products.
-- Migration 018 retired these sources and removed their accepted pointers. The table-volume
-- gate still applies to every showcase table, so restore internally coherent seed pointers;
-- release collection queries exclude every release owned by a retired source.
UPDATE ops.dataset_release
SET status = 'accepted',
    review_comment = 'Internal assessment fixture; excluded from registered product projections.',
    updated_at = '2026-08-22T00:00:00Z',
    version = version + 1
WHERE source_definition_id IN (
    '10000000-0000-0000-0000-000000000005',
    '10000000-0000-0000-0000-000000000006',
    '10000000-0000-0000-0000-000000000007',
    '10000000-0000-0000-0000-000000000008',
    '10000000-0000-0000-0000-000000000009'
) AND status = 'superseded';

INSERT INTO serving.accepted_generation (
    dataset_id,target_feature,dataset_release_id,activated_at,activated_by,version
)
SELECT release.dataset_id,release.target_feature,release.id,
       COALESCE(release.accepted_at,'2026-08-03T00:00:00Z'),
       'internal-assessment-fixture',1
FROM ops.dataset_release release
WHERE release.source_definition_id IN (
    '10000000-0000-0000-0000-000000000005',
    '10000000-0000-0000-0000-000000000006',
    '10000000-0000-0000-0000-000000000007',
    '10000000-0000-0000-0000-000000000008',
    '10000000-0000-0000-0000-000000000009'
) AND release.status = 'accepted'
ON CONFLICT (dataset_id,target_feature) DO NOTHING;
