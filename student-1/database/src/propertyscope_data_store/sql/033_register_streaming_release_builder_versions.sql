-- Existing durable jobs must snapshot the complete streaming builder implementation.

UPDATE ops.job_definition
SET release_builder_version = CASE release_builder_key
        WHEN 'property-snapshot' THEN '2.0.0'
        WHEN 'property-sales' THEN '3.0.0'
        WHEN 'crime-series' THEN '2.0.0'
        WHEN 'school-points' THEN '2.0.0'
        ELSE release_builder_version
    END,
    updated_at = now(),
    version = version + 1
WHERE (release_builder_key = 'property-snapshot' AND release_builder_version <> '2.0.0')
   OR (release_builder_key = 'property-sales' AND release_builder_version <> '3.0.0')
   OR (release_builder_key = 'crime-series' AND release_builder_version <> '2.0.0')
   OR (release_builder_key = 'school-points' AND release_builder_version <> '2.0.0');
