# API-to-UI and interaction contract mapping

## 1. Contract principles

- Feature-owned OpenAPI/JSON examples are the source of truth.
- Same-origin route namespaces are preferred behind the shared edge.
- Frontends call their backend APIs, not database APIs.
- Cross-feature calls use HTTP contracts and bounded fixtures, never Python imports or shared tables.
- Requests propagate `X-Request-ID`, `traceparent`, `X-Agent-Run-ID` and `Idempotency-Key` where
  relevant.
- Errors use `application/problem+json` with safe detail and request ID.
- Valid empty evidence is not an HTTP 500.
- Evidence responses include source/release/effective/freshness/coverage/match metadata.
- Browser responses never expose secrets, database paths, host artifact paths, raw prompts or
  unrestricted upstream payloads.

## 2. External route namespaces

```text
/features/data-platform/              /api/data-platform/v1/
/features/market-intelligence/        /api/market-intelligence/v1/
/features/suburb-analytics/           /api/suburb-analytics/v1/
/features/due-diligence/              /api/due-diligence/v1/
/features/buyer-workspaces/           /api/buyer-workspaces/v1/
/operations/ai-mode/                  /api/ai-mode/v1/
/system/status/                       /api/system/v1/status
```

The current local Feature 1 frontend uses port `5200` and hash routes; shared AI-mode operations use
port `5005/operations/ai-mode/`. The new shell can override links until an edge exposes the stable
same-origin paths.

## 3. Standard collection contract

Recommended response shape:

```json
{
  "items": [],
  "page": {
    "limit": 50,
    "next_cursor": null,
    "has_more": false
  },
  "request_id": "..."
}
```

Do not return unbounded lists. Filters must be explicit and allowlisted.

## 4. Standard evidence contract

```json
{
  "id": "evidence-id",
  "kind": "domain-owned-kind",
  "value": {},
  "evidence": {
    "source_name": "...",
    "source_url": "...",
    "source_record_id": "...",
    "source_release": "...",
    "observed_at": "...",
    "effective_date": "...",
    "coverage_status": "observed",
    "match_method": "...",
    "match_confidence": "high",
    "licence_id": "...",
    "transform_version": "..."
  }
}
```

The shared evidence metadata may be formalised as a domain-neutral contract. The `value` schema stays
feature-owned.

## 5. Problem Details mapping

| HTTP | Meaning | UI behavior |
|---:|---|---|
| 400 | malformed request | general form/request error; normally avoid through client validation |
| 404 | unknown entity | not-found panel with return/search action |
| 409 | version/idempotency/state conflict | show latest state and intentional retry/compare path |
| 422 | invalid domain input | field-level errors; retain entered values |
| 429 | bounded rate/queue limit | show retry guidance and preserve local work |
| 502 | dependency failed | preserve successful/owned data and identify dependency |
| 503 | service not ready/disabled | status/capability explanation; CRUD fallback where possible |
| 504 | dependency/model timeout | partial result or retry, never indefinite spinner |

Example:

```json
{
  "type": "https://propertyscope.invalid/problems/version-conflict",
  "title": "The source definition changed",
  "status": 409,
  "detail": "Reload the latest version before saving again.",
  "instance": "/api/data-platform/v1/sources/SRC-1",
  "request_id": "req_...",
  "errors": [{ "field": "version", "code": "stale" }]
}
```

## 6. Feature 1 mapping

Base: `/api/data-platform/v1`

