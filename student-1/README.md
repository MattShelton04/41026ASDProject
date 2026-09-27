# Student 1

- Name: Matthew Shelton
- Student ID: 24763373
- UTS email: matthew.n.shelton@student.uts.edu.au
- Feature: Data Platform and Property Discovery (Feature 1)

## Ownership

- `frontend/`: assigned feature's frontend microservice
- `backend/`: assigned feature's backend/API microservice and AI interaction
- `database/`: assigned feature's schema, migrations, and seed data
- `tests/`: unit and integration tests for the assigned microservices
- `Dockerfile`: container definition for the assigned services

The implemented feature supports CRUD, integrates with the unified home page and shared styling,
interacts with the configured remote LLM, and remains part of the currently integrated application
slice. Data volume is demonstrated through registered ingestion runs rather than padding every
persistence table. The
[Release 0 readiness assessment](../docs/release-0/readiness-assessment-2026-08-27.md) records the
remaining evidence and approval gates for treating those implementation claims as
submission-complete.

This ownership and feature boundary are part of the tutor-approved team allocation recorded in the
[approved feature scope](../docs/architecture/registered-feature-scope.md).

## Working interface

The Fieldbook interface keeps a persistent Property data sidebar and compact operational pages.
Sources, data checks, files and published coverage have dedicated destinations. Update details
are directly accessible from the list, while editing and destructive confirmation retain their
existing guarded forms. The overview links to actual versions needing preparation or review.

Property records provide keyboard-accessible Research, Sale history, Area context and Sources
sections beneath a full-width identity-and-location row. A larger map sits to the right of
Property at a glance on desktop; the cards stack before the research sections on mobile.
Switching sections retains loaded evidence and the search-return context; the selected
section is represented in the URL for reloads. Empty sale history remains explicitly unknown.
`frontend/fieldbook.css` owns this feature's composition using public Shared tokens. The source
HTMX lifecycle, map provider, acquisition, review, publication and assistant contracts are unchanged.

## Feature boundary

PropertyScope owns registered source acquisition, reproducible ingestion evidence, the
canonical property/address registry, quality-gated immutable dataset releases, and bounded
property discovery. Other features receive versioned artifacts over HTTP and import them into
their own stores; they never access this feature's PostgreSQL/PostGIS database directly.

For verified official-source counts, examples, bounds, hashes, AI execution and the browser
showcase path, see [Feature 1 marking evidence](MARKING_EVIDENCE.md).
For the implemented provider catalogue, HTTP/artifact contracts, compatibility policy,
publication/recovery lifecycle, dataset semantics, and future-registration procedure, see
[the Release 0 data-product consumer guide](DATA_PRODUCT_CONSUMER_GUIDE.md).
The supported `GET /api/data-platform/v1/product-contracts/v1` discovery resource and its
digest-bound ZIP are the consumer entry point for producer-owned record schemas; consumers do not
read repository paths. Releases use gzip-compressed NDJSON. Producer verification queues durable
local activation; the atomic accepted-pointer switch also creates a downstream delivery outbox.
Consumer imports run independently and cannot block or roll back producer publication. See
[ADR-041](../docs/architecture/decisions/ADR-041-producer-owned-publication.md).

Version-controlled source/job configuration lives in `config/`, HTTP and release schemas in
`contracts/`, and persistence-neutral Pydantic/domain policy in
`backend/src/propertyscope_data_platform/`. Checked-in fixture data is synthetic and explicitly
licensed; live and licensed source artifacts remain outside Git.

The default stack connects the official NSW schools CSV, BOCSAR archives, Geoscape G-NAF bulk
archive, PSI sales sources, and the ABS SEIFA 2021 Suburbs and Localities workbook. Starting services never starts a download. When an operator starts
an update, Feature 1 imports every record in the selected registered scope through the same durable run,
content-addressed artifact, serial loader, candidate generation, quality and human publication
path. Complete source remains the default and there is no operator row ceiling. PSI also offers an
inclusive completed publisher archive-year range; this is explicitly partial, is not an exact
contract-date filter, and cannot replace the accepted complete sales-history generation.

