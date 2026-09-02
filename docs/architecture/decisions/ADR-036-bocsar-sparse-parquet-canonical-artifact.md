# ADR-036: Use sparse typed Parquet for canonical BOCSAR handoff

- Status: Accepted
- Date: 2 September 2026
- Owner: PropertyScope Feature 1
- Preserves: ADR-030 release-export semantics and ADR-032 typed database materialisation

## Context

The complete BOCSAR acquisition currently expands sparse official wide CSV facts into more than ten
million newline-delimited JSON records. One observed run retained a roughly 4.17 GB canonical
artifact for 10,114,565 accepted rows. The runner serialises every record as JSON and the loader
reads, parses, normalises and hashes it again before PostgreSQL COPY. This durable intermediate
format adds substantial CPU, filesystem I/O and retained storage before the already measured typed
database materialisation phases.

A separate prototype cache demonstrates that Parquet compresses this data shape well, but it is not
a valid production source. It is a dense suburb-only matrix through December 2025, includes about
97.9 million zero rows, does not include postcode records and is not registered against the current
official source checksum.

## Decision

- Official BOCSAR ZIP archives remain the source of truth and the registered transport/provenance
  boundary. Developer caches are never runtime inputs.
- New BOCSAR canonical artifacts use `propertyscope.canonical-bocsar-parquet.v1` and
  `application/vnd.apache.parquet`. Other canonical profiles and complete release exports retain
  their existing containers.
- The artifact contains only positive observations and explicit coverage rows. It uses an exact
  typed Arrow schema, bounded 65,536-row groups, Zstandard compression, dictionary encoding for
  repeated text and fixed-size binary hashes.
- The writer preserves the existing canonical normalisation and row/completeness SHA-256 values, so
  warehouse provenance and replay comparison remain stable.
- The content-addressed artifact owner supports seekable writers through a managed temporary file,
  hash verification and atomic finalisation. The loader verifies the complete artifact checksum
  before COPY, then verifies the registered schema, metadata and record-kind semantics while
  streaming bounded row batches.
- The loader continues accepting old canonical JSON/NDJSON. Deployment is forward-compatible when
  the runner and loader are released together and rollback may resume NDJSON production.
- PostgreSQL remains the only governed serving store. Candidate isolation, one-transaction
  materialisation, quality evidence, review and accepted-pointer activation do not change.

## Consequences

The runner no longer emits or retains multi-gigabyte textual BOCSAR canonical artifacts, and the
loader avoids UTF-8 JSON parsing and a second canonical row-hash pass. The artifact can be inspected
by standard Parquet tools without confusing dense zero rows with source facts. Semantic-equivalence
tests compare every typed field and provenance hash with the legacy validator.

PyArrow becomes a Student 1 runtime dependency and adds image size. Parquet needs a seekable file,
so checksum verification is a complete bounded scan before COPY rather than verification during the
same sequential NDJSON read. Database COPY, destination rows, indexes, WAL and set-based duplicate
protection remain; therefore this decision does not claim that every full import will finish within
a particular time. Official end-to-end phase timings remain required evidence.

## Rejected alternatives

- **Read the prototype cache directly:** rejected because it is stale, dense, incomplete and outside
  the registered source/provenance boundary.
- **Treat absent Parquet observations as zero without coverage:** rejected because absence could mean
  uncovered, filtered or malformed source data.
- **Use Parquet as the serving database:** rejected because it would bypass the existing release,
  query, quality, concurrency and human-review contracts.
- **Remove JSON/NDJSON loading immediately:** rejected because immutable historical artifacts and
  cached reprocessing must remain replayable.
