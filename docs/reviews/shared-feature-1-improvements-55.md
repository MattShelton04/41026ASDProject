# Shared and Feature 1 review — Improvements 55

Review date: 5 September 2026. Baseline: `f805178`.
Scope: Shared contracts, consumer transport, browser shell and AI services; Feature 1
frontend, HTTP boundaries, property discovery, ingestion and publication setup.
Other students' implementations are outside this change's ownership.

## Implementation plan

1. **HTTP failure correctness.** Stop the Feature 1 response adapter turning unreadable
   upstream bodies into successful JSON. Preserve valid Problem Details, correlation and
   legitimate no-content responses. Test malformed successes and failures without a network.
2. **Browser resource ownership.** Dispose table observers at Shared route replacement and
   Feature 1 search, run refresh and release-preview replacement. Close menu listeners when
   their table is disposed. Verify repeated operations return resources to baseline.
3. **Responsive search.** Cancel obsolete searches as the query changes, allow the corrected
   query immediately, and prevent old completion/pagination from changing the new result or
   its loading state. Keep mutation submission guards unchanged.
4. **Shell consistency.** Correct stale home availability copy and make repeated home-route
   binding idempotent. Verify navigation and normal-origin rendering in Shared/Feature 1.
5. **Complete list navigation.** Apply job, text and lifecycle filters before pagination;
   expose bookmarkable pages rather than silently limiting operators to the first 100 items.
6. **Import and export profiling.** Inspect retained G-NAF/PSI/BOCSAR history, compare the
   prototype's approach, measure database alternatives in disposable PostgreSQL and benchmark
   compatible export pipelines. Keep only optimizations supported by those measurements.
7. **Verification and handoff.** Run the locked canonical gate, focused failure regressions,
   normal-origin form suite and Shared/Feature 1 audits. Retain a concrete review record,
   remaining concerns and validation limits. Commit coherent stages, push the requested
   branch and open a PR.

## Initial findings

| Priority | Finding | Effect |
|---|---|---|
| P1 | `http_support.forward` substitutes `{status: 200}` when upstream JSON cannot be decoded | A broken dependency can look like a successful empty collection or saved operation. |
| P2 | Shared routing does not dispose its table regions; Feature 1 disposes at hash navigation but misses inner replacements and polling | ResizeObservers retain removed tables during prolonged use. |
| P2 | Feature 1 action menus attach document/window listeners without a disposal hook | An open menu removed during navigation or refresh retains its DOM and listeners. |
| P2 | Property search uses the mutation-style single-submission guard | Editing a pending query invalidates its result but still blocks the replacement search until the old request finishes. |
| P2 | Release preview permits previous and next requests concurrently and replaces detached panels after completion | An older response can overwrite a newer page and create observers in a removed view. |
| P2 | Home listeners are rebound when a home anchor changes without replacing its DOM | Repeated navigation can attach multiple handlers to the same form. |
| P3 | Home copy says remaining research areas will appear despite five enabled cards | Availability guidance contradicts the manifest-driven directory. |
| P2 | Lists filter a single loaded page and expose no collection pager | Older matching jobs, updates and releases cannot be reached reliably. |
| P2 | History's Running filter compares against a status the run ledger does not store | Active acquisition, staging and build tasks disappear from that filter. |
| P2 | Release export serializes repeated JSON keys at the private HTTP hop and projects rows on one CPU | Large address and sales products spend avoidable time transferring and constructing records. |
| P2 | Export HTTP reads can outlast a task lease without a heartbeat | A healthy slow read can be mistaken for an interrupted worker. |
| P2 | Crime coverage checks scan the complete month tuple for each observation | Validation becomes quadratic in the number of months per series. |
| P2 | Parquet staging only reports its starting checkpoint | Long sales/crime COPY phases appear stuck at zero until materialisation begins. |
| P2 | The complete sales-source endpoint accepts v2 but rejects the current v3 contract | Current accepted sales products lose their source-record feed. |
| P2 | Shared feature brand/search targets are below 44px on mobile | The browser audit flags core controls that are difficult to tap. |