Ten additional producer-owned profiles cover NSW cadastral lots, five planning controls,
bushfire-prone land, published flood-planning controls, ABS 2021 SAL/LGA boundaries,
gazetted suburbs, government school catchments, strata schemes, selected official amenities
and ABS CPI. They retain full declared coverage, source schemas, attributes, dates, CRS and
explicit geometry validity in `propertyscope.reference-feature.v1`. Their target is Feature 1;
downstream joins and feature integration are separate work. See the
[integration plan](../docs/release-1/reference-data-integration-plan.md),
[operations guide](../docs/release-1/reference-data-operations.md) and
[consumer guide](DATA_PRODUCT_CONSUMER_GUIDE.md) for scope and limitations.

Source support does not imply that this developer's environment contains a successfully
accepted release. `/runtime-capabilities` reports implemented transports and configured caches;
the product catalogue's accepted release, run evidence, artifact verification and publication
state establish what is actually available locally. No startup operation automatically
downloads or publishes these datasets.

The Sources, Data updates and Dataset publishing settings pages present the 16 registered
datasets in six plain groups: foundational property data, geography and boundaries, planning and
hazards, community and amenities, economic context, and development fixtures. G-NAF is labelled
as foundational address identity and location, while PSI is labelled as official NSW sale
history. These labels and one-line purposes are presentation metadata: they do not change source
keys, job profiles, product contracts, URLs, or claim that a configured source has an accepted
local release.

New BOCSAR acquisitions use the versioned sparse
`propertyscope.canonical-bocsar-parquet.v1` handoff: positive observations and explicit coverage are
written as typed, Zstandard-compressed Parquet and completely checksum-verified before COPY. The
loader retains JSON/NDJSON compatibility for historical registered artifacts. This internal
canonical optimisation does not change the complete gzip-NDJSON release export or consumer
contract, and it never reads unregistered developer/prototype caches.

New G-NAF acquisitions also use typed, bounded Parquet through
`propertyscope.canonical-gnaf-parquet.v1`. The loader retains legacy JSON/NDJSON replay and
the same normalization and source hashes. This primarily reduces staging storage and file
traffic, rather than PostgreSQL materialisation time. BOCSAR CSV members stream directly
from their ZIP, and shared month coverage is validated once per distinct bounded vector.

New PSI acquisitions use the partition-aware
`propertyscope.canonical-psi-parquet.v1` handoff. Annual and weekly archives remain in registered
source order, with typed, bounded, Zstandard-compressed row groups and the same retransmission row
hashes as legacy NDJSON. The loader verifies the complete file and exact contract before feeding
the unchanged PostgreSQL typed staging, identity/revision, address-resolution and candidate path.
PostgreSQL remains authoritative, historical JSON/NDJSON stays replayable and complete consumer
release exports remain gzip NDJSON.

Bulk imports register provenance once per batch in `warehouse.import_batch`, inside the same
transaction as the facts. Migration 050 backfills existing references and removes the three
per-row release/artifact/run foreign keys from warehouse facts. The loader owns the relationship
between facts and their registered batch; direct administrative SQL no longer enforces it.
Property identity foreign keys, checksums, complete counts and atomic activation remain.
BOCSAR also deduplicates in one ordered pass instead of grouping and joining the stage again.
See [ADR-039](../docs/architecture/decisions/ADR-039-batch-provenance-for-bulk-imports.md).
Refresh the database API and idle loader together after this migration before starting jobs.

Large release builds request a compact private page layout: field names appear once alongside
arrays of row values. The database API retains its ordinary record layout for older workers;
the backend relays these private pages without decoding and re-encoding them. The runner reads
one page ahead while building the current page, with 20,000 address/sale rows or 500 crime series
per page. Generation, count and cursor checks still fence the whole export.

