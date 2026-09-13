-- Current Lot service declares Creative Commons; Spatial Services copyright specifies
-- Attribution 4.0 for its own published material. Preserve explicit attribution and dates.
UPDATE ops.source_definition
SET licence_id='cc-by-4-0', redistribution_policy='attributed-derived-release',
    updated_at=now(), version=version+1
WHERE id='b4e1417b-bdd3-5df5-a243-1494c2f76479'
  AND licence_id='nsw-spatial-open-data'
  AND redistribution_policy='licence-controlled';
