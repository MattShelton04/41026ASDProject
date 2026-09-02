# BOCSAR sparse Parquet adoption prompt and implementation plan

## Reusable implementation prompt

Implement a production-safe optimisation for PropertyScope Feature 1's BOCSAR acquisition/import
path. Replace newly generated canonical BOCSAR NDJSON with a versioned, typed, compressed Parquet
artifact, while preserving the existing sparse observation and explicit coverage semantics exactly.

Requirements:

- Continue acquiring the official registered BOCSAR postcode and suburb ZIP archives. Do not read
  `C:\git\prototype\property\prototype\data\cache\bocsar_long.parquet` or any other developer
  cache at runtime. That file is dense, stale, suburb-only and lacks registered provenance.
- Emit only positive observations plus one coverage record per source geography/category row. A
  missing observation means zero only when the matching coverage record says blanks are observed
  zero; never infer source coverage from Parquet row absence alone.
- Register new artifacts as `application/vnd.apache.parquet` with schema version
  `propertyscope.canonical-bocsar-parquet.v1`. Embed and verify the profile, schema version,
  coverage-semantics and SHA-256 encoding metadata.
- Use an explicit Arrow schema, bounded batches/row groups, Zstandard compression, dictionary
  encoding for repeated text and 32-byte binary SHA-256 columns. Preserve the legacy canonical
  `source_row_sha256` and `completeness_sha256` values exactly.
- Add a seekable-artifact writer to the content-addressed store. It must write to a managed
  temporary file, flush, hash, atomically finalise, reuse identical content and clean up after
  failure.
- Verify artifact size and SHA-256 completely before database COPY. Reject an unregistered schema,
  incorrect metadata, invalid record-kind fields, invalid postcodes/counts/dates, unsorted coverage
  months, mismatched coverage bounds/count/checksum, empty artifacts and corrupt Parquet.
- Keep JSON and NDJSON loading for old registered artifacts and cached reprocessing. Do not change
  release-export media types, consumer contracts, quality gates, candidate isolation, publication
  review or accepted-generation activation.
- Keep PostgreSQL as the governed serving store. Parquet optimises the canonical handoff; it does
  not bypass the serial loader, transaction boundary, provenance ledger or human review.
- Add semantic-equivalence, determinism, compression, provenance, corrupt-input, atomic-cleanup,
  loader-routing and legacy-compatibility tests. Run the repository quality gate and record a real
  full-source timing separately before making an end-to-end performance claim.

## Implemented plan

1. Isolate the work on `Matt/Boscar_Optimisations` from `origin/main`, leaving concurrent SEIFA work
   untouched.
2. Add PyArrow to the Student 1 runtime through the workspace dependency workflow.
3. Add the v1 sparse BOCSAR writer and a managed seekable artifact-store operation.
4. Route new BOCSAR acquisition artifacts to Parquet, retaining legacy NDJSON generation helpers for
   focused compatibility tests and old-artifact loading in the database service.
5. Add loader-side schema/metadata/semantic validation and full checksum verification before COPY.
6. Prove row and hash equivalence against the legacy validator, deterministic output, meaningful
   compression, failure cleanup and no database COPY after checksum failure.
7. Run targeted tests, Student 1 regression tests and `uv run python scripts/check.py`.
8. Push the requested branch and open a pull request with the migration, rollback and measurement
   caveats called out.

## Rollout and rollback

No migration rewrites existing warehouse rows or artifacts. Deploy the runner and loader together:
the runner begins registering Parquet for new BOCSAR acquisition stages, while the loader accepts
both the new media type and existing JSON/NDJSON. A rollback can restore NDJSON production without
making existing releases unreadable; any already registered Parquet operation should be completed
by a loader version that contains the v1 reader.

The next official-source run should record acquisition/canonicalisation time, artifact bytes,
artifact verification time, typed-staging time, target-materialisation time and final row counts.
The optimisation is accepted only if canonical row/hash equivalence and all release quality checks
hold. Database materialisation can still dominate because the same governed PostgreSQL rows,
indexes and WAL are retained.
