# Feature 1 redesign — Data Platform, Provenance and Property Discovery

## 1. Recommendation

Feature 1 should **not** be rewritten from scratch. Its backend/database/runner architecture and
contracts are the strongest implemented part of the repository. Redesign the experience around
those seams and refactor the browser code incrementally.

The feature must succeed as two related but distinct workspaces:

1. **Property Discovery** — buyer-facing identity, address search, map/list context and source
   coverage; and
2. **Data Operations** — operator-facing source/job/run/release/quality/artifact and recovery
   workflows.

They share canonical property/release vocabulary and a Feature 1 navigation context. They should not
be presented as one giant dashboard with every technical field visible at once.

## 2. Existing implementation to retain

### Backend and service seams

- `student-1/backend/src/propertyscope_data_platform/`
- `student-1/database/src/propertyscope_data_store/`
- backend, database API, loader and runner container targets;
- PostgreSQL 16/PostGIS persistence;
- artifact storage volume and bounded adapters;
- source/adapter/job configuration;
- release manifests, hashes, validation and publication concepts;
- AI-mode client/tool integration;
- readiness/health endpoints and internal tokens;
- OpenAPI contract and JSON Schemas; and
- deterministic tests and fixtures.

### Current browser foundations worth retaining

- `core.js` request wrapper, timeouts, request IDs and Problem Details handling;
- status/action helper functions;
- adaptive run polling behavior;
- semantic dialogs/forms;
- routes for overview, sources, jobs, runs, releases, quality, artifacts, coverage, properties and
  AI; and
- explicit non-government disclaimer.

### Main browser problem

`app.js` is a 1,351-line module that owns API calls, routing, DOM primitives, forms, polling, tables,
rendering and feature workflows. The issue is not the absence of a framework; it is change coupling.
A source-form adjustment should not require navigating the same file that renders property maps,
run timelines and AI diagnosis.

## 3. Product boundary

### Purpose

Own the data control plane, accepted release catalogue, canonical `property_ref`, bounded NSW
property discovery and evidence coverage.

### In scope

- source-definition CRUD;
- job-definition CRUD;
- browser-launched full-refresh/cached-reprocess requests;
- run/task history, validation, artifacts, checksums and failure recovery;
- candidate/accepted/superseded release lifecycle;
- review-gated publish/retry/reprocess actions;
- canonical property search/detail/map context;
- per-property source/feature coverage;
- source freshness, attribution, licence and match-confidence UI; and
- AI-assisted diagnosis/recovery planning with human review.

### Out of scope

- market valuation or forecasting;
- general-purpose warehouse SQL for other features;
- ownership of sale/crime/site/buyer semantics;
- direct editing of upstream government records by ordinary product users;
- arbitrary shell execution or arbitrary URL ingestion;
- automatic publication based only on a model response; and
- statewide raw geometry/source payloads in the browser.

## 4. Personas and task split

| Persona | Main tasks | Default workspace |
|---|---|---|
| Buyer/researcher | Find address, confirm identity, inspect coverage | Property Discovery |
| Data operator | Configure source/job, run/retry, inspect quality, publish | Data Operations |
| Feature owner/consumer | Check accepted release and publication evidence | Releases/Coverage |
| Marker/demonstrator | See CRUD, failure, agent workflow and property value | Guided overview |

The shared shell should deep-link to Property Discovery and Data Operations separately, even though
they are served by the same Feature 1 frontend.

## 5. Information architecture

```text
Feature 1 · Data platform
├── Overview
├── Sources
│   ├── Source list
│   └── Source detail/edit/history
├── Jobs
│   ├── Job list
│   ├── Job detail/edit
│   └── Plan run
├── Runs
│   ├── Run list
│   └── Run detail / tasks / quality / artifacts / lineage
├── Releases
│   ├── Release list
│   └── Candidate review / publish / reject / predecessor compare
├── Evidence
│   ├── Quality rules/results
│   ├── Artifact registry
│   └── Coverage matrix
├── Property discovery
│   ├── Search/map/list
│   └── Canonical property detail / identifiers / coverage
└── AI diagnosis
    ├── Objective/context form
    └── shared agent-run detail link
```

The prototype separates `discovery` (operator view of the discovery dataset) from shared
`explore/property` (buyer-oriented product journey). The running Feature 1 frontend can initially
serve both while maintaining different information density.