| UI route/action | Method/path | Success presentation | Empty/failure presentation |
|---|---|---|---|
| Sources list | `GET /sources` | registry table, filters, freshness/licence | no sources + create; problem panel |
| Create source | `POST /sources` | toast + open detail | field errors/version/adapter policy |
| Source detail | `GET /sources/{id}` | metadata, jobs, lineage | 404 return to registry |
| Update source | `PUT /sources/{id}` | updated version/history | 409 reload/compare |
| Delete source | `DELETE /sources/{id}` | removed/archived and return | 409 dependencies → disable/retire guidance |
| Start bounded run | `POST /ingestion-runs` | open requested/queued run | 422 limits; 409 idempotent existing run |
| Runs list | `GET /ingestion-runs` | status/phase/table | no runs + plan action |
| Run detail | `GET /ingestion-runs/{id}` | tasks/counts/quality/artifacts | last durable state + polling error/retry |
| Retry | `POST /ingestion-runs/{id}/retry` | child/existing run link | invalid state/review required |
| Releases list | `GET /dataset-releases` | candidate/accepted/superseded table | no release + source/run guidance |
| Create draft/candidate metadata | `POST /dataset-releases` | open release detail | schema/lineage errors |
| Release detail | `GET /dataset-releases/{id}` | manifest/lineage/quality | 404 return |
| Update draft | `PUT /dataset-releases/{id}` | new version | accepted immutable; 409/422 |
| Delete permitted draft | `DELETE /dataset-releases/{id}` | return to list | accepted/linked conflict |
| Publish candidate | `POST /dataset-releases/{id}/publish` | accepted receipt + predecessor | review/quality/consumer conflict |
| Property search | `GET /properties/search?q=&state=NSW&limit=` | result cards/map/list | valid no-match; supported-footprint guidance |
| Property detail | `GET /properties/{property_ref}` | canonical identity/aliases | unresolved/unknown state |
| Map context | `GET /properties/{property_ref}/map-context` | bounded point/geometry metadata | neutral map/list when tile/geometry unavailable |
| Property coverage | `GET /properties/{property_ref}/coverage` | source/feature matrix | valid unavailable states |
| Start diagnosis | `POST /dataset-releases/{id}/agent-runs` | open shared run | AI disabled/not ready with deterministic fallback |
| Run projection | `GET /agent-runs/{run_id}` | safe feature-specific summary | shared run link/problem state |

### Feature 1 HTMX fragment candidates

```text
GET /features/data-platform/fragments/sources-table
GET /features/data-platform/fragments/runs-table
GET /features/data-platform/fragments/run-status/{id}
GET /features/data-platform/fragments/releases-table
GET /features/data-platform/fragments/property-results?q=...
```

These routes are presentation adapters; they call the canonical JSON backend and render safe HTML.
They must not introduce alternate business rules or database access.

## 7. Feature 2 mapping

Base: `/api/market-intelligence/v1`

| UI route/action | Method/path | Key response expectations |
|---|---|---|
| Market cases | `GET/POST /market-cases` | bounded list/create, versioned user-owned record |
| Case detail/edit/delete | `GET/PUT/DELETE /market-cases/{id}` | selected filters/status/notes and version conflict |
| Property sales | `GET /properties/{property_ref}/sales` | ordered records, date/class/match/source metadata |
| Comparables | `GET /properties/{property_ref}/comparables` | applied filters, stable order, exclusions, sample size |
| Suburb summary | `GET /suburbs/{state}/{locality}/market-summary` | period, sample, deterministic values/method |
| Timeseries | `GET /suburbs/{state}/{locality}/market-timeseries` | bounded points, units, missing values, release |
| AI explanation | `POST /market-cases/{id}/agent-runs` | run ID, selected evidence scope, no valuation |

Empty sale/comparable results use `200` with `items: []` and an evidence/coverage reason. The UI says
“no supported records in this release,” not “property has never sold.”

## 8. Feature 3 mapping

Base: `/api/suburb-analytics/v1`

| UI route/action | Method/path | Key response expectations |
|---|---|---|
| Suburb summary | `GET /suburbs/{state}/{locality}` | factual metrics plus source/coverage |
| Places | `GET /suburbs/{state}/{locality}/places?type=&limit=` | bounded points and attributes |
| Nearby places | `GET /properties/{property_ref}/nearby-places?radius_m=` | method/distance and straight-line label |
| Crime series | `GET /suburbs/{state}/{locality}/crime-series?...` | month, count/rate, denominator, zero/missing, release |
| Crime compare | `GET /crime/compare?...` | validated same period/measure and comparable series |
| Methodology | `GET /crime/methodology` | categories/geographies/denominator/revision/source |
| Area series | `GET /suburbs/{state}/{locality}/area-series?metric=` | bounded selected indicators |
| Comparison CRUD | `GET/POST /suburb-comparisons`; `GET/PUT/DELETE /suburb-comparisons/{id}` | selected localities/period/measure/notes/version |
| AI explanation | `POST /suburb-comparisons/{id}/agent-runs` | evidence-bound neutral trend run |

