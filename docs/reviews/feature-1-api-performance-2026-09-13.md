# Feature 1 API performance investigation — 13 September 2026

## Scope and baseline

This review covers the Feature 1 public API, its private database/worker hops,
Property Discovery, and the HTTP integrations used by Features 2–5 and AI tools.
Measurements use the existing local Docker stack and accepted publisher data.
No datasets were acquired, approved, replaced or removed during the investigation.

The initial working tree was clean at `Matt/Feature_1_Api_Optimizations`.
PostgreSQL statistics estimated 15.56 million stored G-NAF rows (11 GB including
indexes), 9.15 million PSI rows and 9.78 million BOCSAR observations. These include
retained generations, not just the currently accepted release. Timings depend on
cache warmth and concurrent load and are local evidence, not production SLAs.

## API surface

Public paths below are relative to `/api/data-platform/v1`. The owning backend
relays persistence to `/internal/data-platform/v1` on the database API. Only the
database API and loader hold PostgreSQL credentials.

| Surface | Routes / operations | Bounds and consumers |
| --- | --- | --- |
| Discovery | GET `properties/search`, `properties/locality-summary` | Search: 25 default / 100 maximum returned, 500 candidate window. Summary: exact address counts, optional top 20 streets. Frontend, Feature 4 resolver, HTTP/MCP tools. |
| Property evidence | GET `properties/{ref}`, `/map-context`, `/coverage`, `/sale-history`, `/seifa`, `/report-section` | UUID identity; sale history 50 default / 100 maximum; report evidence up to 25 entries. Features 2/4 use identity, Feature 3 map context, Feature 5 report sections. |
| Operations | GET `overview`, `notifications`, `runtime-capabilities`, GET/POST `artifact-retention` | Small operational relations; retention POST is a separately guarded mutation. |
| Source registry | GET/POST `sources`; GET/PUT/DELETE `sources/{id}`; source HTML fragments | Lists 25 default / 100 maximum. CRUD ownership and optimistic concurrency stay in Feature 1. |
| Jobs | GET/POST `jobs`; GET/PUT/DELETE `jobs/{id}`; GET `/capabilities`; POST `/plans`, `/runs` | Registered acquisition scopes. Planning and execution are explicit user actions. |
| Runs | GET `ingestion-runs`, `/{id}`, `/{id}/tasks`, `/artifacts`, `/quality-results`, `/activity`, `/activity/download`; POST `/cancel`, `/resume`, `/retry`, `/reprocess-cached` | Paginated evidence, bounded activity log, durable worker leases and idempotent transitions. |
| Releases | GET/POST `dataset-releases`; GET/PUT/DELETE `/{id}`; GET `/manifest`, `/artifact`, `/records`; POST `/submit-review`, `/publish`, `/reject`, `/retry-delivery`; GET `/consumer-imports/{operation}` | Lists/previews bounded by page size. Immutable complete artifacts stream separately. Publication and consumer delivery remain durable operations. |
| Product discovery | GET `data-products`, `/{dataset}`, `/{dataset}/accepted`, `/{dataset}/source-records` | Registered catalogue; accepted release contracts for Features 2–5. PSI source feed: required year, 1,000 default / 5,000 maximum rows, release pinning. |
| AI orchestration | GET `assistant/capabilities`; POST `assistant/turns`; GET `assistant/turns/{id}`, `/events`; POST `/cancel`; POST `dataset-releases/{id}/agent-runs`; GET `agent-runs`, `/{id}`, `/events` | Asynchronous AI-mode runs; direct data operations do not require a model. |
| AI tools | POST `tools/{name}.v1`: sources.list, releases.list/inspect/compare/publish, platform.capabilities, runs.list/inspect/explain/retry, coverage.inspect, properties.search/inspect/locality-summary | Same owning HTTP handlers and accepted-data policy; mutations retain policy approval. |
| Private worker API | Consumer-import claim/step; task claim/heartbeat/complete/fail/cancel; run imports/finalize-release/build-context; release product-records | Registered work only. Exports keyset-page 20,000 address/sale rows or 500 crime series, with complete-artifact generation checks. |
| Private diagnostics | Health, schema counts/fingerprint, loader import/activation coordination | Internal authentication; diagnostic table counts are not a user search path. |

## Confirmed causes

1. Search bounds output too late. The Parramatta plan reads 42,804 address rows
   from a trigram bitmap before accepted-generation joins yield 501 candidates.
   It touches 15,816 cached plus 8,589 read blocks, then ranks only 500 documents.
   The SQL took 2,790 ms; the separate HTTP sample took 3,753 ms. Sutherland took
   1,698 ms SQL / 1,730 ms HTTP. Postcode 2000 took 372 ms HTTP.
2. Both browser and database reject a single distinctive alphabetic word shorter
   than eight characters. Glebe and Sydney return 422; Sydney NSW is also rejected.
