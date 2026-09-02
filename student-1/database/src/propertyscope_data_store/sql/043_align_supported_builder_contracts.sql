-- New runs must snapshot the supported gzip-NDJSON builder and record-schema versions.
-- Existing ingestion runs retain their immutable runtime evidence and are not rewritten.

UPDATE ops.job_definition
SET release_builder_version = CASE release_builder_key
        WHEN 'property-snapshot' THEN '3.0.0'
        WHEN 'property-sales' THEN '4.0.0'
        WHEN 'crime-series' THEN '3.0.0'
        WHEN 'school-points' THEN '3.0.0'
        WHEN 'seifa-area' THEN '1.0.0'
        ELSE release_builder_version
    END,
    updated_at = now(),
    version = version + 1
WHERE (release_builder_key = 'property-snapshot' AND release_builder_version <> '3.0.0')
   OR (release_builder_key = 'property-sales' AND release_builder_version <> '4.0.0')
   OR (release_builder_key = 'crime-series' AND release_builder_version <> '3.0.0')
   OR (release_builder_key = 'school-points' AND release_builder_version <> '3.0.0')
   OR (release_builder_key = 'seifa-area' AND release_builder_version <> '1.0.0');
