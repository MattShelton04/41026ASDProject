-- Make retained local showcase evidence internally coherent and explicitly synthetic.

CREATE TEMP TABLE showcase_release_contract (
    release_id UUID PRIMARY KEY,
    product_schema_version TEXT NOT NULL,
    builder_key TEXT NOT NULL,
    builder_version TEXT NOT NULL,
    import_profile TEXT NOT NULL,
    record_count BIGINT NOT NULL,
    record_count_definition TEXT NOT NULL,
    geography_coverage JSONB NOT NULL,
    temporal_coverage JSONB,
    measures JSONB NOT NULL,
    entity_types JSONB NOT NULL,
    source_release TEXT NOT NULL,
    known_limitations JSONB NOT NULL
) ON COMMIT DROP;

INSERT INTO showcase_release_contract VALUES
(
    '60000000-0000-0000-0000-000000000001',
    'propertyscope.property-snapshot.v2','property-snapshot','3.0.0','gnaf-nsw',10,
    'number of source-aligned property/address records in records',
    '["NSW:SYDNEY:2000"]','null','[]','["property_address"]',
    'synthetic-showcase-2026-08',
    '["Synthetic showcase baseline; not complete publisher coverage.","Address identity is not legal title, parcel, ownership, valuation, or occupancy evidence."]'
),
(
    '60000000-0000-0000-0000-000000000002',
    'propertyscope.property-sales.v3','property-sales','4.0.0','psi-sales',10,
    'number of unique source business-key and revision pairs in records',
    '["NSW"]','{"from":"2025-01-02","to":"2025-01-11"}',
    '["area_square_metres","price_aud"]','["property_sale"]',
    'synthetic-showcase-2026-08',
    '["Synthetic showcase baseline; not complete publisher coverage.","This product is not a valuation, forecast, comparable set, or investment recommendation."]'
),
(
    '60000000-0000-0000-0000-000000000003',
    'propertyscope.crime-series.v2','crime-series','3.0.0','bocsar-sparse',10,
    'number of geography/category series records with exact coverage universes',
    '["postcode:2000","postcode:2001","postcode:2002","postcode:2003","postcode:2004","postcode:2005","postcode:2006","postcode:2007","postcode:2008","postcode:2009"]',
    '{"from":"2025-01-01","to":"2025-03-01"}',
    '["recorded_count"]','["crime_series"]','synthetic-showcase-2026-Q1',
    '["Synthetic showcase baseline; not complete publisher coverage.","Counts do not establish rates, causes, predictions, safety, or desirability."]'
),
(
    '60000000-0000-0000-0000-000000000004',
    'propertyscope.school-points.v2','school-points','3.0.0','schools-master',10,
    'number of source school-code records in records',
    '["NSW:SYDNEY"]','null','[]','["government_school_point"]',
    'synthetic-showcase-2026-08',
    '["Synthetic showcase baseline; not complete publisher coverage.","School proximity does not establish catchment, eligibility, quality, or recommendation."]'
),
(
    '60000000-0000-0000-0000-000000000010',
    'propertyscope.property-snapshot.v2','property-snapshot','3.0.0','property-fixture',3,
    'number of source-aligned property/address records in records',
    '["NSW:MOSMAN:2088","NSW:PARRAMATTA:2150","NSW:WOLLONGONG:2500"]','null','[]',
    '["property_address"]','committed-fixture-2026-08',
    '["Small synthetic fixture for demonstration and offline tests.","Address identity is not legal title, parcel, ownership, valuation, or occupancy evidence."]'
),
(
    '60000000-0000-0000-0000-000000000011',
    'propertyscope.property-snapshot.v2','property-snapshot','3.0.0','property-fixture',3,
    'number of source-aligned property/address records in records',
    '["NSW:MOSMAN:2088","NSW:PARRAMATTA:2150","NSW:WOLLONGONG:2500"]','null','[]',
    '["property_address"]','committed-fixture-2026-08',
    '["Historical synthetic candidate retained to demonstrate interrupted-run evidence."]'
),
(
    '60000000-0000-0000-0000-000000000012',
    'propertyscope.property-snapshot.v2','property-snapshot','3.0.0','property-fixture',3,
    'number of source-aligned property/address records in records',
    '["NSW:MOSMAN:2088","NSW:PARRAMATTA:2150","NSW:WOLLONGONG:2500"]','null','[]',
    '["property_address"]','committed-fixture-2026-08',
    '["Historical synthetic candidate retained to demonstrate a rejected review."]'
);

UPDATE ops.artifact_record artifact
SET artifact_kind = 'release_export',
    media_type = 'application/x-ndjson',
    schema_version = contract.product_schema_version
