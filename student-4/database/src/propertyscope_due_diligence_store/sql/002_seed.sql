-- Student 4 - deterministic seed data (>= 10 rows per assessed table).
-- Property references intentionally align with the Feature 1 fixture properties
-- (a0000000-...-0000000000NN) so cross-feature property validation can be demonstrated.

INSERT INTO due_diligence.site_review
    (id, property_ref, address_display, title, status, disposition, checklist,
     verification_questions, notes)
SELECT
    ('d4000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
    ('a0000000-0000-0000-0000-' || lpad(i::text, 12, '0')),
    (ARRAY[
        '11 Example Street, Sydney NSW 2000',
        '12 Example Street, Parramatta NSW 2150',
        '13 Example Street, Newtown NSW 2042',
        '14 Example Street, Mosman NSW 2088',
        'Unit 5, 15 Example Street, Wollongong NSW 2500',
        '16 Example Street, Sydney NSW 2000',
        '17 Example Street, Penrith NSW 2750',
        '18 Example Street, Bondi NSW 2026',
        '19 Example Street, Chatswood NSW 2067',
        '20 Example Street, Liverpool NSW 2170'
    ])[i],
    'Due-diligence review ' || i,
    (ARRAY['draft', 'in_review', 'completed', 'archived', 'draft',
           'in_review', 'completed', 'draft', 'in_review', 'completed'])[i],
    (ARRAY['undecided', 'proceed', 'hold', 'do_not_proceed', 'undecided',
           'proceed', 'hold', 'undecided', 'proceed', 'hold'])[i],
    '[{"item": "Confirm zoning permits the intended use", "done": false},
      {"item": "Check flood and bushfire exposure", "done": false},
      {"item": "Review strata and building orders", "done": false}]'::jsonb,
    '[]'::jsonb,
    'Seed record ' || i || ' - replace with real due-diligence content.'
FROM generate_series(1, 10) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO due_diligence.constraint_observation
    (id, property_ref, constraint_type, evidence_state, source_name, source_url,
     summary, observed_value, match_method, confidence, dataset_release_id)
SELECT
    ('c4000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
    ('a0000000-0000-0000-0000-' || lpad(i::text, 12, '0')),
    (ARRAY['zoning', 'heritage', 'floor_space_ratio', 'building_height', 'flood',
           'bushfire', 'land_reservation', 'acid_sulfate_soils', 'contamination',
           'biodiversity'])[i],
    (ARRAY['confirmed', 'confirmed', 'partial_coverage', 'confirmed', 'non_intersection',
           'confirmed', 'unavailable', 'partial_coverage', 'non_intersection',
           'confirmed'])[i],
    (ARRAY['NSW Planning Portal', 'NSW Heritage Register', 'NSW Planning Portal',
           'NSW Planning Portal', 'NSW SES Flood Data', 'NSW RFS Bushfire Prone Land',
           'NSW Planning Portal', 'NSW Planning Portal', 'NSW EPA Contaminated Land',
           'NSW BioNet'])[i],
    'https://www.planningportal.nsw.gov.au/',
    (ARRAY[
        'Zoned R2 Low Density Residential under the local environmental plan.',
        'Item is not listed on the State Heritage Register.',
        'Floor space ratio control applies; confirm exact figure with council.',
        'Maximum building height control of 9.5 m applies.',
        'Property sits outside the mapped 1% AEP flood extent.',
        'Property is within a mapped bushfire prone land category.',
        'No current road or land reservation intersects the parcel.',
        'Partial acid sulfate soils mapping; confirm class before excavation.',
        'No contamination record intersects the parcel in available data.',
        'A threatened ecological community is mapped nearby.'
    ])[i],
    (ARRAY['R2 Low Density Residential', 'Not heritage listed', 'FSR 0.5:1',
           'Max height 9.5 m', 'Outside mapped flood extent', 'Bushfire Category 1',
           'No current reservation', 'Class 3 acid sulfate soils',
           'No recorded contamination', 'Endangered ecological community'])[i],
    'property_centroid',
    (ARRAY[0.98, 0.95, 0.80, 0.97, 0.99, 0.93, 0.70, 0.82, 0.90, 0.85])[i]::numeric(4, 3),
    'evidence-release-2026-01'
FROM generate_series(1, 10) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO due_diligence.building_observation
    (id, property_ref, record_type, evidence_state, reference_code, source_name,
     source_url, summary, match_method, confidence, observed_on)
SELECT
    ('b4000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
    ('a0000000-0000-0000-0000-' || lpad(i::text, 12, '0')),
    (ARRAY['strata', 'building_order', 'undertaking', 'tribunal', 'strata',
           'building_order', 'undertaking', 'tribunal', 'strata', 'building_order'])[i],
    (ARRAY['confirmed', 'confirmed', 'partial_coverage', 'confirmed', 'non_intersection',
           'confirmed', 'unavailable', 'confirmed', 'partial_coverage',
           'non_intersection'])[i],
    ('REF-' || lpad(i::text, 5, '0')),
    (ARRAY['NSW Strata Hub', 'NSW Fair Trading', 'NSW Fair Trading', 'NCAT',
           'NSW Strata Hub', 'NSW Fair Trading', 'NSW Fair Trading', 'NCAT',
           'NSW Strata Hub', 'NSW Fair Trading'])[i],
    'https://www.nsw.gov.au/',
    (ARRAY[
        'Registered strata scheme with an active managing agent.',
        'A building order was issued and later marked resolved.',
        'A written undertaking is recorded against the building.',
        'A tribunal matter concerning building defects was recorded.',
        'No strata scheme applies to this parcel.',
        'A fire safety building order is currently recorded.',
        'Undertaking coverage is unavailable for this address.',
        'A tribunal order regarding repairs was made.',
        'Partial strata record; confirm current management details.',
        'No building order intersects the parcel in available data.'
    ])[i],
    'address_match',
    (ARRAY[0.96, 0.92, 0.78, 0.99, 0.97, 0.90, 0.72, 0.98, 0.81, 0.88])[i]::numeric(4, 3),
    (DATE '2026-01-01' + (i * 7))
FROM generate_series(1, 10) AS i
ON CONFLICT (id) DO NOTHING;