## 6. Screen specification

### 6.1 Data operations overview

**Purpose:** tell an operator what is accepted, what is running/failing and what needs action.

**Above the fold:**

- accepted release count/current dates;
- active and failed run summary;
- candidate releases awaiting review;
- source coverage/freshness warnings;
- quick actions: plan run, review candidate, open failed run;
- explicit distinction between service readiness and data readiness.

**Do not:** show raw schema/configuration or every count as equal KPI tiles.

Prototype: `../prototype/propertyscope-v2/standalone.html#/data-overview`.

### 6.2 Source registry

**Collection:** publisher, domain, cadence, enabled state, last accepted release, freshness and
licence/redistribution policy. Search/filter by source/domain/status.

**Create/edit:** name, publisher, source URL, adapter key, cadence, licence ID, redistribution
policy, owner contact, enabled, notes and version.

**Detail:** configuration summary, jobs using the source, run/release history, attribution preview,
health/terms notes and danger zone.

**Delete rule:** allow deletion only for unused draft/local definitions; otherwise retire/disable or
return a conflict explaining dependencies.

Prototype: `10-sources.png`, `11-source-detail.png`.

### 6.3 Ingestion jobs

**Collection:** job/profile, dataset, source, strategy, target feature, status, last outcome and safe
limits.

**Detail:** immutable identity/profile key, editable bounded parameters, target publication contract,
source dependency, expected schema/quality rules and recent runs.

**Plan run:** choose approved mode, bounded parameters and review note. Show estimated footprint and
whether acquisition uses a live registered source or cached fixture. The browser never accepts an
arbitrary command/path/URL.

Prototype: `12-jobs.png`, `13-job-detail.png`, `14-run-plan.png`.

### 6.4 Run history and detail

**Collection:** run ID, job, mode, status, phase, start/duration, accepted/rejected rows, request ID.
Active runs poll adaptively; terminal runs stop polling.

**Detail:**

- terminal/active status and meaningful phase;
- immutable request/job/mode/profile metadata;
- Plan → Act → Observe → Adapt timeline where AI applies;
- task/stage timeline;
- row counts and validation summary;
- quality failures with observed/expected/sample;
- artifacts with safe names/hash/size/retention—not host paths;
- candidate release lineage;
- cancel/resume/retry/reprocess/diagnose actions based on state; and
- preserved accepted predecessor.

Prototype: `15-runs.png`, `16-run-detail.png`.

### 6.5 Release catalogue and review

**Collection:** dataset, version, target feature, lifecycle state, records, coverage, checksum,
created/accepted dates and predecessor.

**Review:** compare candidate to current accepted release across schema, record count, checksum,
coverage, quality and consumer acceptance. Review controls capture comment/disposition. Publish is
idempotent and protected; reject does not delete evidence.

**Deletion:** drafts/candidates may be deleted under a documented rule. Accepted history is
superseded, never erased in ordinary UI.

Prototype: `17-releases.png`, `18-release-review.png`.

### 6.6 Quality and artifact evidence

Quality filters by release/run/rule/dimension/severity/status. Artifact registry exposes kind,
bounded logical key, hash, size, retention and lineage. Selecting an item reveals technical metadata
without exposing storage paths or unrestricted downloads.

Prototype: `19-quality.png`, `20-artifacts.png`.

### 6.7 Coverage matrix

Coverage is not a single percentage. Display dataset/source, target feature, geography/time window,
accepted release, freshness, state and limitation. A detail panel explains the exact meaning of
observed/partial/unavailable/stale/source-failed/not-applicable.

Prototype: `21-coverage.png`.

### 6.8 Property discovery

**Search:** query by address or PropertyScope reference; state fixed/bounded to NSW; result limit
explicit. Result cards show canonical address, reference, locality, match state, source count and
freshness.

**Map/list:** local points/overlays, synchronized selection and a list/table fallback. Live base tiles
are optional.

**Property detail:** canonical display address, opaque `property_ref`, coordinates, source identifiers,
aliases/resolution state and a feature/source coverage matrix. Cross-feature links pass only the
opaque reference.

Prototype: `22-discovery.png`, `23-property-detail.png`; buyer-oriented variants are
`02-explore.png` and `03-property.png`.

