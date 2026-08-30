# ADR-032: Use typed, phased source materialisation with loader-local limits

- Status: Accepted
- Date: 30 August 2026
- Owner: PropertyScope Feature 1

## Context

The first complete PSI and BOCSAR imports proved the release transaction and predecessor-safety
model, but their wide JSONB plans repeatedly extracted values, sorted multi-million-row wide
relations, spilled heavily, and left destination allocation after rollback. PSI also reached the
expensive materialisation before an out-of-range address number failed. Global database tuning,
disabled integrity checks, chunk commits and unlogged destination tables would weaken the existing
atomic release contract.

## Decision

- Canonical validation and range checks remain before database materialisation. PSI and BOCSAR are
  copied once into typed transaction-local temporary tables with `COPY ... FREEZE`, followed by
  `ANALYZE` before planner-sensitive work.
- PSI collapses exact retransmissions to the earliest ordinal in a narrow business-key/hash table,
  assigns revisions by first source appearance, resolves each distinct eligible eight-component
  address once with explicit zero/one/many ambiguity, and joins only the retained wide row into the
  destination. Supplied property references continue to win. There is no final wide ordering.
- BOCSAR inserts typed sparse observations and coverage separately without ordinal ordering.
  Missing-versus-zero and coverage fields remain distinct contract evidence.
- Destination inserts retain release-scoped uniqueness and `ON CONFLICT`; the complete candidate
  is still one transaction, and pointer activation remains a later reviewed transaction.
- An expression/covering property index matches the exact `COALESCE` predicates used by PSI.
- PostgreSQL temporary files are bounded with `SET LOCAL temp_file_limit` only on loader-owned
  connections. A conservative free-space check runs before COPY and includes configured temporary
  files, artifact-derived database/index growth and reserve allowances. Failures expose bounded
  resource evidence, preserve the predecessor, and retain the relation-scoped recovery obligation.
- Performance evidence uses disposable real-shape schemas at 100,000 records, then 1,000,000 only
  after three clean reset runs per variant. Each measured statement has a 30-minute ceiling and
  five-minute progress evidence. Full official artifacts are permitted only when the smaller-run
  budget predicts completion within that ceiling.

## Consequences

Typed staging removes repeated JSON conversion and narrows the operations that can spill. Explicit
phases make cancellation and timings attributable without exposing partial candidates. Temporary
tables disappear at transaction end. After a failed/cancelled outcome is durable, the loader
measures the profile's exact allowlisted destination relations, runs bounded non-rewriting
`VACUUM (ANALYZE, INDEX_CLEANUP ON)`, measures again and records completion. A timeout leaves the
operation `needed`; no `VACUUM FULL`, table rewrite or unrelated relation is permitted. The
conservative disk check measures the loader artifact mount as a proxy for the single-host Docker
disk pool and therefore remains an operator-tunable safety bound, not a prediction of exact
PostgreSQL growth on independently provisioned storage.

The benchmark harness is evidence tooling, not a production data generator. Its synthetic rows
preserve relevant shapes and duplicate/address cardinalities but do not establish official-source
semantic completeness; that remains covered by canonical fixtures and permitted pinned-source
validation.

## Rejected alternatives

- **Chunk commits or early pointer movement:** rejected because partial candidates could become
  visible and crash replay would no longer be atomic.
- **Global `work_mem` or temporary-file changes:** rejected because one loader must not destabilise
  unrelated database sessions.
- **Remove conflicts or integrity constraints:** rejected because the existing crash-window replay
  and provenance guarantees depend on them.
- **Run full official datasets first:** rejected because smaller reset runs must establish a bounded
  budget before consuming retained storage and operator time.