FROM showcase_release_contract contract
WHERE artifact.id = (
    SELECT release.artifact_record_id
    FROM ops.dataset_release release
    WHERE release.id = contract.release_id
);

UPDATE ops.dataset_release release
SET schema_version = contract.product_schema_version,
    record_count = contract.record_count,
    coverage_json = jsonb_build_object(
        'state','NSW',
        'profile','synthetic-showcase',
        'synthetic',true,
        'complete',release.source_definition_id='10000000-0000-0000-0000-000000000010',
        'record_count',contract.record_count
    ),
    manifest_json = jsonb_build_object(
        'manifest_schema_version','propertyscope.release-manifest.v2',
        'product_schema_version',contract.product_schema_version,
        'release_id',release.id,
        'release_version',release.release_version,
        'dataset_id',release.dataset_id,
        'target_feature',release.target_feature,
        'builder_key',contract.builder_key,
        'builder_version',contract.builder_version,
        'import_profile',contract.import_profile,
        'normalisation_version','1.0.0',
        'publisher',source.publisher,
        'source',source.name,
        'source_release',contract.source_release,
        'source_retrieved_at',release.created_at,
        'source_effective_at',NULL,
        'candidate_generation_id',release.id,
        'record_count',contract.record_count,
        'record_count_definition',contract.record_count_definition,
        'content_sha256',release.content_sha256,
        'media_type','application/x-ndjson',
        'content_encoding','gzip',
        'byte_count',GREATEST(artifact.bytes,1),
        'geography_coverage',contract.geography_coverage,
        'temporal_coverage',contract.temporal_coverage,
        'measures',contract.measures,
        'entity_types',contract.entity_types,
        'source_licence',source.licence_id,
        'licence_url',source.licence_url,
        'redistribution_decision',source.redistribution_policy,
        'download_permitted',source.redistribution_policy<>'licence-controlled',
        'known_limitations',contract.known_limitations,
        'created_at',release.created_at,
        'supersedes_release_id',CASE
            WHEN release.id='60000000-0000-0000-0000-000000000012'
            THEN '60000000-0000-0000-0000-000000000010'::uuid
            ELSE release.supersedes_release_id END
    ),
    review_comment = CASE WHEN release.status IN ('accepted','superseded')
        THEN 'Synthetic local showcase baseline accepted for demonstration; not publisher coverage.'
        ELSE release.review_comment END,
    supersedes_release_id = CASE WHEN release.id='60000000-0000-0000-0000-000000000012'
        THEN '60000000-0000-0000-0000-000000000010'::uuid
        ELSE release.supersedes_release_id END,
    updated_at = '2026-09-01T00:00:00Z',
    version = release.version + 1
FROM showcase_release_contract contract,ops.source_definition source,ops.artifact_record artifact
WHERE release.id=contract.release_id
  AND source.id=release.source_definition_id
  AND artifact.id=release.artifact_record_id;

UPDATE ops.publication_receipt receipt
SET schema_version=contract.product_schema_version,
    rows_received=contract.record_count,
    rows_accepted=contract.record_count,
    rows_rejected=0,
    error_json=NULL
FROM showcase_release_contract contract
WHERE receipt.dataset_release_id=contract.release_id;

CREATE TEMP TABLE showcase_run_contract ON COMMIT DROP AS
SELECT release.ingestion_run_id,release.dataset_id,contract.*
FROM ops.dataset_release release
JOIN showcase_release_contract contract ON contract.release_id=release.id;

UPDATE ops.ingestion_run run
SET profile_key = CASE contract.release_id
        WHEN '60000000-0000-0000-0000-000000000001' THEN 'gnaf-nsw-address-registry'
        WHEN '60000000-0000-0000-0000-000000000002' THEN 'nsw-psi-sales-year'
        WHEN '60000000-0000-0000-0000-000000000003' THEN 'bocsar-crime-quarterly'
        WHEN '60000000-0000-0000-0000-000000000004' THEN 'nsw-government-schools-master'
        ELSE 'fixture-property-full' END,
    release_builder_version=contract.builder_version,
    requested_scope_json=jsonb_build_object(
        'profile','synthetic-showcase','all_records',true,'record_count',contract.record_count
    ),
    source_snapshot_json=jsonb_build_object(
        'source_release',contract.source_release,'synthetic',true,'record_count',contract.record_count
    ),
    parent_run_id=CASE WHEN run.id='30000000-0000-0000-0000-000000000012'
        THEN '30000000-0000-0000-0000-000000000011'::uuid ELSE run.parent_run_id END,
    status=CASE WHEN contract.release_id IN (
        '60000000-0000-0000-0000-000000000001',
        '60000000-0000-0000-0000-000000000002',
        '60000000-0000-0000-0000-000000000003',
        '60000000-0000-0000-0000-000000000004',
        '60000000-0000-0000-0000-000000000010',
        '60000000-0000-0000-0000-000000000012'
    ) THEN 'succeeded' ELSE run.status END,
    rows_discovered=contract.record_count,
    rows_staged=contract.record_count,
    rows_accepted=CASE WHEN contract.release_id='60000000-0000-0000-0000-000000000011'
        THEN 0 ELSE contract.record_count END,
    rows_rejected=0,
    error_json=CASE WHEN contract.release_id IN (
        '60000000-0000-0000-0000-000000000001',
        '60000000-0000-0000-0000-000000000002',
        '60000000-0000-0000-0000-000000000003',
        '60000000-0000-0000-0000-000000000004',
        '60000000-0000-0000-0000-000000000010',
        '60000000-0000-0000-0000-000000000012'
    ) THEN NULL ELSE run.error_json END
