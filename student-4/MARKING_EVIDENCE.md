# Feature 4 marking evidence

Site, Planning and Building Due Diligence — Michael White (Student 4, 24846267).

This document maps each assessed Release 0 requirement to where it is satisfied in the code and how
to demonstrate it. The approved boundary is in
[`docs/architecture/registered-feature-scope.md`](../docs/architecture/registered-feature-scope.md);
ownership and run instructions are in [`README.md`](README.md).

## Assessed requirements → evidence

| Requirement | Where it is satisfied | How to demonstrate |
| --- | --- | --- |
| Frontend microservice | `student-4/frontend/` served by `f4-frontend` (nginx) on port 5400; adopts the shared design system and shell. | Open <http://localhost:5100> → "Site and planning", or <http://localhost:5400>. |
| Backend/API microservice | `student-4/backend/src/propertyscope_due_diligence/` (`f4-backend`, Flask/Gunicorn) exposing `/api/due-diligence/v1` and `/health/{live,ready}`. | `curl http://localhost:5400/api/due-diligence/v1/site-reviews`. |
| Database microservice | `student-4/database/src/propertyscope_due_diligence_store/` (`f4-db-api` + `f4-postgres`, PostGIS), sole PostgreSQL credential owner. | `docker compose ... exec f4-postgres psql -U due_diligence -d due_diligence -c "\dt due_diligence.*"`. |
| Visible CRUD | Create dialog, edit dialog, delete confirmation and interactive checklist in `frontend/app.js`; `POST/GET/PUT/DELETE /site-reviews` in `backend/.../api.py`. | Create a review (verified-property search), edit it, toggle checklist items, delete it. |
| ≥ 10 deterministic records per table | Migrations `database/.../sql/002_seed.sql` and `003_richer_evidence.sql`: `site_review` = 10, `constraint_observation` = 70, `building_observation` = 50. | `psql -c "SELECT count(*) FROM due_diligence.site_review;"` (and the other two tables). |
| Verified property selection | Backend `Feature1Client.search`/`coordinates` + `GET /properties/search`; frontend property picker in the create dialog. Feature 1 is validated over HTTP with no shared database access. | In the create dialog, search "11 Example Street Sydney" and pick a verified result. |
| Source-attributed planning/environmental evidence | `constraint_observation` (zoning, heritage, floor-space ratio, building height, flood, bushfire) with source name/URL, observed value, match method and confidence. | Open a review → "Planning & environmental constraints". |
| Strata / building-order / tribunal evidence | `building_observation` (strata, building order, undertaking, tribunal) with reference code, source, match method and confidence. | Open a review → "Strata & building records". |
| Explicit evidence states | `confirmed`, `partial_coverage`, `non_intersection`, `unavailable` rendered as shared evidence badges (`evidenceBadgeClass` in `frontend/app.js`). | Different reviews show all four badge states. |
| Environmental map layers (bounded GeoJSON) | `backend/.../map_layers.py` builds a property point + flood/bushfire polygons; `GET /site-reviews/<id>/map`; frontend uses the shared `mapping` module. | Open a review → "Environmental map". |
| Editable checklist / notes / disposition / status | Checklist checkboxes persist via `PUT`; notes/disposition/status editable in the edit dialog. | Toggle a checklist item; edit disposition/status/notes. |
| Interact with the approved LLM (shared AI-mode) | `AiModeClient` + `/assistant/turns` create a bounded agent run; `tool-catalog.yaml` exposes two read-only tools mounted into shared AI-mode. Never selects a model. | See "AI evidence" below. |
| Bounded Plan → Act → Observe → Adapt | The assistant objective + `tool_allowlist` + `limits` (`max_iterations`, `max_tool_calls`, `time_budget_ms`) in `assistant_turn`. | Watch a run progress `queued → adapting → succeeded`. |
| Works when the model provider is unavailable | Direct CRUD, evidence and map require no AI credential; the assistant degrades gracefully. | Run `stack up --offline`; CRUD/evidence/map work, "Generate with AI" reports the provider is unavailable. |
| Health and readiness | `/health/live` (process) and `/health/ready` (checks the feature database API) via shared `project_readiness`. | `curl http://localhost:5400/health/ready`. |
| Integration (repo, Compose, home page, visual system) | `feature.yaml` manifest; `f4-*` Compose services; shell registry entry; shared design-system CSS. | Feature 4 appears "Available now" on the home page with shared styling. |
| Own CI/CD workflow | `.github/workflows/student-4.yml` runs lint, validators, mypy, tests + coverage, browser checks and a container smoke on every `student-4/**` change. | Triggered automatically on pull requests touching Feature 4. |
| Tests | `student-4/tests/` (Python API/DB/client/map/migration suites) and `tests/frontend/core.test.mjs`; discovered by the canonical quality gate. | `uv run python scripts/check.py`. |

## AI evidence (bounded Plan → Act → Observe → Adapt)

Verified live against the Gemini development profile. The assistant created an agent run, the model
executed the **Plan → Act → Observe → Adapt** loop and called both allowlisted Feature 4 tools
(`duediligence.review.inspect.v1` and `duediligence.evidence.summary.v1`), and returned a
professional-verification question pack grounded in the property's real evidence states. Example
generated items for a Sydney review:

- *(Unavailable)* "Can a qualified bushfire consultant verify whether Vegetation Category 1 applies
  to the parcel and what BAL requirements apply, given the unavailable bushfire mapping state?"
- *(Partial Coverage)* "Can a building certifier review the maximum building-height standard
  (observed 9.5 m) to verify compliance against approved plans?"
- *(Confirmed)* "Can a certifier or legal professional review the active building orders and floor
  space ratio (FSR 0.5:1) to confirm legal compliance?"

The generated pack is saved to the review's `verification_questions`. The workflow does not certify
compliance, safety or legal suitability and does not give legal advice.

## Suggested screenshots for the report / video

1. Home page showing "Site and planning" available under the shared shell.
2. Site-review list with the topbar filter.
3. Create dialog with the verified-property search results.
4. Detail view: evidence-state badges across planning/environmental and strata/building sections.
5. The interactive flood/bushfire map.
6. "Generate with AI" producing the question pack (queued → adapting → succeeded).
7. `uv run python scripts/check.py` passing.

## Marking alignment

The implementation evidences the Release 0 criteria for three integrated microservices, Docker
Compose, working CRUD with ≥ 10 deterministic records per table, shared AI-mode integration, the
bounded Plan → Act → Observe → Adapt loop with prompt/tool context, deterministic offline behaviour,
the unified home page and common visual system, per-feature CI, and local tests. The one open
coordination item is evidence sourcing (see the design decision in `README.md`): Feature 4 seeds its
own attributed evidence because Feature 1 does not currently publish planning, environmental, strata
or building products.
