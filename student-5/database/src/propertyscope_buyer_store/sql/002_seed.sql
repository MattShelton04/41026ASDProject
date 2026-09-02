-- Deterministic Release 0 buyer-workspace fixtures. The first case is deliberately
-- aligned to property a000...001, which exists in Features 1, 2 and 4.

WITH seed(
    sequence, name, preferences_json, budget_min_aud, budget_max_aud,
    target_suburbs_json, status, updated_at
) AS (
    VALUES
    (1, 'Sydney evidence-ready shortlist', '{"dwelling_types":["apartment"],"priorities":["transport","planning evidence"]}', 850000, 1250000, '[{"locality":"SYDNEY","state":"NSW"}]', 'active', '2026-08-10T09:00:00Z'),
    (2, 'Parramatta first-home search', '{"dwelling_types":["unit"],"priorities":["schools","public transport"]}', 650000, 950000, '[{"locality":"PARRAMATTA","state":"NSW"}]', 'active', '2026-08-10T09:05:00Z'),
    (3, 'Inner west inspection list', '{"dwelling_types":["terrace","apartment"],"priorities":["walkability"]}', 900000, 1400000, '[{"locality":"NEWTOWN","state":"NSW"}]', 'paused', '2026-08-10T09:10:00Z'),
    (4, 'Lower north shore research', '{"dwelling_types":["apartment"],"priorities":["strata evidence"]}', 1000000, 1700000, '[{"locality":"MOSMAN","state":"NSW"}]', 'active', '2026-08-10T09:15:00Z'),
    (5, 'Wollongong family options', '{"dwelling_types":["house"],"priorities":["flood evidence","schools"]}', 700000, 1100000, '[{"locality":"WOLLONGONG","state":"NSW"}]', 'active', '2026-08-10T09:20:00Z'),
    (6, 'Sydney compact homes', '{"dwelling_types":["studio","apartment"],"priorities":["transport"]}', 550000, 800000, '[{"locality":"SYDNEY","state":"NSW"}]', 'paused', '2026-08-10T09:25:00Z'),
    (7, 'Parramatta accessibility search', '{"dwelling_types":["unit"],"priorities":["step-free access"]}', 700000, 1000000, '[{"locality":"PARRAMATTA","state":"NSW"}]', 'active', '2026-08-10T09:30:00Z'),
    (8, 'Newtown completed comparison', '{"dwelling_types":["terrace"],"priorities":["public transport"]}', 1100000, 1600000, '[{"locality":"NEWTOWN","state":"NSW"}]', 'closed', '2026-08-10T09:35:00Z'),
    (9, 'Mosman long-term options', '{"dwelling_types":["apartment"],"priorities":["building records"]}', 1200000, 2000000, '[{"locality":"MOSMAN","state":"NSW"}]', 'active', '2026-08-10T09:40:00Z'),
    (10, 'Wollongong coastal review', '{"dwelling_types":["unit","house"],"priorities":["planning evidence"]}', 750000, 1200000, '[{"locality":"WOLLONGONG","state":"NSW"}]', 'paused', '2026-08-10T09:45:00Z')
)
INSERT OR IGNORE INTO buyer_case (
    id, owner_ref, name, preferences_json, budget_min_aud, budget_max_aud,
    target_suburbs_json, status, created_at, updated_at, version
)
SELECT
    printf('b5000000-0000-4000-8000-%012d', sequence),
    'release0-demo-owner', name, preferences_json, budget_min_aud, budget_max_aud,
    target_suburbs_json, status, '2026-08-10T09:00:00Z', updated_at, 1
FROM seed;

