-- The current SEED catalogue links the NSW RFS hosted service. Unlike the legacy
-- MapServer, it exposes the complete geometry of the verified million-position feature.
-- Keep older run snapshots/artifacts intact; new discovery uses the current endpoint.
UPDATE ops.source_definition
SET source_url='https://portal.spatial.nsw.gov.au/server/rest/services/Hosted/NSW_BushFire_Prone_Land/FeatureServer/0',
    updated_at=now(), version=version+1
WHERE id='d8192ca9-7087-5808-b4e5-88525b3f89b4'
  AND source_url='https://mapprod3.environment.nsw.gov.au/arcgis/rest/services/Fire/BFPL/MapServer/0';
