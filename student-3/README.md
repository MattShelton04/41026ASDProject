# Student 3

- Name: James Huang
- Student ID: 24970865
- UTS email: Zihuang.huang@student.uts.edu.au
- Feature: Suburb, Crime, and Liveability Analytics (Feature 3)

## Ownership

- `frontend/`: assigned feature's frontend microservice
- `backend/`: assigned feature's backend/API microservice and AI interaction
- `database/`: assigned feature's schema, migrations, and seed data
- `tests/`: unit and integration tests for the assigned microservices
- `Dockerfile`: container definition for the assigned services

This directory contains the functional Feature 3 slice. It supports deterministic suburb search,
LGA/amenity filters and sorting, map/place filters, evidence-backed context cards, selected offence
categories, same-period count/rate comparisons with an accessible chart table, saved-comparison
CRUD, property-relative nearby places, and an optional bounded AI assistant. Deterministic views and
CRUD remain available when AI-mode is unavailable.

## Approved feature boundary

Provide suburb information, local crime and safety data, and liveability metrics that help users
assess a location and make informed property-research decisions using approved Australian Bureau of
Statistics, NSW Government and other relevant public datasets.

- Frontend: suburb search/filter/sort; saved and favourite suburb CRUD; summary cards and
  visualisations; and filters for liveability indicators, amenities, local government area and
  location.
- Backend/API: suburb and user-data CRUD; location validation; approved government-data ingestion;
  query, filter, sort, aggregate and pagination; liveability/amenity/location projections;
  authenticated user-specific saved-suburb endpoints; and structured data for cards,
  visualisations and maps.
- Database: `suburb_info`, `suburb_indicators`, `suburb_amenity`, `suburb_overview` and
  `user_suburbs`, each with at least ten deterministic records.

The approved allocation and complete minimum boundary are maintained in the
[approved feature scope](../docs/architecture/registered-feature-scope.md). This README records
ownership and implementation scope. The checked-in source data is explicitly a deterministic, partial
demonstration fixture; it is not represented as current official crime or liveability evidence.

## Feature layout

- `frontend/`: responsive product UI using the shared design-system and mapping assets at image
  build time; charts always include a data-table alternative.
- `backend/`: public `/api/suburb-analytics/v1` WSGI API, pagination and validation, neutral
  comparison projection, property map-context integration, AI-mode client and allowlisted tools.
- `database/`: the only process that opens the feature-owned SQLite file; migrations, five assessed
  tables, ten-plus deterministic records per table and internal CRUD endpoints.
- `tool-catalog.yaml`: read-only MCP tools for published locality evidence and methodology; the
  deterministic crime-comparison tool remains outside the current assistant allowlist.
- `config/rag/`: reviewed public guidance about evidence, interpretation and unsupported claims.
- `tests/`: persistence, version-conflict, responsible-comparison, AI-degradation and frontend
  contract checks.

## Local development

Start the integrated stack from the repository root with `uv run scripts/dev.py stack up`.
After dependency or Dockerfile changes, use `uv run scripts/dev.py stack rebuild`.
Open `http://localhost:5100/features/suburb-analytics/#suburbs` through the shared shell or
`http://localhost:5600/` directly. The host port can be overridden with
`PROPERTYSCOPE_SUBURB_ANALYTICS_PORT`; 5300 belongs to Feature 2 and the separate UI fixture server.

For standalone development without Docker, start the database, backend and frontend in three
separate terminals from the repository root:

```powershell
$env:PYTHONPATH='student-3/database/src'; $env:SUBURB_DB_PATH='student-3/.local/suburbs.sqlite3'; python -m propertyscope_suburb_store.app
$env:PYTHONPATH='student-3/backend/src'; $env:SUBURB_STORE_URL='http://127.0.0.1:5302'; $env:AI_MODE_URL='http://127.0.0.1:5005'; $env:PROPERTY_DATA_URL='http://127.0.0.1:5200'; python -m propertyscope_suburb_analytics.app
$env:PORT='5600'; python student-3/frontend/dev_server.py
```

Then open `http://127.0.0.1:5600/`.

The Dockerfile exposes independent `database`, `backend` and `frontend` targets. Root Compose
starts `f3-database`, `f3-backend` and `f3-frontend` through the enabled feature manifest. Only the
database mounts `f3-suburb-data`; the backend reaches it, Feature 1 and shared AI-mode over HTTP.
The internal 5301/5302 ports are not published to the host and do not conflict with other containers.
The locked Gunicorn runtime serves the WSGI application factories; the development overlay reloads
backend/database source and serves frontend edits directly. The standalone servers use Python's
standard library. `stack down` preserves the database volume.

## Current data and platform assumptions

### Shared-source ingestion

Feature 3 now consumes immutable releases through Feature 1's supported HTTP contract and
artifact APIs. It never opens Feature 1's PostgreSQL database, receives its credentials, or
imports its Python implementation. No publisher download or shared publication happens at startup.

Supported products:

| Dataset | Consumer contract | Activation |
| --- | --- | --- |
| `bocsar-crime` | `propertyscope.crime-series.v2` | Feature 1 publication callback or explicit accepted-release sync |
| `nsw-government-schools` | `propertyscope.school-points.v2` | Feature 1 publication callback or explicit accepted-release sync |
| `abs-seifa-2021` | `propertyscope.seifa-area.v1` | Background or explicit sync of Feature 1's accepted release only |

Population retains its producer-declared `feature-1` target; it is a local read replica, not a
Feature 3 publication acknowledgement sent back to the producer. Boundaries and other amenities
remain out of scope. Dataset acquisition, quality review and shared publication still belong to
Feature 1 and require the team's normal approval workflow.