Reject mixed count/rate/geography/period requests with `422`. A source-recorded zero is represented as
zero with `zero_missing_state=recorded_zero`; a missing month is null/missing and never plotted as
zero.

## 9. Feature 4 mapping

Base: `/api/due-diligence/v1`

| UI route/action | Method/path | Key response expectations |
|---|---|---|
| Constraints | `GET /properties/{property_ref}/constraints` | result state, coverage, date, source, match |
| Layer map | `GET /properties/{property_ref}/layers.geojson?types=` | bounded simplified geometry, legend metadata |
| Building evidence | `GET /properties/{property_ref}/building-evidence` | observation type/date/summary/match/source |
| Strata summary | `GET /strata/{plan_number}` | supported scheme metadata and limitations |
| Review CRUD | `GET/POST /site-reviews`; `GET/PUT/DELETE /site-reviews/{id}` | checklist/questions/disposition/notes/version |
| AI question pack | `POST /site-reviews/{id}/agent-runs` | bounded evidence and no-certification constraints |

UI state derives from `result_state` plus `coverage_status`; it cannot infer “no risk” from an empty
array. GeoJSON responses enforce feature/coordinate/size limits and may return simplified display
geometry only.

## 10. Feature 5 mapping

Base: `/api/buyer-workspaces/v1`

| UI route/action | Method/path | Key response expectations |
|---|---|---|
| Profile CRUD | `GET/POST /buyer-profiles`; `GET/PUT/DELETE /buyer-profiles/{id}` | minimal priorities/notes/status/version |
| Watchlist CRUD | `GET/POST /watchlist-entries`; `GET/PUT/DELETE /watchlist-entries/{id}` | property/ref resolution and user-supplied claims |
| Watchlist planning run | `POST /watchlist-entries/{id}/agent-runs` | evidence questions, no external action |
| Follow-up CRUD | `GET/POST /follow-ups`; `GET/PUT/DELETE /follow-ups/{id}` | stakeholder/action/rationale/due/status/evidence IDs |
| Dossier CRUD | `GET/POST /dossiers`; `GET/PUT/DELETE /dossiers/{id}` | sections/objective/status/run/version/review |
| Comparison | `GET /dossiers/{id}/comparison` | deterministic side-by-side provider projection |
| Start dossier run | `POST /dossiers/{id}/agent-runs` | durable run ID and provider scope |
| Run projection | `GET /dossiers/{id}/agent-runs/{run_id}` | section/provider/phase/review state |
| Human review | `POST /dossiers/{id}/review` | disposition/comment/version/idempotency |
| Question guide | `GET /dossiers/{id}/question-guide?stakeholder=` | bounded deterministic/approved guide |
| Follow-up proposal run | `POST /dossiers/{id}/follow-up-agent-runs` | proposed tasks requiring review |
| Print | `GET /dossiers/{id}/print` | semantic safe HTML, report/evidence version |

Feature 5 must preserve partial provider results. A provider failure is a section state, not
necessarily a failed dossier. Generated task proposals are distinct from persisted tasks.

## 11. Shared AI-mode mapping

Recommended core concepts:

```text
POST /runs                       create bounded run
GET  /runs                       safe run index
GET  /runs/{id}                  run summary
GET  /runs/{id}/events           durable events with cursor
GET  /runs/{id}/reviews          review requests/dispositions
POST /runs/{id}/reviews/{id}     approve/reject/request change
POST /runs/{id}/cancel           idempotent cancellation
```