3. A property page launches six HTTP requests. Identity, map context and report
   section each load a full snapshot, and coverage repeats independently. The
   sampled six-request flow took 224 ms warm, with avoidable query amplification.
4. A 25-row G-NAF, PSI or BOCSAR release preview returns 503 at the backend's
   five-second store timeout. Preview queries sort source-scale data for display
   and run an exact `count(*)` on every page. The HTTP timeout does not cancel SQL.
5. Release lists return full manifests: one 21-release page was 651,714 bytes.
   This is a payload amplification issue even where local SQL is fast.

Other initial samples: overview 13 ms, sources 10 ms, jobs 34 ms, run list 15 ms,
release list 80 ms, product catalogue 29 ms. Locality summary with top streets
took 4,024 ms initially; its separate warmed aggregate plan took 152 ms and read
27,617 actual locality records. Exact aggregate work must remain distinguishable
from bounded search sampling.

## Implemented changes

- Probe exact accepted locality names, then exact street names, before substring
  matching. Support short suburbs and an optional trailing NSW/postcode. Select
  G-NAF before the compatibility fixture and limit each accepted generation's
  lookup before ranking. Numeric/locality/street candidates use source-key order;
  final ranking has a property-reference tie-breaker. Search still returns at most
  100 rows per request from the fixed 500-candidate window, with honest lower bounds.
- Replace the postcode/street-number indexes with ordered versions; add ordered
  locality and street-name indexes. Keep legacy street lookups on the existing
  trigram index rather than scanning all registry anchors when a street has few hits.
- Bound each interactive property/preview request to 3.5 seconds across pool waits
  and statements. Use transaction-local PostgreSQL cancellation, a 500 ms lock
  timeout and disabled JIT for these small pages. Return correlated
  `503/read_budget_exceeded`; reset settings before pool reuse. Loader, publication,
  and complete export work keep their own budgets.
- Preview in indexed source-key order and fetch `limit + 1` rows. Remove per-page
  counts over source-scale tables. Add `total_is_lower_bound`; the UI says “at least”.
  An empty out-of-range page never invents a total from its offset. BOCSAR preview
  counts remain observations, distinct from the release's exported-series count.
- Add a `(release, source year, business key, revision)` PSI index. The consumer feed
  retains its exact total, original fields and complete yearly pagination.
- Add `view=summary` to release lists and use it on overview/list pages. Full
  metadata remains the default for existing consumers and release-detail workflows.
- Reuse the property snapshot for map, coverage and report evidence. Load sales
  and SEIFA once on first tab selection, including deep links. Preserve loaded
  evidence, cancellation guards and Back to search. Serve Feature 3's map-context
  with one indexed point query; preserve Feature 5's report-section contract.

## Measured result

The [machine-readable summary](feature-1-api-performance-2026-09-13.json) retains
all 48 API cases, SQL footprints, browser flows and consumer measurements.
The baseline HTTP column is one initial sample, including cold reads; after columns
are the median and nearest-rank p95 of 20 sequential samples with caches retained.
These are deliberately labelled differently: cache warming contributes to the time
difference. Query plans independently establish the reduction in work.

| Flow | Before HTTP | After median | After p95 |
| --- | ---: | ---: | ---: |
| Parramatta search | 3,753 ms | 30 ms | 46 ms |
| Sutherland search | 1,730 ms | 29 ms | 47 ms |
| Postcode 2000 | 372 ms | 28 ms | 43 ms |
| Glebe | 422 rejected | 40 ms | 63 ms |
| Sydney | 422 rejected | 27 ms | 48 ms |
| Sydney NSW 2000 | Broad substring path | 146 ms | 307 ms |
| George street name | Rejected by old validation | 38 ms | 55 ms |
| North street name | Rejected by old validation | 39 ms | 65 ms |
| G-NAF preview, 25 rows | 503 after 5,010 ms | 30 ms | 34 ms |
| PSI preview, 25 rows | 503 after 5,023 ms | 19 ms | 34 ms |
| BOCSAR preview, 25 rows | 503 after 5,026 ms | 21 ms | 32 ms |
| PSI source year, 25 rows | 3,662 ms, before year index | 70 ms | 93 ms |
| Locality summary + top streets | 4,024 ms | 87 ms | 151 ms |
| Property map-context (same UUID) | 152 ms | 41 ms | 60 ms |

All **960/960 requests succeeded and completed within 500 ms**, including first
and second preview pages, accepted contracts, operational lists and read-only AI
tools. Four concurrent search users also succeeded on **80/80** requests: median
38 ms, p95 91 ms, maximum 234 ms. These results establish the tested local cases,
not an unbounded concurrency or production-capacity guarantee.

