# ADR-039: Validate warehouse provenance once per import batch

- Status: Accepted
- Date: 5 September 2026
- Owner: PropertyScope Feature 1

## Context

The full G-NAF ingestion on Improvements 55 took 30m05s in database import and 3m34s
in release construction. A subsequent 10.1-million-row BOCSAR load spent more than
30 minutes in its observation INSERT before the operator authorised cancellation.
The operational metadata tables received millions of repeated foreign-key probes.
The ingestion-run record also changes throughout the load as heartbeats arrive.
Earlier simplified SQL benchmarks omitted these metadata foreign keys and did not
represent this cost. The operator explicitly prioritised load speed over exhaustive
per-row metadata enforcement.

## Decision

- Register a `(dataset_release_id, artifact_record_id, ingestion_run_id)` tuple in
  `warehouse.import_batch` once before COPY. Its three foreign keys validate and
  retain the referenced records. Registration and warehouse writes share one
  transaction; failure rolls both back. A replay reuses its existing batch.
- Migration 050 backfills every distinct tuple from all seven warehouse fact tables
  before removing their three row-level operational metadata foreign keys. Existing
  row columns, source hashes and portable contracts remain unchanged. Historical
  generations can retain multiple provenance tuples without rewriting their facts.
- The database service owns enforcement that warehouse writes use their registered
  batch. Direct administrative SQL can bypass that relationship; this is an explicit
  tradeoff. Do not disable PostgreSQL triggers globally or bypass property identity
  foreign keys. Application import APIs remain the supported write path.
- Batch records retain provenance even after a rejected generation's facts are
  removed. Any future permanent lineage purge must remove facts before its batch
  records. Existing metadata deletion stays restrictive.
- BOCSAR uses one `DISTINCT ON` ordered selection for each fact type. Natural-key
  ordering feeds the primary key in order; ordinal breaks ties to retain the first
  source row. This replaces the grouped-ordinal relation and join back to the full
  staging table. Conflict handling still supports replay.
- Complete artifact verification, typed COPY, natural keys, property references,
  row-count quality checks, cancellation and atomic accepted-pointer activation
  remain. Publication is still a separate operator decision.

## Validation and consequences

Fully migrated PostgreSQL tests cover migration backfill, retained property foreign
keys, invalid provenance rejection before consuming rows, and rollback of both facts
and batch registration. Existing BOCSAR regressions cover duplicate precedence,
exact month coverage and replay. Import measurements must include the full schema
and metadata updates; reduced benchmark tables may compare SQL shapes only.

The new header has one row per provenance tuple rather than one trigger event per
fact/reference. Migration scans existing warehouse tables once, but does not rewrite
their large heaps or rebuild search indexes. Coordinate worker refresh after migration
before accepting another ingestion, as old loaders do not register batches.