### 6.9 AI diagnosis

The form chooses a supported entity (run/release/source/job), bounded objective and context options.
It previews the evidence types that will be exposed. The action creates a durable AI-mode run and
links to shared run operations.

Example objective:

> Assess why this crime-series candidate failed validation, compare it with the accepted predecessor,
> propose a bounded recovery plan and queue any retry/publication mutation for human review.

Prototype: `24-ai-diagnosis.png`, shared `05-agent-runs.png` and `06-agent-run.png`.

## 7. Proposed frontend module structure

Keep plain HTML/HTMX/JavaScript, but split by responsibility:

```text
student-1/frontend/
├── index.html
├── styles.css                  # shared imports + Feature 1 composition
├── app.js                      # bootstrap only
├── core/
│   ├── api.js                  # request IDs, timeout, Problem Details
│   ├── router.js               # hash/path routing and navigation state
│   ├── dom.js                  # safe element helpers
│   ├── formats.js              # dates/counts/IDs/status labels
│   ├── state.js                # small client state/store
│   └── polling.js              # adaptive polling and generation guards
├── components/
│   ├── badges.js
│   ├── tables.js
│   ├── forms.js
│   ├── dialogs.js
│   ├── evidence.js
│   ├── run-timeline.js
│   ├── map-frame.js
│   └── empty-error-loading.js
├── routes/
│   ├── overview.js
│   ├── sources.js
│   ├── source-detail.js
│   ├── jobs.js
│   ├── job-detail.js
│   ├── run-plan.js
│   ├── runs.js
│   ├── run-detail.js
│   ├── releases.js
│   ├── release-review.js
│   ├── quality.js
│   ├── artifacts.js
│   ├── coverage.js
│   ├── discovery.js
│   ├── property-detail.js
│   └── ai-diagnosis.js
└── tests/
    ├── core.test.mjs
    ├── polling.test.mjs
    ├── forms.test.mjs
    └── routes-smoke.test.mjs
```

### HTMX migration option

For list/detail CRUD, render server-owned fragments:

```text
GET /features/data-platform/sources             full route
GET /features/data-platform/fragments/sources   table body/panel
POST /api/data-platform/v1/sources               JSON API remains canonical
```

A thin frontend Flask service may call the backend API and render templates; it still must not access
the database directly. Use small JavaScript islands for map interaction, polling, technical JSON
editors and dialogs. Do not create two competing business APIs.

## 8. API-to-screen mapping

All paths below are relative to `/api/data-platform/v1`.

| Screen/action | Endpoint(s) |
|---|---|
| Source list/create | `GET/POST /sources` |
| Source detail/edit/delete | `GET/PUT/DELETE /sources/{id}` |
| Job list/create | Existing/proposed job-definition endpoints in Feature 1 contract |
| Job detail/edit/delete | Existing/proposed job-definition detail endpoints |
| Plan/start run | `POST /ingestion-runs` |
| Run list/detail | `GET /ingestion-runs`, `GET /ingestion-runs/{id}` |
| Retry/reprocess | `POST /ingestion-runs/{id}/retry` and bounded action endpoints |
| Release list/create | `GET/POST /dataset-releases` |
| Release detail/edit/delete | `GET/PUT/DELETE /dataset-releases/{id}` |
| Publish candidate | `POST /dataset-releases/{id}/publish` |
| Property search | `GET /properties/search?q=&state=NSW&limit=` |
| Property detail | `GET /properties/{property_ref}` |
| Map context | `GET /properties/{property_ref}/map-context` |
| Property coverage | `GET /properties/{property_ref}/coverage` |
| Start release diagnosis | `POST /dataset-releases/{id}/agent-runs` |
| Run projection | `GET /agent-runs/{run_id}` |

Where the implementation has additional job/quality/artifact endpoints, keep the published OpenAPI
as the source of truth and update this mapping rather than inventing frontend-only paths.

## 9. CRUD design

### Source definition

- **Create:** local/configured source with allowed adapter and safe URL policy.
- **Read:** collection/detail/history.
- **Update:** metadata, cadence, enabled state, notes; optimistic version check.
- **Delete:** only when permitted; otherwise return `409` and offer retire/disable.

### Job definition