The backend implements `POST /api/data-import/v1/propertyscope-releases` and
`GET /api/data-import/v1/propertyscope-releases/{operation_id}` on its internal service origin.
The callback requires matching body/header idempotency keys and forwards request correlation.
Root Compose supplies `PROPERTYSCOPE_FEATURE_3_URL=http://f3-backend:5301` to Feature 1 and
`SUBURB_IMPORT_WORKER=1` to the single-worker Feature 3 backend. The database durably queues each
operation; the backend worker streams downloads and stages bounded batches through the database
HTTP API. A 180-second renewable, fenced lease permits recovery after a backend restart.
Transport and pre-commit database outages retry with bounded backoff for up to five attempts.
Recovery revalidates the stream and reuses identical staged rows; conflicting replay is rejected.
SQLite WAL lets status reads proceed during staging writes. Original terminal receipts and delivery
keys remain immutable; a fresh key after a closed failed receipt creates a new operation, while
active or accepted matching imports coalesce. Rebuild `f3-backend` after installing the compiled
`jsonschema-rs` dependency; record/manifest format and semantic validation remain mandatory.
See [ADR-040](../docs/architecture/decisions/ADR-040-publication-recovery-and-current-state.md).

Before commit, the importer checks the digest-bound producer contract archive, selected schema and
builder, manifest/record provenance, gzip integrity, SHA-256, exact byte/record counts, unique
record keys and crime coverage semantics. It rejects redirects and external schema references.
Limits are 1 GB compressed, 12 GB expanded, one million records and 500 KB per record. These accept
the currently observed ~500 MB BOCSAR candidate declaration but are not a source-scale benchmark.
Insufficient capacity fails explicitly, never truncates. Verified receipt and current-data pointer
commit together; unverified staging is hidden. Failed imports retain the previous current release.
Unknown commit outcomes reconcile durable state before lease recovery. Explicit retry retains the
previous failure receipt; it does not silently retry terminal failures forever.

Open the **Published evidence** sidebar tab at `http://localhost:5600/#published` to inspect the
accepted releases. **Overview & map** and **Crime trends** now use those same published records;
the map shows published school locations after selecting a locality and the trend comparison uses
published BOCSAR observations.
The backend checks already
accepted releases at startup and every fifteen minutes, independently of browser traffic. Repeated
checks retain the same import identity and do not re-download imported releases. The visible page
refreshes availability every thirty seconds. Manual sync/status/retry controls are optional recovery
tools inside the collapsed **Data maintenance (operators)** section. Terminal failures require an
operator retry after their underlying issue is resolved; visiting a suburb never starts a download.
Suburb pins zoom to neighbourhood level and load the selected amenity types; accessible suburb
buttons remain as an alternative. Rapid selections cannot overwrite the latest suburb's amenities.
The equivalent public API is:

```text
POST /api/suburb-analytics/v1/data-imports/{dataset_id}/sync
POST /api/suburb-analytics/v1/data-imports/{operation_id}/retry
GET  /api/suburb-analytics/v1/published/sources
GET  /api/suburb-analytics/v1/published/suburbs?q=Parramatta&offset=0
GET  /api/suburb-analytics/v1/published/context?locality=Parramatta
```

Imported locality searches are paginated independently of the ten-suburb demo. Context shows
2021 population, government school locations/status and the last twelve covered crime months per
actual source category, with complete retained series available in the context API. Crime counts
are zero only inside the declared observation universe when the source permits it. Postcodes are
retained but never relabelled as suburbs. Exact normalised name matching does not resolve boundary
differences; duplicate ABS locality matches are shown as ambiguous. No rates are calculated from
2021 population against recent crime. Missing amenities/area/LGA boundaries are not invented.
School catchment boundaries are not part of the accepted Feature 1 releases, so the UI labels
catchment status as `not_assessed` and never infers eligibility from school proximity. Saved
comparisons and AI tools retain their existing bounded behavior while their evidence calls are
being migrated to the published projection.

The owned record index includes `(operation_id, locality, record_key)` so locality context can
filter and return records in order without scanning an entire imported release. Startup upgrades
the older two-column index in place, preserving imported records and receipts. See the
[Feature 1 performance review](../docs/reviews/feature-1-data-performance-2026-09-09.md) for the
full-source query measurements.

Local activation check (3 September 2026): the producer's accepted synthetic crime and school
artifact endpoints returned HTTP 503 `artifact_unavailable`; the full BOCSAR candidate returned
409 `artifact_not_publishable`. Population has no accepted release. These upstream prerequisites
must be resolved before real data appears. No shared datasets were downloaded, published or
replaced while implementing the consumer.

- The checked-in dataset is a partial deterministic demonstration fixture, not live official data.
- Authentication remains a shared-platform decision, so local saved comparisons operate as a
  single-user demo rather than inventing a feature-specific identity scheme.
- Overview & map includes a bookmarked-suburb shortlist. Select a map pin or suburb card to
  bookmark/remove that suburb, then use **Bookmarked suburbs** to reopen or remove saved entries.
  Bookmarks persist in browser local storage for that origin, not an authenticated account;
  direct and shared-shell origins have separate lists. Clearing site data removes the shortlist.
- Nearby-place distances are straight-line distances. School proximity never implies catchment or
  enrolment eligibility.
- The grounded assistant is available only in the dedicated Ask AI workspace and as a selected-
  locality sidecar on Overview & map. Crime Trends and Saved Comparisons remain deterministic and
  expose no AI action. The assistant cannot call the crime-comparison tool.

## Responsible analytics constraints

- Count and rate requests cannot be mixed within a comparison.
- Recorded zero is labelled explicitly; missing evidence remains null and is never plotted as zero.
- The UI and AI objective prohibit causal claims, prediction, and safe/unsafe or good/bad rankings.
- Nearby schools are not presented as catchment or eligibility evidence.