WITH seed(
    sequence, case_sequence, property_ref, property_label, validation_state,
    journey_stage, rating, priority
) AS (
    VALUES
    (1, 1, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', 'validated', 'Reviewing', 4, 'high'),
    (2, 1, '22222222-2222-4222-8222-222222222222', '2 Sample Avenue, Mosman NSW 2088', 'validated', 'Shortlisted', 3, 'medium'),
    (3, 2, 'a0000000-0000-0000-0000-000000000002', '12 Example Street, Parramatta NSW 2150', 'validated', 'Inspecting', 5, 'high'),
    (4, 3, 'a0000000-0000-0000-0000-000000000003', '13 Example Street, Newtown NSW 2042', 'validated', 'Shortlisted', NULL, 'medium'),
    (5, 4, 'a0000000-0000-0000-0000-000000000004', '14 Example Street, Mosman NSW 2088', 'validated', 'Offer Considered', 4, 'high'),
    (6, 5, 'a0000000-0000-0000-0000-000000000005', 'Unit 5, 15 Example Street, Wollongong NSW 2500', 'validated', 'Inspecting', 4, 'high'),
    (7, 6, 'a0000000-0000-0000-0000-000000000006', '16 Example Street, Sydney NSW 2000', 'validated', 'Shortlisted', 3, 'low'),
    (8, 7, 'a0000000-0000-0000-0000-000000000007', '17 Example Street, Parramatta NSW 2150', 'validated', 'Reviewing', 5, 'high'),
    (9, 8, 'a0000000-0000-0000-0000-000000000008', '18 Example Street, Newtown NSW 2042', 'validated', 'Closed', 2, 'low'),
    (10, 9, 'a0000000-0000-0000-0000-000000000009', '19 Example Street, Mosman NSW 2088', 'validated', 'Inspecting', NULL, 'medium'),
    (11, 10, 'a0000000-0000-0000-0000-000000000010', 'Unit 10, 20 Example Street, Wollongong NSW 2500', 'unavailable', 'Shortlisted', NULL, 'medium'),
    (12, 10, '95000000-0000-4000-8000-000000000012', NULL, 'pending', 'Shortlisted', NULL, 'low')
)
INSERT OR IGNORE INTO case_property (
    id, buyer_case_id, property_ref, property_label, property_validation_state,
    journey_stage, rating, priority, created_at, updated_at, version
)
SELECT
    printf('c5000000-0000-4000-8000-%012d', sequence),
    printf('b5000000-0000-4000-8000-%012d', case_sequence),
    property_ref, property_label, validation_state, journey_stage, rating, priority,
    '2026-08-10T10:00:00Z', printf('2026-08-10T10:%02d:00Z', sequence), 1
FROM seed;

WITH seed(sequence, case_sequence, property_sequence, content) AS (
    VALUES
    (1, 1, 1, 'Feature 1, Feature 2 and Feature 4 all contain deterministic evidence for this property.'),
    (2, 1, NULL, 'Feature 3 remains unavailable in Release 0 and must be shown as missing evidence.'),
    (3, 2, 3, 'Inspection highlighted good natural light; verify strata records before progressing.'),
    (4, 3, 4, 'Keep this option paused until the budget range is reviewed.'),
    (5, 4, 5, 'Offer is only being considered; no purchase recommendation has been made.'),
    (6, 5, 6, 'Ask for current flood and planning evidence rather than assuming coverage.'),
    (7, 6, 7, 'Compact layout may not meet all stated preferences.'),
    (8, 7, 8, 'Confirm step-free access during the next inspection.'),
    (9, 8, 9, 'Comparison is closed but may be reopened by the user.'),
    (10, 9, 10, 'Building-record coverage requires verification.'),
    (11, 10, 11, 'Provider validation was unavailable when this snapshot was recorded.')
)
INSERT OR IGNORE INTO case_note (
    id, buyer_case_id, case_property_id, content, created_at, updated_at, version
)
SELECT
    printf('d5000000-0000-4000-8000-%012d', sequence),
    printf('b5000000-0000-4000-8000-%012d', case_sequence),
    CASE WHEN property_sequence IS NULL THEN NULL
         ELSE printf('c5000000-0000-4000-8000-%012d', property_sequence) END,
    content, '2026-08-10T11:00:00Z', printf('2026-08-10T11:%02d:00Z', sequence), 1
FROM seed;

WITH seed(sequence, case_sequence, property_sequence, title, due_date, completed) AS (
    VALUES
    (1, 1, 1, 'Review recorded sales exclusions', '2026-09-05', 1),
    (2, 1, 1, 'Verify due-diligence coverage with a qualified professional', '2026-09-12', 0),
    (3, 1, NULL, 'Confirm which priorities remain unassessed', '2026-09-15', 0),
    (4, 2, 3, 'Request current strata records', '2026-09-20', 0),
    (5, 3, 4, 'Recheck budget before booking another inspection', NULL, 0),
    (6, 4, 5, 'Record offer assumptions as user-supplied information', '2026-09-08', 1),
    (7, 5, 6, 'Verify flood evidence coverage', '2026-09-18', 0),
    (8, 6, 7, 'Compare layout with saved preferences', NULL, 1),
    (9, 7, 8, 'Check accessible entrance and lift', '2026-09-10', 0),
    (10, 8, 9, 'Archive external notes outside PropertyScope if no longer needed', NULL, 1),
    (11, 9, 10, 'Ask conveyancer which records require professional review', '2026-09-22', 0),
    (12, 10, 11, 'Retry Feature 1 property validation', '2026-09-06', 0)
)
INSERT OR IGNORE INTO case_task (
    id, buyer_case_id, case_property_id, title, due_date, completed,
    created_at, updated_at, version
)
SELECT
    printf('e5000000-0000-4000-8000-%012d', sequence),
    printf('b5000000-0000-4000-8000-%012d', case_sequence),
    CASE WHEN property_sequence IS NULL THEN NULL
         ELSE printf('c5000000-0000-4000-8000-%012d', property_sequence) END,
    title, due_date, completed, '2026-08-10T12:00:00Z',
    printf('2026-08-10T12:%02d:00Z', sequence), 1
FROM seed;