- **Create:** approved source/adapter/import profile and bounded limits.
- **Read:** collection/detail/run history.
- **Update:** safe parameters/status/version.
- **Delete:** draft/unused only or archive; preserve run lineage.

### Dataset release

- **Create:** candidate metadata normally produced by a run, plus bounded admin fixture flow if
  required for assessed CRUD.
- **Read:** collection/detail/lineage.
- **Update:** draft/review metadata only.
- **Delete:** permitted draft/candidate under policy.
- **Publish:** separate protected state transition, not ordinary update.

### Run evidence

Runs are immutable operational history rather than arbitrary CRUD records. The assignment's CRUD is
satisfied through source/job/release aggregates; retry/cancel/resume are domain actions with audit
history.

## 10. AI workflow

### Tool set

- `property.search.v1`
- `property.inspect.v1`
- `data.sources.v1`
- `data.runs.v1`
- `data.release_inspect.v1`
- `data.coverage.v1`
- optional review-gated `data.run_retry.v1`
- optional review-gated `data.release_publish.v1`

### Plan → Act → Observe → Adapt example

```mermaid
sequenceDiagram
  participant U as Operator
  participant F as Feature 1 API
  participant A as AI-mode
  participant L as Approved LLM
  participant T as Feature 1 tools
  participant H as Human reviewer

  U->>F: Diagnose failed candidate release
  F->>A: Create bounded run objective/context
  A->>L: Plan using tool catalogue and limits
  L-->>A: Plan: inspect release, run, predecessor, coverage
  A->>T: Read release/run/quality evidence
  T-->>A: Structured bounded observations
  A->>L: Observe evidence and draft recovery plan
  L-->>A: Missing month; propose cached reprocess
  A->>T: Optional protected retry proposal
  T-->>A: Review required
  A-->>F: Awaiting human review + evidence links
  F-->>U: Show proposal and exact effect
  U->>H: Approve/reject with comment
  H->>A: Review disposition
  A->>T: Execute idempotent reviewed action if approved
  A-->>F: Terminal outcome and child run ID
```

### Prompt/output constraints

- no arbitrary URL/path/command;
- no publish/retry without explicit protected tool review;
- quote evidence IDs and versions rather than reproducing large payloads;
- differentiate accepted from candidate release;
- state missing evidence and source failure;
- no claims about market/site/crime meaning beyond Feature 1's data quality/coverage boundary;
- bounded steps, calls, response size and time; and
- durable terminal state even on cancellation/failure.

## 11. Release progression

### Release 0

- polished source/job/release CRUD;
- deterministic runs, quality, artifact and property discovery;
- direct AI-mode diagnosis through Ollama/approved LLM;
- genuine Plan → Act → Observe → Adapt trace;
- review gate for state-changing recovery/publication;
- all direct CRUD works without Ollama; and
- screenshots/tests/Compose/workflow evidence.

### Release 1

Feature 1 contributes:

- MCP tools for property identity, source/release/coverage evidence;
- RAG corpus for team-authored source methodology, data dictionaries, coverage and limitation docs;
- grounded answers combining structured current release data with explanatory documents;
- exact citation resolution, prompt-injection resistance and stale/superseded filtering; and
- CRUD/operations behavior when MCP/RAG are disabled.

Structured numeric/property facts come from tools. RAG documents explain meaning and method; they do
not silently override accepted structured records.

### Release 2 local

- planner can decompose recovery/report data questions;
- worker executes read tools and drafts diagnosis;
- reviewer checks citation coverage, accepted/candidate confusion, unsafe mutation and unassessed
  criteria;
- human approves protected actions; and
- pre/post testing evidence is captured.

### Release 2 cloud

- Feature 1 CRUD, property discovery, deterministic quality/release evidence and basic AI-mode remain
  available;
- MCP, RAG and multi-agent controls are hidden/disabled according to capability configuration;
- use curated fixture/releases, not massive statewide imports on a small cloud service; and
- cloud mode must not promise local-only functionality.

## 12. Data and evidence model

### Canonical identity

`property_ref` is a platform-generated opaque UUID/string. G-NAF PIDs are versioned external
evidence, not a permanent legal parcel/title identity. Other features store the opaque reference and
validate it over HTTP.

### Evidence envelope

Every property/release observation shown in the UI should include or link to:

