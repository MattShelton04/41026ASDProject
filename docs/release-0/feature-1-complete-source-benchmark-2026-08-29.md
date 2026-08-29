# Feature 1 complete-source benchmark — 29 August 2026

This report records the local Docker verification of ADR-029 and ADR-030 on the retained official
G-NAF cache. It is operational evidence for this workstation, not a portable performance promise.
All times are wall-clock durations from durable task timestamps in PostgreSQL.

## Inputs and historical baseline

The before evidence was the cancelled G-NAF run retained in the development volume:

- 5,190,134 canonical records;
- 1,700,877,251-byte raw archive and 2,222,419,699-byte canonical NDJSON artifact;
- acquisition completed in approximately 4 minutes 37 seconds;
- import was cancelled before a generation committed;
- aborted global G-NAF index writes left approximately 1.088 GB allocated, including a 221 MB
  generation primary key even though only 10 rows remained committed.

The current run used the same content-addressed raw and canonical objects. No network fixture or
row subset was substituted.

## Complete run result

Run `f011ace4-7ca7-41d4-847e-4c0b1b069c83` completed successfully with candidate release
`50cf0c6c-879d-44ce-ac20-aa689415b29a`.

| Phase | Rows in | Rows out | Duration |
| --- | ---: | ---: | ---: |
| Discover | 0 | 0 | 0.036 s |
| Acquire and canonicalise | 5,190,134 | 5,190,134 | 4 min 2.025 s |
| Verify, COPY, insert and quality | 5,190,134 | 5,190,134 | 22 min 50.199 s |
| Build complete release | 5,190,134 | 5,190,134 | 9 min 38.631 s |
| Total active run |  |  | 36 min 30.915 s |

The acquisition phase was about 35 seconds (12.6%) faster than the retained 4 minute 37 second
baseline on identical cardinality. There is no valid before/after import-duration comparison because
the historical import did not complete.

The candidate contains exactly 5,190,134 warehouse rows and zero published rows. The previously
accepted pointer remained `60000000-0000-0000-0000-000000000001`; completing an ingestion did not
publish it.

## Optimised source-scale reprocess

Run `4c080d1e-7165-48bd-be60-0bc278b8ceae` reprocessed the same verified canonical artifact after
the source-scale import and release changes. It completed successfully with candidate release
`c8f70eb0-6307-45b9-b812-a15e64cc7be2`. The run retained exactly 5,190,134 discovered, staged and
accepted records, with zero rejected records.

| Phase | Original complete run | Optimised reprocess | Change |
| --- | ---: | ---: | ---: |
| Verify, COPY, insert and quality | 22 min 50.199 s | 19 min 51.933 s | 2 min 58.266 s faster (13.0%) |
| Build complete release | 9 min 38.631 s | 7 min 17.550 s | 2 min 21.081 s faster (24.4%) |
| Directly timed cached reprocess | not applicable | 27 min 9.898 s | acquisition was intentionally reused |
| Equivalent complete run | 36 min 30.915 s | 31 min 11.544 s | 5 min 19.371 s faster (14.6%) |

The equivalent complete-run figure combines the original run's unchanged 4 minute 2.025 second
acquisition and 0.036 second discovery with the directly measured optimised import and release
durations. It is therefore a controlled projection, not a second network acquisition measurement.

The import improvement comes from copying G-NAF into a typed temporary table instead of first
materialising every field as JSONB. Release construction uses larger bounded pages, relays those
private JSON pages without a parse/serialise round trip, and projects latitude/longitude directly
instead of constructing GeoJSON in PostgreSQL. The remaining 19 minute 52 second import still
performs a source-scale transaction, spatial transformation, final heap write and generation-key
index write. Partition attach/detach or a more invasive warehouse redesign remains future work,
not an unmeasured claim in this change.

Operator progress was checked during this run. Completed timeline steps show their duration;
active byte/row phases show elapsed time and a throughput-derived approximate remaining time.
The long set-based database insert is explicitly indeterminate because COPY completion cannot
measure that SQL operation. Cached discovery/acquisition steps read `not run (cached result reused)`
instead of implying a zero-duration execution.

## Release artifact evidence

The complete artifact is gzip NDJSON, not the bounded browser preview:

- compressed bytes: 515,790,493;
- SHA-256: `c96f8cba1718c84414402b36ba576bb763ac892d2d8869803ce57f4e4f2a7a4e`;
- decompressed NDJSON lines: 5,190,134;
- manifest record count: 5,190,134;
- product schema: `propertyscope.property-snapshot.v1`;
- builder: `property-snapshot` 2.0.0.

A separate streaming verification re-read the compressed artifact, recomputed the same SHA-256,
and counted every decompressed line without retaining the product in memory. During live snapshots,
the database loader used about 65 MiB while PostgreSQL performed the generation insert, and the
release runner used about 100 MiB during export. These are observations, not asserted peak values.

## Cancellation and transaction evidence

Controlled run `58ad1510-9fef-4a69-8cb2-5cb5348f9745` was cancelled during COPY after 64,318 rows
and 27,552,458 bytes:

- cancellation acknowledgement: 0.363 seconds;
- committed candidate rows: 0;
- accepted rows: 0;
- release status: `abandoned`, with a linked `ingestion_cancelled` terminal reason;
- durable last phase: `verifying and copying canonical stream`;
- G-NAF generation key after rollback: 16 KiB; all G-NAF indexes: 96 KiB.

This demonstrates that checksum verification and COPY share one byte stream, cancellation is
observed inside that pass, and the candidate transaction remains all-or-nothing.

## Storage and index result

Migration 032 replaced the six global G-NAF serving indexes with accepted-row partial indexes. A
targeted concurrent reindex reclaimed the confirmed aborted primary-key bloat:

| Measurement | Before remediation | After remediation | After complete candidate |
| --- | ---: | ---: | ---: |
| G-NAF generation primary key | 221 MB | 16 KiB | 321 MB |
| All G-NAF indexes | approximately 1.088 GB | 96 KiB | 321 MB |
| Feature 1 PostgreSQL database | 242 MB after partial-index migration | 21 MB | 1,912 MB |

After the complete candidate, the six serving indexes remain 8–16 KiB each; all 321 MB of candidate
index allocation is the deterministic `(dataset_release_id, gnaf_pid)` generation key. The 1,567 MB
warehouse heap and generation key are necessary candidate storage, while public search-index build
is deferred to reviewed activation.

Artifact lineage also reuses physical content correctly: 22 artifact ledger rows reference 15
physical storage keys. The identical G-NAF raw and canonical objects each have three run references
across cancelled and successful runs. A seven-day retention dry-run reported zero unreferenced
deletion candidates.

## Verification commands

The implementation passed the canonical `uv run python scripts/check.py` gate, including 384
shared/AI/script tests, 322 Feature 1 tests, 94 frontend tests, architecture validation, generated
contracts, mypy, Ruff and JavaScript syntax checks. Deterministic tests use finite local sources;
the source-scale live verification above used the cached official archive without a network-sized
test dependency.