The existing design already has valuable safeguards: database ownership checks, strict generated
contracts, source streaming, bounded search candidates, durable cancellation, fenced import leases,
atomic accepted-generation activation and separate human publication approval. Improvements must
preserve these invariants; no new product rules or database technology are inferred by this review.

## Decisions and performance evidence

Retained history confirms the user's concern. The 31 August G-NAF run loaded 5,190,134 rows:
acquisition took approximately 4m28s, import 22m53s and build-release 8m43s. The 3 September
638,125-row partial PSI replay spent approximately 4m47s importing and 1m45s building. A previous
PSI task waited behind G-NAF's serial runner before acquisition could start. The retained BOCSAR
example is a seeded fixture, so its duration is not presented as a live measurement. These older
runs span importer changes and are not an A/B benchmark of this branch.

The prototype at `C:\git\prototype\property` also uses streaming COPY and typed source staging.
The current repository already implements those mechanisms, source caching, keyset export,
candidate-only loading and partial search indexes. Removing integrity or publication controls
was not justified by the measurements.

The implemented export path negotiates a compact private column layout, reads one page ahead,
keeps leases alive during waits, and uses two bounded projection processes for large flat
products. One parent-owned compressor preserves the existing portable artifact bytes. Crime
series keep serial projection and use a set for exact coverage membership. The processes do not
perform network, artifact, database or publication work. An empty/failed/cancelled build never
registers an export; partial artifact files are removed.

Three-run synthetic measurements on local Python 3.12 are recorded below. These cover private
page serialization, record validation/projection and gzip building, excluding database queries,
source acquisition and production network time. They are not promises about complete job time.

| Workload | Comparison | Median seconds | Result |
|---|---|---:|---|
| 100,000 addresses | Serial object pages vs compact/prefetched pages with two projection workers | 6.72 → 4.76 | About 29% faster; private payload 55.82MB → 25.22MB |
| 100,000 sales | Same comparison | 8.20 → 4.88 | About 40% faster; private payload 34.90MB → 15.40MB |
| 1,000 crime series, 312 months each | Serial object pages, tuple membership vs set membership | 3.73 → 2.76 | About 26% faster; same portable bytes |

Every compared pipeline produced an identical gzip checksum and byte count within the workload.
The [address](evidence/improvements55-export-addresses.json),
[sales](evidence/improvements55-export-sales.json),
[original crime](evidence/improvements55-export-crime.json) and
[linear-lookup crime](evidence/improvements55-export-crime-linear.json) records retain the samples.
`scripts/benchmark_feature1_exports.py` reproduces the three layouts without external services.
Its experimental parallel crime variant is retained for comparison, but is deliberately disabled
in the runner: after the membership fix, nested process transfer outweighed CPU savings.

A further three-run address benchmark used the actual runner image with its two-CPU/4GiB
budget and no network access. Median build time fell from 10.07s to 6.47s (about 36%), with
identical output bytes across the compared pipelines. The
[container samples](evidence/improvements55-export-addresses-docker.json) retain that check.

Additional experiments were rejected rather than installed as speculative tuning:

- Sorting G-NAF candidate inserts by key: three 1-million-row trials had median 40.84s without
  the sort and 43.14s with it. This used a fully migrated disposable PostGIS database.
- Increasing PostgreSQL work memory from 4MiB to 64MiB: existing PSI source-shape benchmarks
  passed the three-repetition 100k gate and then ran at 1m. Median measured phases were 13.30s
  and 13.66s respectively. Temporary blocks fell substantially, but overall time did not improve.
- G-NAF Parquet prototype: a synthetic 100k-row file shrank from 31.82MB NDJSON to 2.55MB,
  but reading and validating it was slower with the current row-oriented validator. Changing the
  default handoff solely for file size would not resolve the reported import latency.
- Replacing BOCSAR's three indexed export subqueries with one aggregate scan did not improve
  the measured page time; the existing SQL is retained.
- Lower gzip compression yielded only a small improvement in the initial address trial while
  enlarging the artifact, so compression and builder versions are unchanged.

Downstream delivery already uses immutable release callbacks, gzip-NDJSON streaming, bounded
staging, checksum/count/schema verification and atomic commit. Repeated provenance compresses
well. Keeping that portable contract avoids coordinating a format migration with other owners;
the private compact hop captures a benefit without changing their products. Feature 3's
consumer-owned HTTP batching is a possible separate tuning area and was inspected read-only.