```json
{
  "source_name": "...",
  "source_url": "...",
  "source_record_id": "...",
  "source_release": "...",
  "observed_at": "...",
  "effective_date": "...",
  "coverage_status": "observed|partial|unavailable|stale|source_failed|not_applicable",
  "match_method": "...",
  "match_confidence": "exact|high|medium|low|unmatched",
  "licence_id": "...",
  "transform_version": "..."
}
```

The UI may summarise it, but a detail/provenance action must expose the complete safe metadata.

## 13. Error and recovery design

| Condition | Response/UI |
|---|---|
| Unknown source/job/release/property | `404` with request ID and return/search action |
| Version conflict | `409`; compare latest record and retry edit intentionally |
| Invalid bounded input | `422`; field-level messages |
| Consumer/source dependency failed | `502`; preserve local record/evidence and show dependency |
| Service not ready | `503`; direct navigation/status guidance |
| Accepted release exists, candidate fails | Keep accepted data prominently live; show failed candidate separately |
| Artifact missing/expired | Evidence state indicates retention outcome; run/release remains |
| AI unavailable | Disable diagnosis, keep all deterministic operations |
| Poll request fails | Back off, preserve last durable state, allow manual refresh |
| Cancel/retry races | Idempotency/version conflict with child/terminal state link |

## 14. Accessibility and responsive requirements

- source/job/release forms have persistent labels and error associations;
- dialogs trap/return focus correctly;
- data tables have captions/headers and accessible row actions;
- run phase changes use a polite live region without announcing elapsed time every second;
- map results have a list/table alternative;
- status uses icon/text, not colour only;
- technical IDs are selectable/readable;
- mobile uses list → detail rather than compressed multi-pane layouts;
- destructive/publish actions require clear text and review context; and
- all operations are keyboard-complete.

## 15. Testing strategy

### Unit

- status/action mapping;
- parameter and year-range validation;
- source/job/release form normalisation;
- coverage/lineage transformation;
- polling delay/backoff/generation guards;
- evidence-state mapping; and
- safe URL/search forwarding.

### Contract/component

- every OpenAPI response fixture renders success, empty and problem states;
- source/job/release CRUD including version conflict and deletion policy;
- failed candidate never replaces accepted release;
- publish/retry idempotency;
- property search and coverage;
- protected AI tool review behavior; and
- no raw paths/secrets/prompts in browser responses.

### Browser

- route smoke test for all Feature 1 routes;
- keyboard CRUD flows;
- responsive screenshots;
- run polling lifecycle;
- release comparison/review;
- property search/map/list fallback;
- Ollama-unavailable state; and
- partial/error states with request IDs.

### Architecture

- frontend calls backend only;
- backend calls database API rather than opening DB directly;
- no Feature 2–5 package imports;
- bounded artifact volume access by role;
- no database credentials in frontend/backend where not required; and
- Compose/contract generation remains valid.

## 16. Implementation sequence

1. Adopt shared tokens and keep current routes/API behavior unchanged.
2. Extract API/router/format/polling modules with existing tests still green.
3. Extract common components and dialogs.
4. Move overview/sources/jobs into route modules.
5. Move runs/releases and add focused route tests.
6. Move evidence/coverage/property routes.
7. Rebuild the overview and detail layouts to match the prototype.
8. Add server-rendered HTMX fragments only where they simplify forms/tables; do not perform a
   simultaneous framework rewrite.
9. Link AI diagnosis to the shared run evidence UI with originating entity context.
10. Capture assessment screenshots and a deterministic failed-release recovery trace.

## 17. Definition of done

Feature 1 is full-mark ready when:

- source, job and permitted release records have visible create/read/update/delete paths;
- every production table has deterministic seed/migration evidence per project interpretation;
- a failed candidate release cannot displace the accepted predecessor;
- the operator can diagnose, review and execute a bounded recovery action;
- property search resolves a canonical candidate and exposes match/source/coverage metadata;
- ordinary operation works with Ollama stopped;
- AI run evidence is durable and understandable;
- maps/tables/forms are accessible and mobile-usable;
- frontend/backend/database boundaries remain enforced;
- API/contract/core/browser/architecture tests pass; and
- the video can demonstrate the complete Feature 1 story in approximately seventy seconds.
