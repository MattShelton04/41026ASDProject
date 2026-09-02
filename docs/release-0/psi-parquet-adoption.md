# PSI partition-aware Parquet adoption prompt and implementation plan

## Reusable implementation prompt

Implement a production-safe optimisation for PropertyScope Feature 1's NSW Property Sales
Information acquisition/import path. Replace newly generated canonical PSI NDJSON with a
versioned, typed, compressed Parquet artifact while preserving publisher-partition order,
retransmission identity and the existing governed PostgreSQL result.

Requirements:

- Continue acquiring only the registered official PSI annual and weekly ZIP archives. Preserve raw
  source provenance and checksums; do not use developer caches as production inputs.
- Register new artifacts as `application/vnd.apache.parquet` with schema version
  `propertyscope.canonical-psi-parquet.v1`. Embed and verify profile, version, partition-order,
  retransmission and hash-encoding metadata.
- Use an explicit Arrow schema, source-ordered partition row groups bounded to 65,536 rows,
  Zstandard compression, dictionary encoding for repeated text and 32-byte binary SHA-256 values.
  Use typed dates/timestamps/integers without losing exact publisher decimal text.
- Preserve every canonical field and the legacy `source_row_sha256` exactly. The hash must continue
  excluding `source_revision` and `source_partition_year`, so an exact sale retransmitted in a
  later archive has the same hash and database revision behavior.
- Preserve the existing non-blocking quality treatment for out-of-range derived address numbers.
- Write through the managed seekable content-addressed artifact operation. Failed writes must clean
  up their temporary files; identical content must retain deterministic bytes and hashes.
- Verify artifact size and SHA-256 completely before database COPY. Reject an unregistered Arrow
  schema or metadata, empty/corrupt artifacts and invalid field ranges, dates, postcodes, decimals,
  UUIDs, hashes, partition years or quality warnings.
- Keep JSON/NDJSON loading for historical artifacts and cached reprocessing. Do not change raw ZIP
  retention, complete gzip-NDJSON release exports, consumer contracts, quality gates, candidate
  isolation, publication review or accepted-generation activation.
- Keep PostgreSQL as the authoritative serving store. Parquet optimises only the canonical handoff;
  the existing typed staging, identity/revision derivation, exact-address resolution, target
  materialisation, indexes and WAL remain.
- Add semantic-equivalence, retransmission, partition-order, row-group, determinism, compression,
  invalid-input, loader-routing and legacy-compatibility tests. Run the canonical repository gate
  and measure a real complete-source run separately before claiming an end-to-end duration.

## Implemented plan

1. Merge the accepted ABS SEIFA 2021 work into `Matt/Boscar_Optimisations`, preserving its source,
   import and consumer behavior.
2. Add a dedicated v1 PSI Arrow schema and deterministic partition-aware writer using the PyArrow
   dependency already introduced for the BOCSAR optimisation.
3. Route new `psi-sales` acquisition artifacts through the managed seekable artifact writer while
   retaining the legacy NDJSON helper for compatibility evidence.
4. Add strict profile dispatch and PSI schema/metadata/row validation to the database loader after
   full-file content verification.
5. Feed validated rows into the unchanged PostgreSQL stream-import profile, including its typed
   stage, retransmission/revision policy, address resolution, candidate generation and checks.
6. Prove field/hash equivalence with the legacy validator, stable cross-partition retransmission
   hashes, bounded partition row groups, deterministic compression and rejection of invalid files.
7. Update architecture and operator documentation, run targeted and repository-wide checks, then
   push the existing branch and update its pull request.

## Rollout, measurement and rollback

Deploy the runner and loader together. Existing registered NDJSON artifacts remain readable, and
no warehouse migration or release rewrite is required. A rollback may restore NDJSON generation;
keep the v1 reader deployed until all registered Parquet import operations are terminal.

For the first official complete-history run, retain acquisition/canonicalisation duration,
canonical artifact bytes, verification duration, typed-staging rows/time, identity/revision time,
address-resolution time, target-materialisation time, final counts and release quality outcomes.
Compare those values with a like-for-like NDJSON run. Database work may still dominate even when
the canonical artifact becomes much smaller.
