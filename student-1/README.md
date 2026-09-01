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
read repository paths. Releases use gzip-compressed NDJSON, and external publication is a
durable consumer-import operation with a short connect phase and a fixed status resource. The final
receipt is stored before activation is queued; the prior accepted release remains live until the
atomic pointer switch completes.

Version-controlled source/job configuration lives in `config/`, HTTP and release schemas in
`contracts/`, and persistence-neutral Pydantic/domain policy in
`backend/src/propertyscope_data_platform/`. Checked-in fixture data is synthetic and explicitly
licensed; live and licensed source artifacts remain outside Git.

The default stack connects the official NSW schools CSV, BOCSAR archives, Geoscape G-NAF bulk
archive and PSI sales sources. Starting services never starts a download. When an operator starts
an update, Feature 1 imports every record in the selected registered scope through the same durable run,
content-addressed artifact, serial loader, candidate generation, quality and human publication
path. Complete source remains the default and there is no operator row ceiling. PSI also offers an
inclusive completed publisher archive-year range; this is explicitly partial, is not an exact
contract-date filter, and cannot replace the accepted complete sales-history generation.

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

For frontend-only browser work, `uv run scripts/dev.py ui serve` serves Shared and Feature 1 together on
loopback with explicit deterministic UI scenarios and no Docker, database or model credential. See
[`docs/ui/feature-1-fixture-mode.md`](../docs/ui/feature-1-fixture-mode.md) for URLs and the
Playwright smoke command. This audit host is separate from the production-like showcase path below.

Open <http://localhost:5200>. The main product path is:

1. Use **Property search** to find a NSW address, review the sources available for it and, when a
   compatible NSW PSI generation has been accepted, inspect its matched sale history. The page
   loads identity first and hydrates the bounded latest-revision sale timeline separately. Candidate
   or unpublished PSI rows never appear in buyer-facing property results.
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
   activation; the release page shows its progress while the prior accepted version remains live.
6. When a version needs interpretation, select **Review with AI**. AI review is optional, cannot
   publish changes and remains available later in **Activity history**.

Use **Ask about Property data** for free-form, read-only questions about the feature, its sources,
updates, releases, coverage or accepted property evidence. This shared chat interface is separate
from the fixed Data review flow; each message creates a durable AI-mode run, shows its evidence and
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

### Which local URL and container should I use?

The Docker stack and the frontend-only fixture server are separate environments:

| Address or container | Purpose |
| --- | --- |
| <http://localhost:5100/features/data-platform/> | Feature 1 through the integrated PropertyScope shell; use this to verify shared navigation and the real stack together. |
| <http://localhost:5200> | The same live Feature 1 backend and PostgreSQL data through its direct frontend; use this for focused Feature 1 development. |
| <http://127.0.0.1:5300> | Deterministic `ui serve` fixtures only; no Docker runner, loader, official source, or durable PostgreSQL workflow. |
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

Use `schools-master`, `bocsar-crime`, `gnaf-nsw`, or `psi-sales` to request the complete registered
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

G-NAF is about 1.7 GB. To avoid downloading it again after a local reset, place an official
PSV archive at `.propertyscope-source-cache/gnaf.zip` and declare its CRS before startup:

```powershell
$env:PROPERTYSCOPE_GNAF_CRS = "GDA94" # or GDA2020
uv run scripts/dev.py stack up
```

The cache directory is Git-ignored and mounted read-only. Without a cache, the runner discovers
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