Exact existing AI-mode contracts should remain authoritative. Feature frontends normally create a run
through their own backend, which validates the objective/entity and calls AI-mode. They do not expose
an unrestricted “prompt box.”

### Agent event rendering

| Event category | User label | Technical detail disclosure |
|---|---|---|
| plan | Planned evidence retrieval | plan version/model/profile |
| tool requested | Retrieving market evidence | tool name/version/arguments redacted/bounded |
| tool completed | 12 sale observations retrieved | duration/result count/evidence IDs |
| observation | Evidence gap found | provider/reason/retryability |
| adaptation | Switched to prior accepted period | reason and bounded next step |
| draft | Draft section generated | prompt/model version and token/size metadata |
| review required | Human approval required | exact proposed mutation/output |
| terminal | Completed/partial/failed/cancelled | durable summary/request ID |

## 12. Release 1 grounded-answer contract

```json
{
  "status": "partially_grounded",
  "answer": "...",
  "structured_evidence": [
    { "evidence_id": "...", "feature": "market-intelligence", "field_refs": ["..."] }
  ],
  "citations": [
    {
      "document_id": "...",
      "chunk_id": "...",
      "title": "...",
      "publisher": "...",
      "effective_date": "...",
      "source_url": "..."
    }
  ],
  "unassessed": ["..."],
  "conflicts": [],
  "versions": {
    "model_profile": "...",
    "prompt_set": "...",
    "retrieval": "...",
    "corpus": "..."
  },
  "run_id": "..."
}
```

The UI can open each structured evidence item and document chunk. Citation text is escaped and
bounded; retrieved passages cannot render active HTML/instructions.

## 13. Release 2 capability contract

A shared capability manifest drives controls:

```json
{
  "release": "release-2",
  "deployment_mode": "cloud",
  "capabilities": {
    "ai_mode": { "enabled": true },
    "mcp": { "enabled": false, "reason": "disabled_in_cloud" },
    "rag": { "enabled": false, "reason": "disabled_in_cloud" },
    "multi_agent": { "enabled": false, "reason": "disabled_in_cloud" }
  }
}
```

Feature pages must not discover this by intentionally calling a disabled endpoint and waiting for an
error. Render the appropriate mode proactively and still handle runtime failure.

## 14. Idempotency and review

Use `Idempotency-Key` for:

- starting ingestion/report/AI runs;
- retry/reprocess requests;
- candidate publication;
- protected report save; and
- approved follow-up task batch creation.

A review request captures the proposed operation hash/version. Approval of an obsolete proposal
returns `409` and requires regeneration/review; it must not execute against changed evidence.

## 15. Security boundaries

- Backend allowlists tool/service URLs; browser cannot supply arbitrary targets.
- Cross-feature clients validate response schema and size.
- Model/tool output is treated as untrusted until schema-validated.
- Retrieved documents are untrusted context and cannot alter permissions.
- HTML is escaped; source URLs are validated and use safe link attributes.
- Internal tokens/database credentials never reach browser or other feature containers.
- Logs/redacted run views avoid objectives/free text where privacy risk is unnecessary.
- Feature 5 never sends external communications or stores identity/finance documents.

## 16. Contract test fixture set

Each provider publishes fixtures for:

```text
success.json
empty.json
partial.json
not-found.problem.json
validation.problem.json
version-conflict.problem.json
dependency-failed.problem.json
service-unavailable.problem.json
```

Evidence providers also publish `stale`, `conflicting`, `source_failed` and `unknown/not_covered`
examples where applicable. Consumers test against these fixtures and provider workflows trigger the
relevant consumer contract tests.

## 17. API/UI definition of done

- every implemented screen is mapped to a versioned endpoint/fragment;
- list endpoints are bounded and filterable;
- empty evidence is schema-valid;
- request IDs appear in recoverable problem UI;
- version/idempotency conflicts are intentional flows;
- evidence metadata is visible and preserved into reports;
- protected mutations require a separate review contract;
- capability flags drive release-specific controls;
- cross-feature partial failure is tested; and
- OpenAPI, examples, server behavior, UI mapping and tests agree.