Two spawned projection workers validate and serialize bounded batches for large flat products. A
single runner-owned compressor preserves ordering and deterministic bytes at a fixed compression level; only
the runner handles HTTP, files, leases and registration. Small products avoid process startup.
`PROPERTYSCOPE_RELEASE_PROJECTION_WORKERS` accepts 0..4 (default 2); use 0 for serial projection
on constrained hosts. The Compose CPU/memory limits still apply to the worker children together.
Crime series retain serial projection: linear-time month membership checks remove repeated scans,
and measurements showed process transfer overhead outweighed parallel gains for nested series.
Cancellation stops further scheduling, and unfinished read-only HTTP work retains a 120-second
transport read timeout. Import and publication transactions remain serial and atomic.

`PROPERTYSCOPE_RELEASE_COMPRESSION_LEVEL` accepts 1..9 (runner default 3; set 6 for the previous
compression setting). Level 3 reduces export CPU at the cost of larger release downloads.
Native JSON encoding/decoding handles the private export hop and validated product records;
the public schemas, source hashes, generation fences and complete-record validation remain.
Rebuild the affected services after dependency changes. See the
[performance review](../docs/reviews/feature-1-data-performance-2026-09-09.md) for measurements,
tradeoffs and the full flow, and the [operator UI brief](../docs/ui/feature-1-operator-improvements.md)
for proposed follow-up work.

Reproduce the synthetic export measurements without a network or database:

```text
uv run python scripts/benchmark_feature1_exports.py --product property-snapshot --rows 100000
uv run python scripts/benchmark_feature1_exports.py --product property-sales --rows 100000
uv run python scripts/benchmark_feature1_exports.py --product crime-series --rows 1000
```

These measure transport encoding/decoding and product building, not complete source job duration.
Each variant must produce identical portable gzip bytes at the selected compression level
(`--compression-level 3` measures the runner default). Parquet staging reports
consumed row checkpoints during COPY, including the final partial batch, rather than leaving
Update history at zero until materialisation begins.

PSI exact-address matching uses the accepted, published G-NAF generation and recognised street-type
equivalents. Unique matches create only the missing registry reference anchors needed for the
sales foreign key; canonical addresses still come from the accepted warehouse generation. See
[ADR-038](../docs/architecture/decisions/ADR-038-psi-accepted-gnaf-reference-anchors.md).
Full-history PSI matching builds transaction-local address dictionaries and joins sales addresses
in batches, avoiding repeated lookup queries against the full property register. Exact matching,
ambiguity handling and source facts remain unchanged.
After correcting an import failure, **Use downloaded file** on its run creates a cached reprocess
with the same scope and lineage. Selected archive-year runs remain partial and non-publishable.

The PSI adapter is verified against real publisher archives and parses every annual archive from
1990 onward plus current Monday weekly updates. Archives download into temporary files and
DAT members are consumed as streams, so the archive and expanded records are not duplicated in
application memory. Ordinary publisher requests may receive HTTP 403, so acquisition retries
through validated Range requests; a read-only cache can avoid repeat downloads. Fixture
runs never silently stand in for a requested live run. A handful of publisher rows contain an
undocumented area unit or impossible nonblank date: the original sale/area facts remain retained,
while derived square metres or dates are left unknown rather than guessed.

## Run it locally

Start Docker Desktop, then use the repository workflow from the project root:

```text
uv sync --locked --all-packages --all-groups
uv run scripts/dev.py stack up
```

Use `uv run scripts/dev.py stack up --offline` when validating Feature 1 without an OpenAI credential.
Database migrations and the deterministic showcase baseline are automatic in both modes; no SQL,
seed script, or Docker Desktop action is required.

For a long full-history data session, use
`uv run scripts/dev.py stack up --offline --no-reload --build` before starting jobs. This uses
built images and avoids development reload polling (particularly expensive on Windows bind mounts).
It preserves the same project/volumes. Rebuild after edits in this mode; plain `stack up` restores
the usual source mounts and reload behavior. Switching modes can recreate workers, so do it while
idle. The performance review separates this runtime choice from parser/query improvements.

