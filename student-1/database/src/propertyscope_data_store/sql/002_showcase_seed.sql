-- Deterministic showcase evidence. IDs are stable so browser journeys and tests can cite them.
INSERT INTO ops.source_definition (
    id, name, publisher, source_url, adapter_key, cadence, licence_id, licence_url,
    redistribution_policy, target_features_json, status, notes, created_at, updated_at, version
)
SELECT ('10000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       (ARRAY['G-NAF NSW','NSW Valuer General PSI','BOCSAR crime','NSW government schools',
              'NSW planning sample','LEP flood overlay','RFS bushfire prone land','NSW strata schemes',
              'Building orders','Deterministic fixture'])[i],
       (ARRAY['Geoscape Australia','NSW Valuer General','NSW BOCSAR','NSW Department of Education',
              'NSW Planning Portal','NSW councils','NSW RFS','NSW Fair Trading',
              'NSW Fair Trading','PropertyScope'])[i],
       'https://example.invalid/attribution/source-' || i,
       (ARRAY['gnaf-nsw','psi-sales','bocsar-bulk','schools-master','arcgis-planning',
              'arcgis-planning','arcgis-planning','manual-versioned','manual-versioned','fixture'])[i],
       CASE WHEN i IN (3,4) THEN 'quarterly-expected' ELSE 'source-release-driven' END,
       CASE WHEN i = 10 THEN 'CC0-1.0' ELSE 'source-terms' END,
       'https://example.invalid/licence/' || i,
       CASE WHEN i = 10 THEN 'fixture-redistributable' ELSE 'metadata-only' END,
       jsonb_build_array('feature-' || LEAST(i, 5)),
       CASE WHEN i IN (9) THEN 'disabled' WHEN i IN (8) THEN 'draft' ELSE 'active' END,
       'Showcase source metadata; URL is attribution only and cannot direct acquisition.',
       '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z', 1
