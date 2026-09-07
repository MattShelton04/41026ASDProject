# Current-state map and source-of-truth reconciliation

## Baseline and method

Input: `41026ASDProject-main(1).zip`, SHA-256 `d46612e3795da287bd48d40cfbf1fd20e23f22ed9441605c3e74f1165ba26ca8`.
The archive contained no usable Git history. It was extracted without editing, copied to a sibling working repository and committed as `86b2ac8e69f31f39cf6ad4c5061e7e2e5fb8efef`. The initial working tree was clean. The supplied baseline passed 195 frontend Node tests and the available architecture/style checks; the canonical Python gate was blocked by the environment before redesign work.

The map combines source inspection with live Chromium DOM/control inventories. `AGENTS.md`, root and feature READMEs, contribution instructions, shared-platform architecture, deployment projection, current CSS, UI audit code and assistant contracts were read. Source, contracts and observed behavior override historical prototypes. [ROUTE_CONTROL_INVENTORY.md](ROUTE_CONTROL_INVENTORY.md) records the exact route examples, baseline and final controls observed, and screenshot links. Dynamic identifiers create route families rather than an enumerable list of all possible screens.

## Actual application structure

| Area | Source route families | Primary tasks and controls |
|---|---|---|
| Shared | `#home`, `#features`, `#system-status`, `#evidence`, `#release-roadmap`, `#assistant` | Property-search handoff, research directory, current service/data status, source/history links, capability roadmap and scoped assistant. Global and local navigation are separate. |
| Property data | `#overview`, `#data-products`, `#sources`, `#jobs`, `#runs`, `#releases`, `#quality`, `#artifacts`, `#coverage`, `#properties`, `#assistant`, `#ai` | List/detail navigation, search, filters and pagination; source form/list/detail HTMX; job previews and confirmed commands; run phases, quality evidence, artifacts and release review; property records; chat and bounded AI review. |
| Sales & market | `#market-cases` | Select a case, create/edit/delete through native dialogs, view eligible/excluded sales and yearly volume, inspect source releases and ask a case-scoped question. Selected case is local state, not an invented ID route. |
| Suburb context | `#explore`, `#trends`, `#published`, `#comparisons`, `#assistant` | Locality search, LGA/amenity/sort filters, map display options, bookmarks, details, two-locality crime comparisons, dates/measure selection, saved comparisons and scoped assistant. |
| Site & planning | `#site-reviews`, `#site-reviews/:id` | Search, create/edit/delete reviews; source-attributed constraint evidence; map/fallback; checklist and notes; bounded question generation with saved results. |
| Buyer workspace | `#buyer-cases`, `#buyer-cases/:id` | Budget/suburb/preferences, shortlist, tasks, notes, evidence refresh and summary workflow. Section jumps do not replace the router hash. |
| AI activity | `/operations/ai-mode/` plus validated query context | Filter/list/select runs, inspect steps/evidence/events/reports, refresh/poll, review controls and verified return navigation. |

All five features are enabled in `deployment/enabled-features.v1.json`. This is a deployment availability claim, **not** a guarantee that a backend, dataset or model is healthy. Each frontend remains independently deployable. The edge prefixes are `/features/data-platform/`, `/features/market-intelligence/`, `/features/suburb-analytics/`, `/features/due-diligence/` and `/features/buyer-workspaces/`.

### Important route details

`#release-roadmap` is the real shared roadmap route; `#roadmap` falls back to home. Artifact detail is keyed by its ingestion run, not by the artifact row ID. Feature 1 AI detail uses an agent-run ID, while a release-prefill route is `#ai/release:<release-id>?goal=...`. A buyer summary ID belongs to the buyer service and must not be used as an AI-mode run ID. The property search rejects overly broad short terms; the final valid search example is `11 Example Street`, not an assumed-valid `Sydney` query.

## Baseline state/control findings

The baseline already had explicit loading, error, validation, dirty-form, confirmation and durable-run concepts. The redesign did not invent those capabilities. The issue was inconsistent composition and incomplete interaction resilience: raw IDs competed with titles, metadata was small, repeated cards nested unnecessarily, and related controls had different geometry. Research and operational contexts had little density distinction. Mobile navigation and feature-specific page structures behaved differently.

Browser/self-review findings included a pagination container borrowing dialog negative margins, optional storage access throwing in the activity view under denied storage, changing case selection retaining old evidence, and required comparison fields interfering with Cancel. The shared assistant rerender/polling surface needed stronger draft, disclosure, cancellation and stale-response handling. Some discovered failures were profile-specific rather than product defects: opaque-origin HTMX errors and absent WebGL are recorded separately.

## Fixture support: what exists and what was added

The canonical `scripts/ui_fixtures.py` catalogue provides eight scenarios: populated, empty, slow, error, partial, long-content, large and validation-error. It contains rich shared/Feature 1/AI-mode JSON responses and separate Flask-rendered source fragments. The existing cross-feature smoke primarily checks empty/unavailable API behavior; that is not populated workflow coverage for Features 2–5.

This mission adds a **browser-only**, isolated adapter and explicit synthetic seed for the real Feature 2–5 endpoint shapes. It supports in-memory CRUD, version conflicts, validation rejection, source evidence and bounded assistant runs. It does not become a production endpoint or a replacement backend. Unknown API paths fail with 404. External requests are blocked in this test harness, not in application code.

| Scenario | Meaning in the new browser harness | Important boundary |
|---|---|---|
| Populated | Canonical F1 data plus synthetic cases, reviews, suburb observations and buyer records | Synthetic evidence is labeled; not live property data. |
| Empty | No collection records; detail requests may correctly return 404 | “Empty” does not make an existing detail entity magically exist. |
| Slow | API responses are genuinely held pending, then released | Loading screenshots capture actual pending requests, not a mocked skeleton screenshot. |
| Error | Known APIs return deterministic 503 responses | Those expected network failures are retained, not counted as healthy responses. |
| Partial | Incomplete evidence and missing observations, including a null crime point | Not every route consumes partial data; a route/scenario capture is not a distinct business-state assertion. |
| Long-content | Long names, addresses and notes where the public shape permits them | Tests wrapping and disclosure, not permission to exceed server validation limits. |
| Large | Repeated deterministic records, including 100 feature collections | Rendering stress, not a production latency or database benchmark. |
| Validation-error | Safe mutation rejection with 422 and retained input | Requires an interaction; passive page capture alone cannot validate recovery. |
| AI-specific | Guide outage, provider rejection, failed/review-required/poll-outage/no-evidence states | Recorded synthetic states; no model or private reasoning. |

## Stale-document discrepancies

“Only Feature 1 is available” no longer describes this deployment. The assistant’s tools can still be narrower than product availability; these facts are now expressed separately. Previous prototype navigation and the three README screenshots were not treated as a complete screen inventory. Shared Home research cards and F1 Source fragments require genuine-origin HTMX; their injected screenshots are explicitly limited and not evidence that those flows passed.

No complete cross-feature property graph, universal chat permission or seamless entity handoff was inferred. Where APIs differ, the user continues into the relevant owning workspace. The route and control appendix describes what exists, not an idealized future product.