For frontend-only browser work, `uv run scripts/dev.py ui serve` serves Shared and Feature 1 together on
loopback with explicit deterministic UI scenarios and no Docker, database or model credential. See
[`docs/ui/feature-1-fixture-mode.md`](../docs/ui/feature-1-fixture-mode.md) for URLs and the
Playwright smoke command. This audit host is separate from the production-like showcase path below.

Open <http://localhost:5200>. The main product path is:

1. Use **Property search** to find a NSW address, review the sources available for it and, when a
   compatible NSW PSI generation has been accepted, inspect its matched sale history. Once an ABS
   SEIFA generation is accepted, the same page shows the four 2021 SAL indexes and Australian
   deciles for an exact normalised NSW locality match. SEIFA is labelled as area context—not a
   property, household, or resident score. The page loads identity first and hydrates each optional
   evidence panel separately. Candidate or unpublished rows never appear in buyer-facing results.
2. Use **Data overview** to check whether published property data is current or needs attention.
3. Open **Data updates**, choose an update, then select **Start update** or **Load earlier data**.
4. Preview the source and proposed work, then follow progress in **Update history**.
   Each timeline step shows its elapsed or completed duration. Active row/byte phases show bounded
   progress and an approximate remaining time once enough evidence exists; set-based database work
   stays explicitly indeterminate rather than presenting a misleading 100% bar. An interrupted
   detail page performs a finite slow reconciliation check and refreshes immediately when its tab
   becomes visible, so a resume performed elsewhere appears on the already-open page.
5. Review new versions under **Published data** before publishing or rejecting them. Data checks,
   files and coverage are opened from the update or version they explain instead of appearing as
   separate primary destinations. Publication returns after queueing a durable background
   activation; the release page shows **Publishing** while the prior accepted version remains live.
   Publication reconciliation runs independently of acquisition/export. The page continues slow
   polling for long imports. Lightweight activations run independently of serial bulk imports and
   GNAF index builds, retaining artifact verification and fenced accepted-pointer transactions.
   The page refreshes when its tab becomes visible and loads record previews
   separately from current state/actions. **Retry publication** preserves failed receipts and
   retries local activation with a fresh attempt key. See
   [ADR-040](../docs/architecture/decisions/ADR-040-publication-recovery-and-current-state.md) and the
   [live investigation](../docs/operations/publication-investigation-2026-09-05.md).
   Full PSI publication is independent of Feature 2. Its importer now accepts durable background
   work and streams the complete dataset without a total record/byte cap (ADR-042). Failed delivery
   is reported separately and can be retried with **Retry downstream import** on the published
   release. Feature 1 publishes all records without truncation.
6. When a version needs interpretation, select **Review with AI**. AI review is optional, cannot
   publish changes and remains available later in **Activity history**. Dataset, failed-check and
   publishing entry points use the shared chat with the exact dataset attached and an editable
   suggested question. Existing `#ai/<run-id>` links reopen their saved answer and source inspection
   in that same component, with follow-up questions available after the review finishes.

Use **Ask about Property data** for free-form, read-only questions about the feature, its sources,
updates, releases, coverage or accepted property evidence. Both this page and **AI review** use the
shared chat interface; each new message creates a read-only durable AI-mode run, shows its evidence and
activity link, and supplies a bounded copy of completed visible exchanges to the next follow-up.
Only one response runs at a time. From an update detail page, **Ask AI about update** supplies the
exact run as validated page context, allowing the assistant to explain the current stage, durable counters,
quality evidence, errors and limitations without inventing a remaining-time forecast. See
[`docs/ui/shared-ai-chat.md`](../docs/ui/shared-ai-chat.md).

The assistant also exposes an exact accepted-generation locality summary for questions such as
"How many registered addresses are in Sutherland 2232?" Counts are computed in PostgreSQL rather
than estimated from fuzzy search results, and are explicitly address-record counts rather than
claims about houses, dwellings, legal lots or ownership. Tool availability is stable: when a
compatible accepted dataset is missing, tools return typed availability evidence instead of being
dynamically hidden. Address resolution, quality and catalogue questions continue to use the existing
search, release-inspection and source/release tools rather than duplicating overlapping tools.