## Validation record and remaining limits

The initial tree was clean, `uv sync --locked --all-packages --all-groups` succeeded, and the
baseline canonical gate passed. The implementation includes byte-equivalence, bounded scheduling,
cancellation, malformed-page, stale-search, observer/menu cleanup, filter and real PostgreSQL
regressions. Final `uv run python scripts/check.py` passed: lint/format, contract and
architecture validation, typing, 1,617 Python tests and 192 frontend tests. The gate skipped
31 opt-in tests. Separately, all 29 selected PostgreSQL integration tests passed against the
disposable server, and all 37 normal-origin form/browser tests passed.

The browser audit exposed the mobile target sizes and passed all six selected batches after the
fix (118 controls inventoried, 48 exercised). One non-blocking table-clipping warning and seven
informational contained-scroll findings remain. The quick audit is not a complete interaction
matrix. README screenshots are regenerated from the deterministic fixture application.

Live application/history inspection is read-only. Database writes and source-scale measurements
use a separately created disposable PostgreSQL server; browser mutation tests own an isolated
fixture host. Complete live G-NAF/PSI/BOCSAR jobs and downstream service imports have not been
rerun, so full-job speedups remain unverified. The runner still schedules acquisition tasks
serially and waits for loader completion; safely overlapping whole jobs requires a separate
durable scheduling change and resource-budget measurements. No checksums, source completeness,
identity matching, database ownership or human approval guarantees were weakened.

## Follow-up: full ingestion exposed per-row provenance overhead

The first complete post-change G-NAF run accepted 5,190,134 addresses in 38m31s:
4m52s cached-source preparation, 30m05s import and 3m34s release construction.
The build improved, but the total did not. The earlier estimate based on unchanged
import time was too optimistic. BOCSAR prepared 10,114,565 canonical rows, then spent
over 30 minutes in its observation INSERT. The operator authorised cancellation and
explicitly prioritised a faster import path over exhaustive per-row metadata checks.

Live counters exposed millions of repeated metadata scans and hundreds of millions
of entries read from the changing ingestion-run index. The earlier reduced SQL
benchmark tables omitted those foreign keys. They remain useful for comparing query
shapes, but do not substantiate full-schema ingestion performance.

Migration 050 and ADR-039 move the three constant metadata foreign keys from each
warehouse row to one `warehouse.import_batch` registration. Existing references are
backfilled first; facts, registration and quality updates retain one transaction.
The loader now owns the fact-to-batch relationship, so direct administrative SQL no
longer receives those three per-row checks. This explicitly supersedes the initial
pass's decision to retain all existing constraints. Property identity foreign keys,
artifact checksums, complete counts and atomic publication remain.

BOCSAR also uses an ordered `DISTINCT ON` selection to keep the first source row per
natural key without grouping then joining the wide stage again. Portable products
and downstream interfaces are unchanged. The follow-up PostgreSQL suite passes all
32 selected tests, including fully migrated provenance/backfill/rollback checks.

Three-run full-schema materialisation stress tests used a separate PostGIS container
limited to two CPUs/3GiB. A second connection updated the referenced run every 0.2s.
At 1m rows, median G-NAF INSERT time fell from 59.76s to 26.49s; BOCSAR from 54.33s
to 23.10s. The saved [EXPLAIN trigger evidence](evidence/improvements55-import-materialisation.json)
shows the removed per-row metadata checks. Each product used a freshly migrated
database, synthetic typed staging and rolled-back fact writes between repetitions;
allocated pages were reused, so these are stress measurements rather than pristine
end-to-end timing guarantees. Both products also passed three repetitions at 100k
before advancing to 1m. Acquisition, validation/COPY and commit are outside this
materialisation comparison. The metadata heartbeat is deliberately more frequent
than production. The live reruns are the source of complete-job timing evidence.

The final canonical gate passed after the follow-up: 1,617 Python tests and 192
frontend tests, with 34 opt-in tests skipped. The separate PostgreSQL run passed 32
tests. The idle database API, loader and runner were refreshed successfully after
migration. Complete G-NAF and BOCSAR were restarted through cached canonical replay;
complete PSI history was queued through the registered full-data job. These new
runs do not publish candidates or replace the accepted generations automatically.

