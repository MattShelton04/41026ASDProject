# Student 4

- Name: Michael White
- Student ID: 24846267
- UTS email: Michael.h.white@student.uts.edu.au
- Feature: Site, Planning, and Building Due Diligence (Feature 4)

## Ownership

- `frontend/`: assigned feature's frontend microservice
- `backend/`: assigned feature's backend/API microservice and AI interaction
- `database/`: assigned feature's schema, migrations, and seed data
- `tests/`: unit and integration tests for the assigned microservices
- `Dockerfile`: container definition for the assigned services

The completed feature must support CRUD, contain at least ten records per table,
integrate with the unified home page and shared styling, interact with the
approved LLM, and remain part of the integrated group application.

## Approved feature boundary

Provide an evidence-based site due-diligence workspace using accepted PropertyScope planning,
environmental, strata and building information. The feature distinguishes confirmed observations,
non-intersections, partial coverage and unavailable coverage, and does not certify compliance,
safety or legal suitability.

- Frontend: site-review CRUD; verified property selection; source-attributed planning controls;
  supported environmental map layers; strata/building-order/tribunal evidence; explicit evidence
  states; editable checklists/questions/notes/disposition/status; and an AI-generated professional-
  verification question pack.
- Backend/API: site-review CRUD; Feature 1 property validation without database access; versioned
  evidence import; constraint/source retrieval; bounded GeoJSON; match method/confidence; validated
  evidence states; bounded Plan → Act → Observe → Adapt question generation; health and readiness.
- Database: `constraint_observation`, `building_observation` and `site_review`, each with at least ten
  deterministic records.

The approved allocation and complete minimum boundary are maintained in the
[approved feature scope](../docs/architecture/registered-feature-scope.md).

## Implementation status

Feature 4 is **implemented and integrated** — a complete frontend + backend/API + database
microservice set, enabled in the shared application, the unified home page and the common visual
system. Direct CRUD and deterministic evidence work with or without an AI credential.

### Delivered capabilities

- **Database** (`propertyscope_due_diligence_store`): a PostGIS service owning `site_review`,
  `constraint_observation` and `building_observation`, with ordered SQL migrations and **≥ 10
  deterministic seed rows per table** spanning all four evidence states (confirmed, partial
  coverage, non-intersection, unavailable).
- **Backend / API** (`propertyscope_due_diligence`): a credential-free Flask service exposing
  `/health/live`, `/health/ready` and the `/api/due-diligence/v1` surface:
  - Site-review **CRUD** (`site-reviews` list/create/read/update/delete).
  - **Feature 1 property validation and search** over HTTP, with no shared database access.
  - **Evidence retrieval** (`/site-reviews/<id>/evidence`) and **bounded GeoJSON** map layers
    (`/site-reviews/<id>/map`) — a verified property point plus flood/bushfire polygons drawn only
    where the evidence intersects.
  - A **bounded Plan → Act → Observe → Adapt** assistant (`/assistant/turns`) that generates a
    professional-verification question pack through the shared AI-mode service, plus two read-only
    tools the model calls back into (`/tools/duediligence.review.inspect.v1`,
    `/tools/duediligence.evidence.summary.v1`).
- **Frontend**: a design-system UI (shared topbar, sidebar, cards, badges) with a site-review list
  and filter, a **create dialog** with verified-property search, an **edit/delete** flow, an
  **interactive checklist**, a **detail view** showing source-attributed zoning / heritage /
  floor-space-ratio / building-height / flood / bushfire and strata / building-order / tribunal
  evidence with explicit evidence-state badges, an **interactive flood/bushfire map**, and a
  **"Generate with AI"** action that produces and saves the question pack. Served on
  `PROPERTYSCOPE_DUE_DILIGENCE_PORT` (default 5400).
- **Wiring & CI**: `feature.yaml` + `tool-catalog.yaml`, a multi-stage `Dockerfile`, Compose
  services (`f4-postgres`, `f4-db-api`, `f4-backend`, `f4-frontend`), deterministic Python + Node
  tests, and a dedicated `.github/workflows/student-4.yml` build/test/integration workflow.

See [`MARKING_EVIDENCE.md`](MARKING_EVIDENCE.md) for how each assessed requirement is satisfied and
demonstrated.

### Approved LLM

The feature is **provider-neutral**: it never selects a model, and interacts with the approved LLM
only through the shared AI-mode boundary. The registered production profile is OpenAI (GPT-5.6);
an OpenAI-compatible API, including Gemini development profiles, is permitted for local testing.

## Run it locally

Deterministic mode (no AI credential — CRUD, evidence and the map all work):

```
uv run scripts/dev.py stack up --offline
```

With the AI question pack enabled (Gemini development profile). Create a Git-ignored `.env.gemini`
with `AI_MODE_LLM_PROVIDER=gemini`, `AI_MODE_DEFAULT_MODEL_PROFILE=gemini-development.v1` and a
`GEMINI_API_KEY` (free from <https://aistudio.google.com>), then:

```
uv run scripts/dev.py stack up --env-file .env.gemini
```

Open the unified home page at <http://localhost:5100> (Feature 4 appears under "Site and planning")
or the feature directly at <http://localhost:5400>. Stop with `uv run scripts/dev.py stack down`.

The development stack bind-mounts Feature 4 source. Backend and database API edits reload their
Gunicorn workers automatically; frontend edits appear on browser refresh. Use
`uv run scripts/dev.py stack rebuild f4-backend f4-db-api f4-frontend --offline` only after changing
dependencies or Docker build inputs.

## Design decision: evidence sourcing

The approved backend boundary lists "versioned evidence-release import". Feature 1's published
products are property, address, sales, crime and school data; it does not currently publish the
planning, environmental, strata or building evidence this feature reasons over. Feature 4 therefore
populates its owned tables with deterministic, source-attributed seed evidence (migrations `002`
and `003`) rather than importing releases that do not yet exist. The import path can be added if and
when Feature 1 publishes relevant evidence products; this remains an open coordination item for the
team.
