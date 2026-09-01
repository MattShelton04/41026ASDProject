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

## Scaffold status

A runnable vertical-slice scaffold is now in place (frontend + backend/API + database
microservices), registered and **enabled** in the shared application. It is a **starting
point**, not the finished feature — expand it to the full approved boundary above.

Implemented so far:

- **Database** (`propertyscope_due_diligence_store`): PostGIS service with `site_review`,
  `constraint_observation` and `building_observation` tables, ordered SQL migrations, and at
  least ten deterministic seed rows per table.
- **Backend/API** (`propertyscope_due_diligence`): credential-free Flask service exposing
  `/health/live`, `/health/ready` and the `/api/due-diligence/v1` site-review CRUD, evidence
  retrieval, and Feature 1 property validation over HTTP. Direct CRUD keeps working when
  Feature 1 is unavailable.
- **Frontend**: dependency-free page that lists site reviews, integrated into the unified home
  page and served on `PROPERTYSCOPE_DUE_DILIGENCE_PORT` (default 5400).
- **Wiring**: `feature.yaml`, a multi-stage `Dockerfile`, Compose services (`f4-postgres`,
  `f4-db-api`, `f4-backend`, `f4-frontend`), and deterministic Python + Node tests discovered
  by the repository quality gate.

Not yet built (your next branches): the AI-generated Plan -> Act -> Observe -> Adapt
verification-question pack (add an `onboarding.ai` block plus `tool-catalog.yaml`), versioned
evidence-release import, bounded GeoJSON layers, and the richer planning/environmental/strata
and building-order UI.

### Run it locally

```
uv run scripts/dev.py stack up --offline
```

Open the unified home page at <http://localhost:5100> (Feature 4 appears under "Site and
planning") or the feature directly at <http://localhost:5400>. Stop with
`uv run scripts/dev.py stack down`.