| Query footprint | Before | After |
| --- | ---: | ---: |
| Parramatta address rows visited | 42,804 | 501 |
| Parramatta shared buffer accesses | 24,405 | 485 |
| Parramatta SQL execution | 2,790 ms | 25 ms |
| Sutherland address rows visited | 12,180 | 501 |
| Sutherland shared buffer accesses | 9,044 | 519 |
| Sutherland SQL execution | 1,698 ms | 27 ms |
| Postcode address rows visited | 1,002 | 501 |
| Preview page rows fetched | Full sort/count plus 25 returned | 26 fetched, 25 returned |
| Initial property-page HTTP requests | 6 | 1 |
| Release list bytes, 21 entries | 651,714 full | 14,019 summary |

Buffer accesses count hits plus reads, not distinct pages. Optimized SQL figures
above are the main search statement; HTTP timings also include the indexed name
probe and both service hops. A rare no-match address query did not improve its
buffer footprint (625 to 1,155 accesses for `11 Example Street`), because both
accepted generations and compatibility data must be checked. Its measured SQL
still fell from 146 to 92 ms. Exact locality aggregates still visit all 27,617
Parramatta addresses; they are intentionally not estimated from search's sample.

The live browser measured seven searches at 53–340 ms until result cards were
visible. It verified 50 unique results across two pages, return navigation, one
initial property request (192 ms until identity/map were visible), one request per
first evidence-tab selection, no requests on revisiting those tabs, and a 53 ms
search through the shared `/features/data-platform/` entrypoint. External map
tiles were disabled for this test; there were no page errors. Browser figures
include DOM rendering and test synchronization and are separate from HTTP latency.

## Cross-feature validation

No other student's implementation was edited. The existing clients and public
routes exercise the same Feature 1 contracts:

| Consumer flow | Samples | Median | p95 | Result |
| --- | ---: | ---: | ---: | --- |
| Feature 2 own client: validate identity | 20 | 58 ms | 73 ms | All verified |
| Feature 3 public nearby-places route | 20 | 48 ms | 92 ms | All 200 |
| Feature 4 public property search (Glebe) | 20 | 68 ms | 135 ms | All 200 |
| Feature 4 public property validation | 20 | 69 ms | 92 ms | All 200 |
| Feature 5 own client: validate report section | 20 | 90 ms | 175 ms | All validated |

Feature 5 also collected evidence for the selected property through its existing
Feature 1/2/4 gateway in 223 ms. This was a read-only boundary test; it did not
create buyer cases or market cases. Complete artifact bytes, release pinning,
consumer receipt contracts and approval semantics are unchanged. Live AI provider
generation and complete publisher acquisitions/imports were not rerun.

## Reproduction, checks and tradeoffs

With the stack running and the same accepted data, run:

```text
uv run python scripts/benchmark_feature1_api.py --samples 20 --property-ref 0449066e-5949-da5e-dd2c-f6fac1c62304 --output .propertyscope-runtime/feature1-api.json
uv run pytest student-1/tests/e2e/test_form_behaviour_playwright.py --no-cov -q
uv run python scripts/check.py
```

Omit `--property-ref` to choose a result from your own accepted dataset. The script
only performs reads and documented read-only tool POSTs. It keeps every latency,
status, byte count and page count, prints p50/p95, and exits nonzero on failures.
Missing accepted products are not silently replaced by fixtures.

The required Chromium suite passed **48 tests**. The fresh PostgreSQL/PostGIS
suite passed **10 tests**, including migrations, accepted-generation replacement,
unpublished-row exclusion, deterministic search pages, postcode filtering,
SQL cancellation and pooled-connection recovery. Its server was disposable and
separate from the retained application database. The Feature 1 Node suite passed
**65 tests**. The final `uv run python scripts/check.py` completed successfully:
lint, formatting, architecture validation, typing across 259 source files,
**2,030 Python tests passed / 49 skipped**, all required coverage thresholds met,
and **221 JavaScript tests passed**. The gate skipped 41 PostgreSQL tests and eight
platform-dependent checks. The ten PostgreSQL identity/read tests ran separately;
the remaining 31 importer/space-recovery integration tests were not rerun. The
Chromium suite also ran separately.

The first full-gate attempt that reached Feature 3 encountered one loopback
`RemoteDisconnected` in its unchanged assistant integration test. The isolated
Feature 3 HTTP suite then passed all 25 tests, followed by the successful complete
gate rerun; no owner code or checks were weakened.

Migrations 053/054 add three indexes and replace two shorter indexes. The five
resulting indexes total about 3 GB in this retained multi-generation database;
the three added indexes account for about 1.84 GB. This buys bounded ordered reads
at the cost of storage and extra index maintenance during activation/import. The
normal migration runner builds indexes transactionally during startup; rollout
should allow time for that build. G-NAF indexes remain partial on published rows,
so candidate imports do not populate them. Large ingestion/write throughput was
not rebenchmarked in this read-path change.

Remaining bounds are explicit: search ranks a 500-candidate sample, previews use
offset pagination capped by the existing API, exact statistics may still exhaust
the interactive deadline under heavy load, and caches/host resources affect timing.
The benchmark's 2025 PSI year and recorded UUID are reproducibility inputs, not
application defaults or guaranteed contents of every developer's database.
