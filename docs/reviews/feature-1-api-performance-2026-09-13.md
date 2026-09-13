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

Implementation, repeated before/after measurements and final validation follow
in subsequent commits on this branch.