Property search accepts short suburb names such as Glebe and Sydney and optional NSW/postcode
suffixes. It prefers exact locality or street-name matches before substring matching, returning
25 results per page from a fixed 500-candidate window. Add more address detail to narrow a broad
search. Property records reuse one snapshot for location, coverage and source summary; sale
history and area evidence load when their sections first open. Release previews fetch one extra
row to determine continuation and label totals as lower bounds instead of counting the entire
source on each page. Complete downloads retain all records.

The [API map and performance review](../docs/reviews/feature-1-api-performance-2026-09-13.md)
documents the measured before/after results, indexes, interactive SQL deadlines, compatibility
boundaries, and the `scripts/benchmark_feature1_api.py` reproduction command.

### Which local URL and container should I use?

The Docker stack and the frontend-only fixture server are separate environments:

| Address or container | Purpose |
| --- | --- |
| <http://localhost:5100/features/data-platform/> | Feature 1 through the integrated PropertyScope shell; use this to verify shared navigation and the real stack together. |
| <http://localhost:5200> | The same live Feature 1 backend and PostgreSQL data through its direct frontend; use this for focused Feature 1 development. |
| <http://127.0.0.1:5990> | Deterministic `ui serve` fixtures only; no Docker runner, loader, official source, or durable PostgreSQL workflow. |
| `ps-dev-f1-runner-1` | The serial acquisition worker. It claims durable run tasks, downloads and parses only registered official sources, writes verified content-addressed artifacts, and heartbeats/cancels work through private HTTP APIs. It serves no browser port and has no PostgreSQL credentials. |
| `ps-dev-f1-db-loader-1` | The separate serial database loader. It verifies runner artifacts and performs registered PostgreSQL COPY/import operations; keeping credentials here prevents the runner and backend from opening the database. |

`5100` and `5200` being healthy at the same time is expected: `5100` is the shared edge and `5200`
is Feature 1's direct ingress. Run `uv run scripts/dev.py stack status` for the authoritative live
service list. Use `uv run scripts/dev.py stack logs f1-runner` when an acquisition is queued but not
progressing; use `stack logs f1-db-loader` when it is specifically waiting in the import stage.
For source-scale publication/write triage, safe targeted restarts and activation recovery, use the
[large-data operations runbook](../docs/release-0/feature-1-large-data-operations.md).

The acquisition path can also run without browser actions. This queues the registered deterministic
fixture, waits for all runner and loader stages, and reports the retained candidate release:

```text
uv run scripts/dev.py data collect fixture-property
```

Use `schools-master`, `bocsar-crime`, `gnaf-nsw`, `psi-sales`, or `abs-seifa-2021` to request the complete registered
source, and add `--no-wait` for a long job. These commands automate discovery,
acquisition, validation, import, normalisation, quality checks, and candidate construction. They do
not bypass the separate human decision to submit, accept, or reject a candidate.

The browser and public plan/run API additionally support selected completed annual archives for the
PSI job. Choose **Selected publisher archive years**, then an inclusive first and last year. The
backend expands that choice to a contiguous partition list and persists it through run and release
evidence. Archive years are source packaging, not guaranteed contract-date bounds. Scoped results
remain partial candidates and the publication boundary refuses to replace complete accepted history
with them. The data CLI intentionally continues to request the complete registered scope.

Run `uv run scripts/dev.py stack down` when finished. Named AI history, PostgreSQL and artifact
volumes are preserved.

## Real-source captures

Real acquisition uses the normal Compose project and PostgreSQL volume:

```text
uv run scripts/dev.py data sync-psi --all
uv run scripts/dev.py stack up
```

A complete project reset is also code-driven: `uv run scripts/dev.py stack reset` removes only the
local project's labelled Docker volumes. The following `stack up` recreates PostgreSQL, migrates it,
and restores the deterministic operator baseline automatically.