## Live fast-import results and the full-history PSI follow-up

The replacement full canonical G-NAF replay accepted 5,190,134 addresses: import
5m56s, build 3m22s, execution 9m18s. Import alone fell about 80% from the measured
30m05s baseline. BOCSAR accepted 10,114,565 canonical observation/coverage rows:
import 13m29s, build 3m55s, execution 17m23s, plus 9m04s waiting behind G-NAF.
Its product contains 318,122 crime-series records. Both candidate releases passed
schema and candidate-row-count checks. Acquisition was skipped for these retained
canonical replays; these are not fresh network-download timings.

Complete PSI prepared 7,402,643 canonical records in 21m39s, but its import exposed
another source-scale query problem. The exact-address phase alone spent over
18 minutes in a pair of correlated aggregate lookups. Live cumulative index counters
showed about 720 million entries read through the broad G-NAF locality/postcode
index and no use of the exact-component index. The operator-authorised cancellation
preserved the prepared canonical artifact for another replay, avoiding repeated
source preparation. The cancelled attempt is not a successful import timing.

The typed PSI matcher now builds materialized address dictionaries and batch-joins
the distinct eligible addresses. Each source is grouped once; G-NAF precedence,
zero/one/many cardinality, directional street-type equivalents, supplied-reference
precedence and stale-anchor exclusion are preserved. A regression specifically
checks ambiguity when full and abbreviated spellings coexist. ADR-038 documents
the implementation change. The portable downstream product remains unchanged.

Three isolated, fully migrated PostgreSQL trials at each scale verified every
expected match. At 100k eligible addresses the old/new medians were 1.88s/2.59s;
at 1m they were 19.47s/35.59s. This deliberately simple single-locality fixture
uses the selective exact-component index successfully, so batch aggregation is
slower there. It establishes correctness and a bounded source-scale execution
sample, not a general speedup. The live dataset's repeated broad-index searches
are the reason for changing query shape; the retained full-history replay below
establishes completion at actual source scale. Temporary reference dictionaries trade extra
sequential grouping and spill space for removal of per-address search plans.

The final matching follow-up passed `uv run python scripts/check.py`: 1,617 Python
tests and 192 frontend tests, with 35 opt-in tests skipped. A separate disposable
PostgreSQL run passed all 33 import/identity/recovery tests, alongside 52 focused
unit tests. The idle loader was refreshed before the complete retained PSI replay.
The disposable benchmark server was removed after validation.

### Completed live replay timings (5 September 2026)

| Complete canonical scope | Imported rows | Import | Build | Execution | Queue wait |
| --- | ---: | ---: | ---: | ---: | ---: |
| NSW G-NAF | 5,190,134 | 5m56s | 3m22s | 9m18s | <1s |
| BOCSAR observations and coverage | 10,114,565 | 13m29s | 3m55s | 17m23s | 9m04s |
| PSI all history and current weekly | 7,402,643 | 26m11s | 7m19s | 33m30s | <1s |

Durations are independently rounded from persisted timestamps. These successful
runs all replay complete retained canonical artifacts and skip acquisition.
PSI's preceding full-refresh attempt prepared that same complete source in 21m39s;
adding preparation to the successful replay gives roughly 55m09s of measured
component work across two attempts, not one uninterrupted full-refresh timing.
There is no successful full-history PSI baseline supporting a percentage speedup.
The batch matcher did complete the previously cancelled resolution phase, and
the entire PSI candidate import and release build completed successfully.

The PSI product contains 7,402,643 records in 952,728,964 gzip-NDJSON bytes.
Property linkage reports 4,940,715 linked and 2,461,928 unmatched records.
Schema, complete candidate count and property-linkage blocking rules passed;
four out-of-range derived address numbers produced the existing source-anomaly
warning, with original records retained. BOCSAR exports 318,122 series rather
than one portable record per canonical observation/coverage row.

All three releases remain candidates; no publication or accepted-pointer change
was performed. The authorised 10-minute completion monitor is paused after the
final result. Complete downstream consumer ingestion remains untested by this run.
