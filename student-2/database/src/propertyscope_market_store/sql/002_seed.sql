WITH sale_seed(
    sequence, property_ref, address_display, contract_date, price_aud,
    locality, postcode, match_tier, confidence, release_version
) AS (
    VALUES
    (1, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2019-03-14', 790000, 'SYDNEY', '2000', 'A', 1.0, 'fixture-2026-r1'),
    (2, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2020-06-18', 835000, 'SYDNEY', '2000', 'A', 1.0, 'fixture-2026-r1'),
    (3, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2021-02-02', 880000, 'SYDNEY', '2000', 'A', 0.99, 'fixture-2026-r1'),
    (4, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2021-11-26', 925000, 'SYDNEY', '2000', 'B', 0.93, 'fixture-2026-r1'),
    (5, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2022-08-19', 970000, 'SYDNEY', '2000', 'A', 1.0, 'fixture-2026-r1'),
    (6, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2023-04-10', 1015000, 'SYDNEY', '2000', 'A', 1.0, 'fixture-2026-r1'),
    (7, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2023-12-05', 1040000, 'SYDNEY', '2000', 'B', 0.95, 'fixture-2026-r1'),
    (8, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2024-05-27', 1085000, 'SYDNEY', '2000', 'A', 1.0, 'fixture-2026-r1'),
    (9, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2025-01-16', 1120000, 'SYDNEY', '2000', 'A', 1.0, 'fixture-2026-r1'),
    (10, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2025-09-01', 1165000, 'SYDNEY', '2000', 'A', 0.99, 'fixture-2026-r1'),
    (11, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2025-10-01', 0, 'SYDNEY', '2000', 'A', 1.0, 'fixture-2026-r1'),
    (12, 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2025-12-01', 1195000, 'SYDNEY', '2000', 'D', 0.45, 'fixture-2026-r1'),
    (13, '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2020-01-17', 610000, 'NEWCASTLE', '2300', 'A', 1.0, 'fixture-2026-r1'),
    (14, '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2021-07-08', 655000, 'NEWCASTLE', '2300', 'A', 0.99, 'fixture-2026-r1'),
    (15, '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2022-03-22', 700000, 'NEWCASTLE', '2300', 'B', 0.94, 'fixture-2026-r1'),
    (16, '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2023-02-11', 735000, 'NEWCASTLE', '2300', 'A', 1.0, 'fixture-2026-r1'),
    (17, '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2023-10-30', 760000, 'NEWCASTLE', '2300', 'A', 0.98, 'fixture-2026-r1'),
    (18, '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2024-09-06', 805000, 'NEWCASTLE', '2300', 'A', 1.0, 'fixture-2026-r1'),
    (19, '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2025-03-03', 830000, 'NEWCASTLE', '2300', 'B', 0.92, 'fixture-2026-r1'),
    (20, '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2026-02-13', 875000, 'NEWCASTLE', '2300', 'A', 1.0, 'fixture-2026-r1'),
    (21, '33333333-3333-4333-8333-333333333333', '25 Park Avenue, Wollongong NSW 2500', '2021-05-09', 720000, 'WOLLONGONG', '2500', 'A', 1.0, 'fixture-2026-r1'),
    (22, '33333333-3333-4333-8333-333333333333', '25 Park Avenue, Wollongong NSW 2500', '2022-12-12', 755000, 'WOLLONGONG', '2500', 'A', 1.0, 'fixture-2026-r1'),
    (23, '33333333-3333-4333-8333-333333333333', '25 Park Avenue, Wollongong NSW 2500', '2023-08-21', 790000, 'WOLLONGONG', '2500', 'B', 0.91, 'fixture-2026-r1'),
    (24, '33333333-3333-4333-8333-333333333333', '25 Park Avenue, Wollongong NSW 2500', '2024-02-29', 820000, 'WOLLONGONG', '2500', 'A', 1.0, 'fixture-2026-r1'),
    (25, '33333333-3333-4333-8333-333333333333', '25 Park Avenue, Wollongong NSW 2500', '2025-06-14', 860000, 'WOLLONGONG', '2500', 'A', 0.99, 'fixture-2026-r1'),
    (26, '33333333-3333-4333-8333-333333333333', '25 Park Avenue, Wollongong NSW 2500', '2026-01-05', 895000, 'WOLLONGONG', '2500', 'A', 1.0, 'fixture-2026-r1')
)
INSERT OR IGNORE INTO sale_observation (
    id, source_business_key, source_revision, source_era, property_ref,
    address_display, contract_date, settlement_date, price_aud,
    area_square_metres, locality, postcode, sale_code, interest_of_sale,
    match_tier, match_confidence, geographic_precision, release_id,
    release_version, source_record_sha256, normalisation_version,
    synthetic, created_at
)
SELECT
    printf('50000000-0000-4000-8000-%012d', sequence),
    printf('synthetic-psi:%03d', sequence), 1, 'post-2001', property_ref,
    address_display, contract_date, date(contract_date, '+30 days'), price_aud,
    500.0, locality, postcode, 'R', '1', match_tier, confidence,
    'exact_address', '50000000-0000-4000-8000-000000000001',
    release_version, lower(hex(zeroblob(32))), '1.0.0', 1,
    '2026-08-01T00:00:00Z'
FROM sale_seed;

WITH case_seed(sequence, name, property_ref, address_display, date_from, date_to, status, notes) AS (
    VALUES
    (1, 'Sydney example – full history', 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2019-01-01', '2026-12-31', 'active', 'Showcase case with two deliberately excluded records.'),
    (2, 'Sydney recent period', 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2023-01-01', '2026-12-31', 'draft', 'Focus on recent recorded transactions.'),
    (3, 'Sydney pre-2023 evidence', 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2019-01-01', '2022-12-31', 'complete', 'Archived research window.'),
    (4, 'Newcastle full history', '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2020-01-01', '2026-12-31', 'active', 'Deterministic Newcastle fixture.'),
    (5, 'Newcastle recent period', '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2023-01-01', '2026-12-31', 'draft', 'Recent transaction history only.'),
    (6, 'Newcastle 2021–2024', '22222222-2222-4222-8222-222222222222', '8 Harbour Road, Newcastle NSW 2300', '2021-01-01', '2024-12-31', 'complete', 'Completed evidence review.'),
    (7, 'Wollongong full history', '33333333-3333-4333-8333-333333333333', '25 Park Avenue, Wollongong NSW 2500', '2021-01-01', '2026-12-31', 'active', 'Deterministic Wollongong fixture.'),
    (8, 'Wollongong recent period', '33333333-3333-4333-8333-333333333333', '25 Park Avenue, Wollongong NSW 2500', '2024-01-01', '2026-12-31', 'draft', 'Small sample; limitations should remain visible.'),
    (9, 'Wollongong 2021–2023', '33333333-3333-4333-8333-333333333333', '25 Park Avenue, Wollongong NSW 2500', '2021-01-01', '2023-12-31', 'archived', 'Historical completed research.'),
    (10, 'Sydney 2025 snapshot', 'a0000000-0000-0000-0000-000000000001', '11 Example Street, Sydney NSW 2000', '2025-01-01', '2025-12-31', 'draft', 'Intentionally narrow window.')
)
INSERT OR IGNORE INTO market_case (
    id, name, property_ref, address_display, date_from, date_to, status,
    notes, filters_json, ai_run_ref, property_validation_state,
    created_at, updated_at, version
)
SELECT
    printf('60000000-0000-4000-8000-%012d', sequence), name, property_ref,
    address_display, date_from, date_to, status, notes,
    '{"minimum_match_tier":"B"}', NULL, 'synthetic_fixture',
    '2026-08-01T00:00:00Z', printf('2026-08-%02dT00:00:00Z', sequence), 1
FROM case_seed;