| Import profile | Status | Upstream behaviour |
|---|---|---|
| `schools-master` | Connected | Imports every row in the official Data.NSW master CSV. |
| `bocsar-sparse` | Connected | Streams the complete official postcode and suburb ZIPs into sparse observations plus explicit coverage rows; the downstream consumer release remains separately bounded. |
| `gnaf-nsw` | Connected | Discovers the latest registered PSV ZIP from Data.gov.au, or uses the optional local source cache below; preserves unit identity and transforms declared GDA94/GDA2020 coordinates to WGS84 at import. |
| `psi-sales` | Connected | Streams complete annual history and current weekly packages, including the pre-2001 root-DAT format. Stable source keys collapse identical retransmissions. |
| `seifa-2021-sal-nsw` | Connected | Downloads the official national ABS 2021 SAL workbook, validates its fixed Table 1 headings, and imports every NSW SAL row with the four scores, Australian deciles, population, and source provenance. |

SEIFA refreshes are census-release-driven rather than periodic. The registered `full-data` scope
means the complete NSW subset of the official national SAL workbook; it is not a sample or an
operator-selected row cap. ABS `-` values remain explicit null score/decile pairs. Published output
uses the `propertyscope.seifa-area.v1` gzip-NDJSON contract under CC BY 4.0 and the UI carries the
required “Based on Australian Bureau of Statistics data” attribution.

G-NAF is about 1.7 GB. To avoid downloading it again after a local reset, place an official
PSV archive at `.propertyscope-source-cache/gnaf.zip` and declare its CRS before startup:

```powershell
$env:PROPERTYSCOPE_GNAF_CRS = "GDA94" # or GDA2020
uv run scripts/dev.py stack up
```

The cache directory is Git-ignored and mounted read-only. Another checkout can reuse it
by setting `PROPERTYSCOPE_SOURCE_CACHE_DIR` (for example
`../41026ASDProject/.propertyscope-source-cache`) in its `.env`; `stack doctor` shows the
cache in use. Without a cache, the runner discovers
and downloads the latest registered archive from the official CKAN package. The runner streams
every NSW address into an isolated candidate generation without an operator row ceiling.
Deterministic demonstrations use the finite fixture source instead of reducing G-NAF.

The same cache supports official PSI annual packages. Place any unmodified publisher archive at
`.propertyscope-source-cache/psi/<year>.zip` (for example `psi/2025.zip`) before starting the
stack. Missing years are acquired from the official source. Each update processes annual archives
from 1990 through the previous year and every Monday weekly partition in the current year.
Canonical NDJSON and PostgreSQL COPY stream without a record cap or job byte ceiling.

For a true from-scratch PSI build, `uv run scripts/dev.py data sync-psi --all` acquires and ZIP-verifies
every annual archive plus the current-year Monday archives on the host, where the publisher does not
issue the Cloudflare Linux-container challenge. It writes atomically into the Git-ignored cache that
the application mounts read-only. Targeted alternatives are `--year 2025`, `--week 2026-08-10`, and
`--current-weekly`; rerunning retains already verified archives.

Every publishable full-data release contains the complete immutable generation as a deterministic gzip NDJSON
artifact. Every release detail page also includes a separately labelled, release-scoped dataset
preview. Preview queries use fixed registered projections, cap pages at 100 records and never mix
candidate and accepted generations; that browser bound does not truncate the release. Official
sources are connected in the default stack. Complete acquisition/release construction remains the
default; selected-year PSI runs create clearly partial, non-publishable candidates. Licence and redistribution policy still controls whether the complete artifact
may be downloaded or retained as metadata-only evidence.

## Shared integration boundary

The Feature 1 frontend calls only its backend. The backend and runner call the private database
API over HTTP; neither imports the database package nor receives PostgreSQL credentials. The
serial loader is the only process besides the database API that owns those credentials. Shared
AI-mode loads Feature 1's allowlisted tool catalogue, calls its bounded HTTP tools and stores
diagnosis history in AI-mode's own database. It never reads PropertyScope PostgreSQL directly.

