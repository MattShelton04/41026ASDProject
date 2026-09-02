-- Student 4 - richer evidence.
--
-- The initial seed (002) gave each property a single constraint and building
-- observation. This migration adds a full, source-attributed set for every
-- property so the site-review detail view shows the complete planning,
-- environmental, strata and building picture, spanning all four evidence states
-- (confirmed, partial coverage, non-intersection and unavailable).

-- Planning and environmental constraints: one row per property x constraint type.
INSERT INTO due_diligence.constraint_observation
    (id, property_ref, constraint_type, evidence_state, source_name, source_url,
     summary, observed_value, match_method, confidence, dataset_release_id)
SELECT
    ('c4000002-0000-0000-0000-' || lpad((p * 10 + t.rank)::text, 12, '0'))::uuid,
    ('a0000000-0000-0000-0000-' || lpad(p::text, 12, '0')),
    t.constraint_type,
    (ARRAY['confirmed', 'partial_coverage', 'non_intersection', 'unavailable'])[
        1 + ((p + t.rank) % 4)
    ],
    t.source_name,
    t.source_url,
    t.summary,
    t.observed_value,
    'property_centroid',
    (0.80 + ((p + t.rank) % 5) * 0.04)::numeric(4, 3),
    'evidence-release-2026-02'
FROM generate_series(1, 10) AS p
CROSS JOIN (
    VALUES
        (1, 'zoning', 'NSW Planning Portal', 'https://www.planningportal.nsw.gov.au/',
         'Land zoning control from the local environmental plan.',
         'R2 Low Density Residential'),
        (2, 'heritage', 'NSW Heritage Register', 'https://www.hms.heritage.nsw.gov.au/',
         'Heritage listing status recorded for the parcel.', 'Not a listed heritage item'),
        (3, 'floor_space_ratio', 'NSW Planning Portal', 'https://www.planningportal.nsw.gov.au/',
         'Maximum floor space ratio development standard.', 'FSR 0.5:1'),
        (4, 'building_height', 'NSW Planning Portal', 'https://www.planningportal.nsw.gov.au/',
         'Maximum building height development standard.', 'Maximum 9.5 m'),
        (5, 'flood', 'NSW SES and council flood mapping', 'https://www.ses.nsw.gov.au/',
         'Flood planning area exposure for the parcel.', '1% AEP flood planning area'),
        (6, 'bushfire', 'NSW RFS bushfire prone land', 'https://www.rfs.nsw.gov.au/',
         'Bushfire prone land mapping category.', 'Vegetation Category 1')
) AS t (rank, constraint_type, source_name, source_url, summary, observed_value)
ON CONFLICT (id) DO NOTHING;

-- Strata, building-order, undertaking and tribunal evidence.
INSERT INTO due_diligence.building_observation
    (id, property_ref, record_type, evidence_state, reference_code, source_name,
     source_url, summary, match_method, confidence, observed_on)
SELECT
    ('b4000002-0000-0000-0000-' || lpad((p * 10 + t.rank)::text, 12, '0'))::uuid,
    ('a0000000-0000-0000-0000-' || lpad(p::text, 12, '0')),
    t.record_type,
    (ARRAY['confirmed', 'partial_coverage', 'non_intersection', 'unavailable'])[
        1 + ((p + t.rank + 1) % 4)
    ],
    'REF-' || lpad((p * 10 + t.rank)::text, 5, '0'),
    t.source_name,
    t.source_url,
    t.summary,
    'address_match',
    (0.82 + ((p + t.rank) % 4) * 0.04)::numeric(4, 3),
    (DATE '2026-02-01' + (p * 3))
FROM generate_series(1, 10) AS p
CROSS JOIN (
    VALUES
        (1, 'strata', 'NSW Strata Hub', 'https://www.nsw.gov.au/',
         'Strata scheme registration and management status.'),
        (2, 'building_order', 'NSW Fair Trading', 'https://www.nsw.gov.au/',
         'Building orders or rectification notices recorded against the building.'),
        (3, 'undertaking', 'NSW Fair Trading', 'https://www.nsw.gov.au/',
         'Written undertakings recorded against the building.'),
        (4, 'tribunal', 'NCAT', 'https://www.ncat.nsw.gov.au/',
         'Tribunal matters concerning the building.')
) AS t (rank, record_type, source_name, source_url, summary)
ON CONFLICT (id) DO NOTHING;