FROM showcase_run_contract contract
WHERE run.id=contract.ingestion_run_id;

UPDATE ops.run_task task
SET status='succeeded',
    finished_at=COALESCE(task.finished_at,task.updated_at),
    rows_out=contract.record_count,
    error_json=NULL,
    lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
    updated_at='2026-09-01T00:00:00Z',version=task.version+1
FROM showcase_run_contract contract
WHERE task.ingestion_run_id=contract.ingestion_run_id
  AND contract.release_id IN (
      '60000000-0000-0000-0000-000000000001',
      '60000000-0000-0000-0000-000000000002',
      '60000000-0000-0000-0000-000000000003',
      '60000000-0000-0000-0000-000000000004',
      '60000000-0000-0000-0000-000000000010',
      '60000000-0000-0000-0000-000000000012'
  );

UPDATE ops.import_operation operation
SET status='succeeded',rows_in=contract.record_count,rows_staged=contract.record_count,
    rows_accepted=contract.record_count,rows_rejected=0,
    result_json=jsonb_build_object('generation','synthetic-showcase','record_count',contract.record_count),
    error_json=NULL
FROM showcase_run_contract contract
WHERE operation.ingestion_run_id=contract.ingestion_run_id
  AND contract.release_id<>'60000000-0000-0000-0000-000000000011';

WITH ranked AS (
    SELECT quality.id,quality.ingestion_run_id,contract.dataset_id,
           contract.product_schema_version,contract.record_count,
           row_number() OVER (PARTITION BY quality.ingestion_run_id ORDER BY quality.id) AS sequence
    FROM ops.quality_result quality
    JOIN showcase_run_contract contract ON contract.ingestion_run_id=quality.ingestion_run_id
)
UPDATE ops.quality_result quality
SET rule_key='showcase.' || ranked.dataset_id || CASE ranked.sequence
        WHEN 1 THEN '.schema-contract' ELSE '.candidate-completeness' END,
    rule_version='1.0.0',
    dimension=CASE ranked.sequence WHEN 1 THEN 'schema' ELSE 'completeness' END,
    severity='blocking',
    status=CASE WHEN ranked.ingestion_run_id='30000000-0000-0000-0000-000000000011'
        AND ranked.sequence=2 THEN 'fail' ELSE 'pass' END,
    observed_value_json=CASE ranked.sequence
        WHEN 1 THEN jsonb_build_object('product_schema_version',ranked.product_schema_version)
        WHEN 2 THEN jsonb_build_object(
            'record_count',ranked.record_count,
            'run_completed',ranked.ingestion_run_id<>'30000000-0000-0000-0000-000000000011'
        ) END,
    expected_value_json=CASE ranked.sequence
        WHEN 1 THEN jsonb_build_object('product_schema_version',ranked.product_schema_version)
        WHEN 2 THEN jsonb_build_object('record_count',ranked.record_count,'run_completed',true) END,
    message=CASE WHEN ranked.ingestion_run_id='30000000-0000-0000-0000-000000000011'
        AND ranked.sequence=2
        THEN 'Historical synthetic candidate did not complete and was not published.'
        WHEN ranked.sequence=1 THEN 'Showcase records match the registered product contract.'
        ELSE 'Showcase candidate count matches its explicit synthetic source scope.' END,
    sample_json=NULL
FROM ranked
WHERE quality.id=ranked.id;

UPDATE ops.source_definition source
SET notes=CASE WHEN source.id='10000000-0000-0000-0000-000000000010'
        THEN 'Complete three-record synthetic fixture for demonstrations and offline testing.'
        ELSE 'Registered publisher source. The preloaded local baseline is an explicit synthetic sample; run the source job to acquire publisher data.' END,
    updated_at='2026-09-01T00:00:00Z',version=source.version+1
WHERE source.id IN (
    '10000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000010'
);