FROM generate_series(1, 10) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.job_definition (
    id, source_definition_id, name, profile_key, profile_version, adapter_key,
    release_builder_key, import_profile_key, import_profile_version, target_feature,
    dataset_id, refresh_strategy, default_run_mode, scope_json, quality_policy_key,
    quality_policy_version, max_parallelism, timeout_seconds, max_objects, max_bytes,
    max_rows, status, schedule_text, created_at, updated_at, version
)
SELECT ('20000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       ('10000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       'Showcase job ' || lpad(i::text, 2, '0'), 'showcase-' || i, '1.0.0',
       (ARRAY['gnaf-nsw','psi-sales','bocsar-bulk','schools-master','arcgis-planning',
              'arcgis-planning','arcgis-planning','manual-versioned','manual-versioned','fixture'])[i],
       'release-builder-' || i, 'import-profile-' || i, '1.0.0',
       'feature-' || LEAST(i, 5), 'dataset-' || i,
       CASE WHEN i = 2 THEN 'append_only_partitioned' WHEN i IN (5,6,7) THEN 'partitioned_snapshot'
            WHEN i IN (8,9) THEN 'manual_versioned_import' ELSE 'full_snapshot' END,
       'full_refresh', jsonb_build_object('profile','showcase','partitions',jsonb_build_array(i)),
       'quality-policy-' || i, '1.0.0', 1, 900, 10, 50000000, 100000,
       CASE WHEN i IN (8,9) THEN 'draft' ELSE 'active' END, NULL,
       '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z', 1
FROM generate_series(1, 10) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.ingestion_run (
    id, job_definition_id, source_definition_id, adapter_version, release_builder_version,
    import_profile_version, normalisation_version, profile_key, run_mode,
    requested_scope_json, source_snapshot_json, input_checkpoint_json, output_checkpoint_json,
    accepted_watermark_json, attempt_number, parent_run_id, requested_at, started_at, finished_at,
    status, rows_discovered, rows_staged, rows_accepted, rows_rejected, error_json,
    lease_owner, lease_token, lease_expires_at, heartbeat_at, cancel_requested_at,
    request_id, idempotency_key, created_at
)
SELECT ('30000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       ('20000000-0000-0000-0000-' || lpad(LEAST(i,10)::text, 12, '0'))::uuid,
       ('10000000-0000-0000-0000-' || lpad(LEAST(i,10)::text, 12, '0'))::uuid,
       '1.0.0','1.0.0','1.0.0','1.0.0','showcase-' || LEAST(i,10),
       CASE WHEN i IN (6,12) THEN 'reprocess_cached' ELSE 'full_refresh' END,
       jsonb_build_object('profile','showcase','partition',i),
       jsonb_build_object('source_release','fixture-2026-08','objects',jsonb_build_array('object-' || i)),
       jsonb_build_object('captured',i-1), jsonb_build_object('captured',i),
       jsonb_build_object('accepted',GREATEST(i-1,0)), 1,
       CASE WHEN i = 12 THEN '30000000-0000-0000-0000-000000000003'::uuid ELSE NULL END,
       ('2026-08-01T00:00:00Z'::timestamptz + i * interval '1 hour'),
       ('2026-08-01T00:01:00Z'::timestamptz + i * interval '1 hour'),
       ('2026-08-01T00:02:00Z'::timestamptz + i * interval '1 hour'),
       (ARRAY['succeeded','succeeded','failed','succeeded','cancelled','succeeded',
              'succeeded','succeeded','succeeded','succeeded','interrupted','succeeded'])[i],
       100+i, 100+i, CASE WHEN i IN (3,5,11) THEN 0 ELSE 98+i END,
       CASE WHEN i IN (3,5,11) THEN 2 ELSE 0 END,
       CASE WHEN i = 3 THEN jsonb_build_object('code','quality_gate_failed','message','Required BOCSAR month is missing')
            WHEN i = 5 THEN jsonb_build_object('code','cancelled','message','Cancelled by operator')
            WHEN i = 11 THEN jsonb_build_object('code','lease_expired','message','Runner heartbeat expired') ELSE NULL END,
       NULL,NULL,NULL,NULL, CASE WHEN i=5 THEN '2026-08-01T05:01:30Z'::timestamptz ELSE NULL END,
       'seed-request-' || i, 'seed-run-' || i,
       ('2026-08-01T00:00:00Z'::timestamptz + i * interval '1 hour')
FROM generate_series(1, 12) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.run_task (
    id, ingestion_run_id, logical_key, partition_json, stage, status, attempt_number,
    started_at, finished_at, rows_in, rows_out, error_json, lease_owner, lease_token,
    lease_expires_at, heartbeat_at, created_at, updated_at, version
)
SELECT ('40000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       ('30000000-0000-0000-0000-' || lpad((((i-1)%12)+1)::text, 12, '0'))::uuid,
       'fixture/object-' || i, jsonb_build_object('partition',i),
       (ARRAY['discover','acquire','validate_artifact','import','normalise','quality','build_release'])[((i-1)%7)+1],
       CASE WHEN i IN (6,13) THEN 'failed' WHEN i IN (11,18) THEN 'cancelled' ELSE 'succeeded' END,
       CASE WHEN i IN (8,16) THEN 2 ELSE 1 END,
       '2026-08-02T00:00:00Z','2026-08-02T00:01:00Z', 10+i, 10+i,
       CASE WHEN i IN (6,13) THEN jsonb_build_object('code','quality_gate_failed','message','Fixture blocking rule failed') ELSE NULL END,
       NULL,NULL,NULL,NULL,'2026-08-02T00:00:00Z','2026-08-02T00:01:00Z',1
FROM generate_series(1, 24) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.artifact_record (
    id, ingestion_run_id, run_task_id, logical_key, artifact_kind, storage_key,
    source_uri_redacted, content_sha256, media_type, bytes, etag, source_last_modified,
    schema_version, retention_class, created_at
)
SELECT ('50000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       ('30000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       ('40000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       'fixture/artifact-' || i, CASE WHEN i <= 10 THEN 'release_export' ELSE 'source_raw' END,
       'sha256/' || encode(digest('artifact-' || i, 'sha256'),'hex'),
       'source-' || i || '/object', encode(digest('artifact-' || i, 'sha256'),'hex'),
       'application/json', 1000+i, NULL, '2026-08-01T00:00:00Z','propertyscope.fixture.v1',
       CASE WHEN i <= 10 THEN 'accepted-release' ELSE 'candidate' END,'2026-08-02T00:00:00Z'
FROM generate_series(1, 12) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.dataset_release (
    id, dataset_id, source_definition_id, ingestion_run_id, target_feature, release_version,
    schema_version, coverage_json, record_count, content_sha256, artifact_record_id,
    manifest_json, status, review_comment, accepted_at, supersedes_release_id,
    created_at, updated_at, version
)
SELECT ('60000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       CASE WHEN i <= 10 THEN 'dataset-' || i ELSE 'dataset-3' END,
       ('10000000-0000-0000-0000-' || lpad(LEAST(i,10)::text, 12, '0'))::uuid,
       ('30000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       'feature-' || LEAST(CASE WHEN i <= 10 THEN i ELSE 3 END,5),
       CASE WHEN i <= 10 THEN '2026.08.' || i ELSE '2026.09.' || i END,
       CASE WHEN i IN (3,11,12) THEN 'propertyscope.crime-series.v1' ELSE 'propertyscope.fixture.v1' END,
       jsonb_build_object('state','NSW','profile','showcase','complete',i <> 11),
       CASE WHEN i=11 THEN 90 ELSE 100+i END,
       encode(digest('artifact-' || i, 'sha256'),'hex'),
       ('50000000-0000-0000-0000-' || lpad(i::text, 12, '0'))::uuid,
       jsonb_build_object('release_id','seed-release-' || i,'dataset_id',CASE WHEN i<=10 THEN 'dataset-'||i ELSE 'dataset-3' END,
                          'schema_version',CASE WHEN i IN (3,11,12) THEN 'propertyscope.crime-series.v1' ELSE 'propertyscope.fixture.v1' END,
                          'known_limitations',jsonb_build_array('Synthetic showcase evidence')),
       CASE WHEN i <= 10 THEN 'accepted' WHEN i=11 THEN 'candidate' ELSE 'rejected' END,
       CASE WHEN i=11 THEN 'Missing required month; accepted predecessor remains live.' ELSE 'Deterministic showcase review.' END,
       CASE WHEN i <= 10 THEN '2026-08-03T00:00:00Z'::timestamptz ELSE NULL END,
       CASE WHEN i=12 THEN '60000000-0000-0000-0000-000000000003'::uuid ELSE NULL END,
       '2026-08-02T00:00:00Z','2026-08-03T00:00:00Z',1
FROM generate_series(1, 12) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.import_operation (
    id, ingestion_run_id, run_task_id, candidate_release_id, import_profile_key,
    import_profile_version, artifact_record_id, status, attempt_number, idempotency_key,
    requested_at, started_at, finished_at, rows_in, rows_staged, rows_accepted, rows_rejected,
    result_json, error_json, version
)
SELECT ('70000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       ('30000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       ('40000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       ('60000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       'import-profile-' || LEAST(i,10),'1.0.0',
       ('50000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       (ARRAY['succeeded','succeeded','failed','succeeded','cancelled','succeeded','succeeded','succeeded','succeeded','succeeded','interrupted','succeeded'])[i],
       CASE WHEN i=12 THEN 2 ELSE 1 END, 'seed-import-' || i,
       '2026-08-02T00:00:00Z','2026-08-02T00:00:10Z','2026-08-02T00:01:00Z',
       100+i,100+i,CASE WHEN i IN (3,5,11) THEN 0 ELSE 100+i END,CASE WHEN i IN (3,5,11) THEN 100+i ELSE 0 END,
       CASE WHEN i IN (3,5,11) THEN NULL ELSE jsonb_build_object('generation','seed-'||i) END,
       CASE WHEN i=3 THEN jsonb_build_object('code','quality_gate_failed') WHEN i=5 THEN jsonb_build_object('code','cancelled')
            WHEN i=11 THEN jsonb_build_object('code','lease_expired') ELSE NULL END,1
FROM generate_series(1,12) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.quality_result (
    id, ingestion_run_id, dataset_release_id, rule_key, rule_version, dimension, severity,
    status, observed_value_json, expected_value_json, message, sample_json, created_at
)
SELECT ('80000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       ('30000000-0000-0000-0000-' || lpad((((i-1)%12)+1)::text,12,'0'))::uuid,
       ('60000000-0000-0000-0000-' || lpad((((i-1)%12)+1)::text,12,'0'))::uuid,
       'fixture-rule-' || i,'1.0.0',
       (ARRAY['schema','completeness','validity','uniqueness','coverage','drift','lineage','reproducibility'])[((i-1)%8)+1],
       CASE WHEN i IN (3,11,19) THEN 'blocking' WHEN i%4=0 THEN 'warning' ELSE 'info' END,
       CASE WHEN i IN (3,11,19) THEN 'fail' WHEN i%4=0 THEN 'warn' ELSE 'pass' END,
       jsonb_build_object('value',CASE WHEN i IN (3,11,19) THEN 11 ELSE 12 END),
       jsonb_build_object('minimum',12),
       CASE WHEN i IN (3,11,19) THEN 'Required month continuity is incomplete.' ELSE 'Fixture quality evidence.' END,
       CASE WHEN i IN (3,11,19) THEN jsonb_build_array(jsonb_build_object('month','2025-11')) ELSE NULL END,
       '2026-08-02T00:02:00Z'
FROM generate_series(1,24) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO ops.publication_receipt (
    id, dataset_release_id, target_feature, consumer_operation_id, status, schema_version,
    content_sha256, rows_received, rows_accepted, rows_rejected, error_json, request_id,
    created_at, completed_at
)
SELECT ('90000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       ('60000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       'feature-' || LEAST(i,5),'consumer-seed-' || i,'accepted','propertyscope.fixture.v1',
       encode(digest('artifact-' || i,'sha256'),'hex'),100+i,100+i,0,NULL,'seed-publish-'||i,
       '2026-08-03T00:00:00Z','2026-08-03T00:01:00Z'
FROM generate_series(1,10) AS i
ON CONFLICT (id) DO NOTHING;

INSERT INTO registry.property (
    property_ref,address_display,flat_type,unit_number,street_number_first,street_number_suffix,
    street_number_last,street_name,street_type,locality,postcode,state,address_search,geom,
    resolution_status,created_at,updated_at,version
)
SELECT ('a0000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       CASE WHEN i%5=0 THEN 'Unit '||i||', ' ELSE '' END || (10+i) || ' Example Street, ' ||
       (ARRAY['Sydney','Parramatta','Newtown','Mosman','Wollongong'])[((i-1)%5)+1] || ' NSW ' ||
       (ARRAY['2000','2150','2042','2088','2500'])[((i-1)%5)+1],
       CASE WHEN i%5=0 THEN 'UNIT' ELSE NULL END, CASE WHEN i%5=0 THEN i::text ELSE NULL END,
       10+i,NULL,NULL,'EXAMPLE','STREET',
       (ARRAY['SYDNEY','PARRAMATTA','NEWTOWN','MOSMAN','WOLLONGONG'])[((i-1)%5)+1],
       (ARRAY['2000','2150','2042','2088','2500'])[((i-1)%5)+1],'NSW',
       lower(CASE WHEN i%5=0 THEN 'unit '||i||' ' ELSE '' END || (10+i) || ' example street ' ||
             (ARRAY['sydney','parramatta','newtown','mosman','wollongong'])[((i-1)%5)+1] || ' nsw'),
       ST_SetSRID(ST_MakePoint(151.0 + (i%10)*0.01, -34.0 + (i%10)*0.01),4326),
       CASE WHEN i IN (29,30) THEN 'provisional' ELSE 'verified' END,
       '2026-08-01T00:00:00Z','2026-08-01T00:00:00Z',1
FROM generate_series(1,30) AS i
ON CONFLICT (property_ref) DO NOTHING;

INSERT INTO registry.property_identifier (
    id,property_ref,scheme,identifier_value,source_release_id,is_current,valid_from,valid_to,
    match_method,match_confidence,evidence_json,created_at
)
SELECT ('a1000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       ('a0000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,'GNAF_PID','GANSW'||lpad(i::text,8,'0'),
       '60000000-0000-0000-0000-000000000001'::uuid,true,'2026-05-01',NULL,'pid_continuity',1.0,
       jsonb_build_object('source','synthetic fixture','release','2026-05'),'2026-08-01T00:00:00Z'
FROM generate_series(1,15) AS i ON CONFLICT (id) DO NOTHING;

INSERT INTO registry.address_alias (
    id,property_ref,alias_display,alias_search,alias_kind,source_release_id,source_identifier,is_current,created_at
)
SELECT ('a2000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       ('a0000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       (10+i)||' EXAMPLE ST',''||(10+i)||' example st','source_abbreviation',
       '60000000-0000-0000-0000-000000000001'::uuid,'GANSW'||lpad(i::text,8,'0'),true,'2026-08-01T00:00:00Z'
FROM generate_series(1,15) AS i ON CONFLICT (id) DO NOTHING;

INSERT INTO registry.unresolved_match (
    id,dataset_release_id,source_record_key,source_address_json,candidate_property_refs,
    reason_code,resolver_key,resolver_version,status,review_comment,resolved_property_ref,created_at,resolved_at
)
SELECT ('a3000000-0000-0000-0000-' || lpad(i::text,12,'0'))::uuid,
       '60000000-0000-0000-0000-000000000011'::uuid,'unresolved-'||i,
       jsonb_build_object('unit',i,'street','EXAMPLE STREET'),
       jsonb_build_array(jsonb_build_object('property_ref','a0000000-0000-0000-0000-'||lpad(i::text,12,'0'),'score',0.8)),
       CASE WHEN i%2=0 THEN 'unit_ambiguity' ELSE 'geometry_conflict' END,'property-resolver','1.0.0','open',
       NULL,NULL,'2026-08-02T00:00:00Z',NULL
FROM generate_series(1,10) AS i ON CONFLICT (id) DO NOTHING;

INSERT INTO warehouse.gnaf_address
SELECT '60000000-0000-0000-0000-000000000001'::uuid,'GANSW'||lpad(i::text,8,'0'),
       ('a0000000-0000-0000-0000-'||lpad(i::text,12,'0'))::uuid,(10+i)||' Example Street, Sydney NSW 2000',
       'SYDNEY','2000','CURRENT','PROPERTY_CENTROID',4283,
       ST_SetSRID(ST_MakePoint(151.0+i*0.001,-34.0+i*0.001),4326),encode(digest('gnaf-'||i,'sha256'),'hex'),'1.0.0',
       '50000000-0000-0000-0000-000000000001'::uuid,'30000000-0000-0000-0000-000000000001'::uuid,'2026-08-02T00:00:00Z'
FROM generate_series(1,10) AS i ON CONFLICT DO NOTHING;

INSERT INTO warehouse.psi_sale
SELECT '60000000-0000-0000-0000-000000000002'::uuid,'psi-key-'||i,1,'post-2001','001','P'||i,'D'||i,
       ('2025-01-01'::date+i),('2025-02-01'::date+i),750000+i*10000,500,'M',500,
       ('a0000000-0000-0000-0000-'||lpad(i::text,12,'0'))::uuid,'A',0.98,'property',
       encode(digest('psi-'||i,'sha256'),'hex'),'1.0.0','50000000-0000-0000-0000-000000000002'::uuid,
       '30000000-0000-0000-0000-000000000002'::uuid,'2026-08-02T00:00:00Z'
FROM generate_series(1,10) AS i ON CONFLICT DO NOTHING;

INSERT INTO warehouse.bocsar_observation
SELECT '60000000-0000-0000-0000-000000000003'::uuid,'postcode',lpad((1999+i)::text,4,'0'),'OFFENCE-'||i,
       'Offence '||i,'Subcategory '||i,('2025-01-01'::date+(i-1)*interval '1 month')::date,i,
       encode(digest('bocsar-observation-'||i,'sha256'),'hex'),'1.0.0','50000000-0000-0000-0000-000000000003'::uuid,
       '30000000-0000-0000-0000-000000000003'::uuid,'2026-08-02T00:00:00Z'
FROM generate_series(1,10) AS i ON CONFLICT DO NOTHING;

INSERT INTO warehouse.bocsar_coverage
SELECT '60000000-0000-0000-0000-000000000003'::uuid,'postcode',lpad((1999+i)::text,4,'0'),'OFFENCE-'||i,
       ARRAY['2025-01-01'::date,'2025-02-01'::date,'2025-03-01'::date],
       '2025-01-01','2025-03-01',3,true,encode(digest('months-q1','sha256'),'hex'),
       encode(digest('bocsar-coverage-'||i,'sha256'),'hex'),'1.0.0','50000000-0000-0000-0000-000000000003'::uuid,
       '30000000-0000-0000-0000-000000000003'::uuid,'2026-08-02T00:00:00Z'
FROM generate_series(1,10) AS i ON CONFLICT DO NOTHING;

INSERT INTO warehouse.school
SELECT '60000000-0000-0000-0000-000000000004'::uuid,'S'||lpad(i::text,4,'0'),'Example Public School '||i,
       'Primary','Open','Sydney ','SYDNEY','CITY OF SYDNEY',ST_SetSRID(ST_MakePoint(151+i*0.001,-34+i*0.001),4326),
       encode(digest('school-'||i,'sha256'),'hex'),'1.0.0','50000000-0000-0000-0000-000000000004'::uuid,
       '30000000-0000-0000-0000-000000000004'::uuid,'2026-08-02T00:00:00Z'
FROM generate_series(1,10) AS i ON CONFLICT DO NOTHING;

INSERT INTO warehouse.spatial_feature
SELECT '60000000-0000-0000-0000-000000000005'::uuid,'planning-sample','zoning','feature-'||i,4326,
       jsonb_build_object('xmin',151.0,'ymin',-34.0,'xmax',151.1,'ymax',-33.9),
       ST_Buffer(ST_SetSRID(ST_MakePoint(151+i*0.001,-34+i*0.001),4326),0.0005),
       ST_Buffer(ST_SetSRID(ST_MakePoint(151+i*0.001,-34+i*0.001),4326),0.0005),
       '2025-01-01',NULL,jsonb_build_object('zone','R'||i),'identity-4326.v1',
       encode(digest('spatial-'||i,'sha256'),'hex'),'1.0.0','50000000-0000-0000-0000-000000000005'::uuid,
       '30000000-0000-0000-0000-000000000005'::uuid,'2026-08-02T00:00:00Z'
FROM generate_series(1,10) AS i ON CONFLICT DO NOTHING;

INSERT INTO serving.accepted_generation (dataset_id,target_feature,dataset_release_id,activated_at,activated_by,version)
SELECT 'dataset-'||i,'feature-'||LEAST(i,5),('60000000-0000-0000-0000-'||lpad(i::text,12,'0'))::uuid,
       '2026-08-03T00:00:00Z','showcase-seed',1 FROM generate_series(1,10) AS i
ON CONFLICT (dataset_id,target_feature) DO NOTHING;

INSERT INTO serving.property_coverage
SELECT ('a0000000-0000-0000-0000-'||lpad(i::text,12,'0'))::uuid,'dataset-'||(((i-1)%10)+1),
       'feature-'||LEAST(((i-1)%10)+1,5),('60000000-0000-0000-0000-'||lpad((((i-1)%10)+1)::text,12,'0'))::uuid,
       CASE WHEN i%7=0 THEN 'partial' ELSE 'supported' END,jsonb_build_object('state','NSW','profile','showcase'),
       '2026-08-03T00:00:00Z' FROM generate_series(1,30) AS i
ON CONFLICT (property_ref,dataset_id,target_feature) DO NOTHING;

INSERT INTO ops.idempotency_record (scope,idempotency_key,request_sha256,status_code,response_json)
SELECT 'showcase','seed-operation-'||i,encode(digest('request-'||i,'sha256'),'hex'),200,
       jsonb_build_object('status','applied','operation',i) FROM generate_series(1,10) AS i
ON CONFLICT (scope,idempotency_key) DO NOTHING;
