UPDATE sale_observation
SET property_ref = 'a0000000-0000-0000-0000-000000000001'
WHERE property_ref = '11111111-1111-4111-8111-111111111111';

UPDATE market_case
SET property_ref = 'a0000000-0000-0000-0000-000000000001'
WHERE property_ref = '11111111-1111-4111-8111-111111111111';

UPDATE market_case
SET property_validation_state = 'fixture_verified'
WHERE property_ref = 'a0000000-0000-0000-0000-000000000001'
  AND property_validation_state = 'synthetic_fixture';