Tutor approval for the narrow ADR-016 PostgreSQL/PostGIS exception has been confirmed. A durable
link or copy of that written approval should still be attached to the submission evidence; the
implementation and executable architecture checks cannot substitute for that record.

## Backend structure and correlation

`api.py` is the HTTP composition surface. It retains service health, runtime capability and
artifact-retention endpoints, then delegates cohesive route families to registrars. Data-product
catalogue reads live in `data_product_routes.py`; release HTTP binding lives in
`release_routes.py`; candidate loading, publication state transitions and public evidence
projection live separately in `release_imports.py`, `release_publication.py` and
`release_projection.py`. Generic Flask response/proxy mechanics live in `http_support.py`;
registered run-scope rules live in the framework-independent `scope_policy.py`; protected tool
approval matching lives in `approval.py`; and registered source acquisition lives in
`source_transport.py`. Source-format parsing remains under `adapters/`, while `runner.py`
coordinates durable tasks and heartbeats rather than owning transport policy.

The database service keeps one public transaction-owning facade in `repository.py`. Registered
import lifecycle SQL is isolated behind its private `_import_operations.py` collaborator; outbound
publication delivery and crash-safe reconciliation are isolated behind
`_consumer_import_operations.py`;
generation-aware canonical-property discovery lives in `_property_reads.py`; and release metadata
plus bounded immutable-generation projections live in `_release_records.py`. Each collaborator
depends on a narrow owner protocol and is reached through the stable facade, so callers retain one
repository contract and transaction owner. Immutable release query specifications live in
`query_specs.py`, retry/task sequencing lives in `orchestration_policy.py`, and serialization/replay
projections live in `persistence_support.py`. This keeps PostgreSQL atomicity visible at one facade
without burying every persistence aggregate, pure policy, and public projection contract in the
same repository module.

Runtime versions are not duplicated in repository constants. At database API startup,
`runtime_registry.py` loads an immutable persistence projection from the reviewed
`config/job-profiles/*.yaml` documents and injects it into the store. The credential-free backend
independently validates the same declarative boundary against its executable adapter and release
builder registries; neither service imports the other's package. Job creation derives every
persisted profile, adapter, builder, import-profile and quality-policy version from that registry,
rejecting unknown profiles, contradictory component versions and stale caller snapshots.

At the shared proxy and every Feature 1 HTTP hop, `X-Request-ID`, `X-Agent-Run-ID`, `traceparent`
and `Idempotency-Key` are forwarded case-insensitively under canonical names. Invalid request/span
identifiers are replaced or dropped at ingress rather than becoming misleading correlation data.

## Frontend structure

The production browser remains framework-free and calls only the Feature 1 backend. Cross-cutting
behavior is split under `frontend/core/` (API/Problem Details, routing, formatting/evidence,
forms and polling guards), reusable DOM primitives live under `frontend/components/`, and migrated
screens live under `frontend/routes/`. The primary product navigation contains Property search,
Data overview, Data updates, Update history and Published data. Source definitions, product
contracts, quality checks, files and coverage remain available as contextual specialist routes but
are not presented as competing top-level workflows. `app.js` is the transition composition root.
The independently built frontend image copies shared design-system v0.1 assets, while the
development overlay mounts the same source files for reload.

Data updates, Update history and Published data use bookmarkable previous/next pages. Search,
status, job and publication-state filters run before database pagination, including matches
outside the first 100 records. Changing a property query cancels its obsolete read immediately;
release previews serialize page requests. Route replacement and inner refreshes dispose table
observers and open action-menu listeners.

### Source-definition HTMX CRUD

Source definitions are the representative Release 0 HTMX CRUD slice. Opening `#sources` creates a
loading region that performs a real request to `/fragments/data-platform/v1/sources`. Feature 1
Nginx proxies that same-origin path to the existing Flask backend, whose Jinja fragment blueprint
uses the injected `DataStoreClient` to call `/internal/data-platform/v1/sources` on the private
database API. The frontend and backend never import the database implementation or open PostgreSQL.

