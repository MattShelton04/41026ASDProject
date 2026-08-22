-- Keep internal fixture keys stable while presenting the showcase data in product language.
UPDATE ops.source_definition
SET name = 'Example NSW property records',
    notes = 'Small synthetic dataset for demonstrations and offline testing.',
    updated_at = '2026-08-22T00:00:00Z',
    version = version + 1
WHERE id = '10000000-0000-0000-0000-000000000010';

UPDATE ops.job_definition
SET name = 'Example property records update',
    updated_at = '2026-08-22T00:00:00Z',
    version = version + 1
WHERE id = '20000000-0000-0000-0000-000000000010';
