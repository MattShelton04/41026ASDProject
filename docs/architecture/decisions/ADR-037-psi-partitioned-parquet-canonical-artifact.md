# ADR-037: Use partition-aware typed Parquet for canonical PSI handoff

- Status: Accepted
- Date: 2 September 2026
- Owner: PropertyScope Feature 1
- Preserves: ADR-030 release-export semantics, ADR-032 typed database materialisation and ADR-035
  bounded PSI archive-year acquisition

## Context

A complete NSW Property Sales Information (PSI) run contains more than seven million sale records.
The previous canonical handoff expanded those records into multi-gigabyte newline-delimited JSON,
then made the database loader parse and validate that text before the existing PostgreSQL COPY,
identity/revision, address-resolution and candidate-materialisation phases. This duplicated CPU,
filesystem I/O and retained storage without changing the governed database result.

PSI archives are explicit annual and weekly publisher partitions. The same sale may be retransmitted
in multiple archives, so archive order, partition evidence, business keys and the established row
hash must remain stable. The optimisation must not turn a Parquet file into a serving database or
bypass the candidate/review/publication lifecycle.

## Decision

- Official registered PSI ZIP archives remain the source and provenance boundary. Raw publisher
  archives and their checksums are unchanged.
- New PSI canonical artifacts use `propertyscope.canonical-psi-parquet.v1` and
  `application/vnd.apache.parquet`.
- The runner writes source archives in registered partition order. A partition boundary starts a
  new bounded row group; larger partitions are additionally split at 65,536 rows. Zstandard
  compression, dictionary encoding and fixed-size binary SHA-256 values reduce the handoff size.
- The Arrow schema uses typed dates, timestamps and integers. Publisher decimal values that feed
  PostgreSQL `NUMERIC` remain exact validated strings, avoiding an artificial fixed precision or
  scale. Known unusable derived address integers remain nullable with the existing bounded quality
  warning.
- `source_partition_year` remains explicit evidence. The established `source_row_sha256` continues
  to exclude partition year and source revision, so exact retransmissions retain the same identity
  and collapse/revision semantics as legacy NDJSON.
- Before COPY, the loader verifies the complete artifact byte count and SHA-256, then verifies the
  exact Arrow schema, embedded profile/version/partition/hash metadata and row semantics in bounded
  batches. It continues accepting registered legacy JSON/NDJSON artifacts.
- PostgreSQL remains authoritative. Typed temporary staging, deterministic identity/revision
  derivation, address resolution, candidate isolation, quality checks, review and accepted-pointer
  activation are unchanged. Complete consumer releases remain gzip NDJSON.

## Consequences

New PSI runs avoid generating and reparsing the multi-gigabyte canonical JSON representation while
retaining the same database rows and provenance hashes. Partition ordering is directly testable in
the artifact, and bounded row groups prevent whole-history materialisation in application memory.

The database still performs source-scale COPY, deduplication, address resolution, index and WAL
work. Parquet therefore improves the runner-to-loader handoff but does not establish a guaranteed
end-to-end duration. An official complete-source run must record phase timings and artifact size.
Runner and loader should be deployed together; rollback may resume NDJSON generation while the v1
reader remains available for already registered Parquet operations.

This format is not applied indiscriminately. BOCSAR and PSI have measured multi-million-row text
handoffs and benefit now. Schools and ABS SEIFA are small and remain simpler as JSON. G-NAF is a
plausible future candidate, but its transport, geocode selection and full-scale database costs need
a separate benchmark and contract decision before changing its canonical format.

## Rejected alternatives

- **Use Parquet instead of PostgreSQL:** rejected because it bypasses governed materialisation,
  release review, concurrent query and accepted-generation contracts.
- **Partition the database by publisher archive:** rejected because archive partitions are source
  packaging, not stable sale-date or property-query boundaries, and retransmissions cross them.
- **Include archive year in the row hash:** rejected because it would turn exact retransmissions
  into artificial revisions and change accepted history.
- **Convert every source job to Parquet:** rejected because format complexity is not justified for
  small sources and G-NAF needs independent evidence.