The list, detail, create, edit, validation/conflict, delete-confirmation, success, empty, not-found,
dependency-failure, and retry states are server-rendered and autoescaped. Forms use `hx-get`,
`hx-post`, `hx-put`, and `hx-delete` with explicit targets, swaps, indicators, and disabled controls.
Request IDs and supported correlation/idempotency headers continue through the existing client;
optimistic updates submit the stored `version`. Current persistence does not claim replay-safe
create/delete idempotency beyond the conventions already implemented by the database service.

External `frontend/routes/sources-htmx.js` glue keeps native dialog dirty-state protection, swaps
HTML error responses for 409/422/503, restores focus, and keeps hash deep links coherent. The old
Source JSON renderer and submit handler are removed so one user action produces one mutation. Jobs
and all other JSON routes remain unchanged. Maps, assistant chat, agent/run timelines, adaptive
polling, charts, route composition, and the existing robust dialog primitives intentionally remain
JavaScript.

`uv run scripts/dev.py ui serve` provides a bounded per-browser-session in-memory Source store for
isolated create/update/conflict/delete checks; it never writes a database or volume. Validate with
`uv run pytest student-1/tests/component/test_source_fragments.py --no-cov -q` and
`uv run pytest student-1/tests/e2e/test_form_behaviour_playwright.py --no-cov -q`. In Compose, the
same asset and fragment routes are available through ports 5100 and 5200 and the fragment request
continues through the real Feature 1 backend/private database API boundary.

`frontend/integration/shell.js` is Feature 1's public adapter for the Shared product shell. Its
`createFeature1ShellAdapter()` export owns
Feature 1 search routing, release-envelope projection, data-store readiness interpretation and
feature-scoped activity links. Shared loads the adapter over the feature's existing HTTP ingress;
there is no compile-time Shared-to-Feature import. Feature code consumes Shared JavaScript through
the public `browser/index.js` and `mapping/index.js` barrels copied/mounted by the existing frontend
image workflow.

Property detail uses the shared MapLibre/OpenFreeMap provider under
`shared/frontend/mapping/` rather than a decorative map placeholder. The feature supplies the
verified property point and popup meaning through its existing public `map-context` endpoint; the
shared package owns GeoJSON validation, renderer/provider lifecycle, tile failure fallback and
camera interactions. See the [shared mapping README](../shared/frontend/mapping/README.md) for
adding schools, suburb/area polygons, viewport-backed layers and a different basemap provider.

### Operator progress and activity

Run detail leads with the registered source name, current stage, attempt elapsed time, heartbeat
age and last observed progress change. Verified Parquet metadata supplies COPY row totals;
SQL joins/index phases remain indeterminate. Resume restarts the interrupted stage and clears
its attempt counters/timestamps while the earlier attempt remains in saved activity.

`GET /api/data-platform/v1/ingestion-runs/{id}/activity` relays the database owner's bounded
`ops.run_activity` log. The database records stage/status/attempt/counter changes atomically
with task updates, omits heartbeat-only noise and retains the latest 1,000 events per run.
Only phase names, counts and bounded error codes are logged: no lease tokens, raw exception
messages or property records. Existing tasks receive an explicitly labelled migration snapshot.
The UI polls overlapping recent windows, deduplicates event IDs, and supports pause, filtering,
autoscroll and a text download. It is an operator progress log, not raw container stdout.

The in-app notification inbox observes job completion, failure, interruption, cancellation,
publication and downstream-delivery outcomes
every 15 seconds while open (30 seconds in background tabs). Read state and deduplication are
stored on this browser origin; the initial historical list does not create a notification storm.
One bounded `/notifications` projection returns the latest 100 states by activity time without
source snapshots, manifests or credentials. Desktop notifications are optional and permission
is requested only from the explicit enable button. There is no email, service worker or off-device
delivery service. Detailed follow-up scope and limitations are in
[`docs/ui/feature-1-operator-improvements.md`](../docs/ui/feature-1-operator-improvements.md).
