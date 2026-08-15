# PropertyScope screen inventory

## 1. Catalogue summary

The prototype contains **38 desktop views**, **9 selected mobile views** and **5 long-form captures**. It is a product/interaction reference, not an API-connected replacement for the running services.

- Interactive prototype: `../prototype/propertyscope-v2/standalone.html`
- Storyboard and screen catalogue: `../design-assets/storyboards/index.html`
- Desktop contact sheet: `../design-assets/desktop-contact-sheet.jpg`
- Mobile contact sheet: `../design-assets/mobile-contact-sheet.jpg`

## 2. Screen-to-owner/API inventory

| # | Route / screenshot | Owner | Release state | Purpose | Principal API/contract |
|---:|---|---|---|---|---|
| 1 | [`home`](../prototype/propertyscope-v2/standalone.html#/home) | Shared | R0 shell | Integrated product entry, global search, feature/release framing | Feature links; capability manifest |
| 2 | [`explore`](../prototype/propertyscope-v2/standalone.html#/explore) | Shared / F1 | R0 | Buyer-oriented property search and supported-footprint results | GET F1 /properties/search |
| 3 | [`property`](../prototype/propertyscope-v2/standalone.html#/property) | Shared composition preview | R0 target | Buyer-facing property evidence summary and cross-feature entry points | F1 property + coverage; later F2–F4 reads |
| 4 | [`system-status`](../prototype/propertyscope-v2/standalone.html#/system-status) | Shared | R0–R2 | Operational readiness and capability/deployment mode | Shared capability/readiness aggregation |
| 5 | [`agent-runs`](../prototype/propertyscope-v2/standalone.html#/agent-runs) | Shared AI-mode | R0–R2 | Durable agent-run index across features | AI-mode run index |
| 6 | [`agent-run`](../prototype/propertyscope-v2/standalone.html#/agent-run) | Shared AI-mode | R0–R2 | Plan/Act/Observe/Adapt events, tool evidence and review | AI-mode run/events/reviews |
| 7 | [`evidence`](../prototype/propertyscope-v2/standalone.html#/evidence) | Shared | R0–R2 | Cross-feature evidence ledger/navigation without owning domain data | Safe evidence references/projections |
| 8 | [`release-roadmap`](../prototype/propertyscope-v2/standalone.html#/release-roadmap) | Shared | R0–R2 | Honest implemented/enabled/planned capability view | Capability manifest |
| 9 | [`data-overview`](../prototype/propertyscope-v2/standalone.html#/data-overview) | Feature 1 | R0 | Accepted data, failures, candidates and operator actions | F1 summary/run/release endpoints |
| 10 | [`sources`](../prototype/propertyscope-v2/standalone.html#/sources) | Feature 1 | R0 | Source-definition list, filters and create CRUD | GET/POST /sources |
| 11 | [`source-detail`](../prototype/propertyscope-v2/standalone.html#/source-detail) | Feature 1 | R0 | Source metadata, jobs, lineage and edit/delete policy | GET/PUT/DELETE /sources/{id} |
| 12 | [`jobs`](../prototype/propertyscope-v2/standalone.html#/jobs) | Feature 1 | R0 | Job-definition list and safe execution profiles | Job-definition collection endpoints |
| 13 | [`job-detail`](../prototype/propertyscope-v2/standalone.html#/job-detail) | Feature 1 | R0 | Job configuration, limits, history and edit/delete | Job-definition detail endpoints |
| 14 | [`run-plan`](../prototype/propertyscope-v2/standalone.html#/run-plan) | Feature 1 | R0 | Request bounded full-refresh or cached-reprocess run | POST /ingestion-runs |
| 15 | [`runs`](../prototype/propertyscope-v2/standalone.html#/runs) | Feature 1 | R0 | Run history, filters and active status | GET /ingestion-runs |
| 16 | [`run-detail`](../prototype/propertyscope-v2/standalone.html#/run-detail) | Feature 1 | R0 | Tasks, quality, artifacts, failure and recovery actions | GET /ingestion-runs/{id}; action endpoints |
| 17 | [`releases`](../prototype/propertyscope-v2/standalone.html#/releases) | Feature 1 | R0 | Candidate/accepted/superseded release catalogue | GET/POST /dataset-releases |
| 18 | [`release-review`](../prototype/propertyscope-v2/standalone.html#/release-review) | Feature 1 | R0 | Candidate vs predecessor comparison and human publish/reject | GET /dataset-releases/{id}; POST /publish |
| 19 | [`quality`](../prototype/propertyscope-v2/standalone.html#/quality) | Feature 1 | R0 | Quality rule/result explorer | F1 quality endpoints |
| 20 | [`artifacts`](../prototype/propertyscope-v2/standalone.html#/artifacts) | Feature 1 | R0 | Bounded artifact lineage, hashes, sizes and retention | F1 artifact endpoints |
| 21 | [`coverage`](../prototype/propertyscope-v2/standalone.html#/coverage) | Feature 1 | R0 | Dataset/source/geography/time coverage matrix | F1 coverage endpoints |
| 22 | [`discovery`](../prototype/propertyscope-v2/standalone.html#/discovery) | Feature 1 | R0 | Operator view of canonical property registry and map/list | GET /properties/search |
| 23 | [`property-detail`](../prototype/propertyscope-v2/standalone.html#/property-detail) | Feature 1 | R0 | Canonical identity, external identifiers, map context and coverage | GET /properties/{ref}; /map-context; /coverage |
| 24 | [`ai-diagnosis`](../prototype/propertyscope-v2/standalone.html#/ai-diagnosis) | Feature 1 | R0 | Create bounded data-quality/recovery AI objective | POST /dataset-releases/{id}/agent-runs |
| 25 | [`market-cases`](../prototype/propertyscope-v2/standalone.html#/market-cases) | Feature 2 | R0 planned | Market-case CRUD collection | GET/POST /market-cases |
| 26 | [`market-detail`](../prototype/propertyscope-v2/standalone.html#/market-detail) | Feature 2 | R0 planned | Recorded sales, comparables, trends, methodology and AI | Property sales/comparables/summary + case detail |
| 27 | [`suburb-comparison`](../prototype/propertyscope-v2/standalone.html#/suburb-comparison) | Feature 3 | R0 planned | Saved suburb comparison, schools/places and context | Comparison CRUD + suburb/place/area endpoints |
| 28 | [`crime-trends`](../prototype/propertyscope-v2/standalone.html#/crime-trends) | Feature 3 | R0 planned | Same-period count/rate crime series with zero/missing | Crime series/compare/methodology endpoints |
| 29 | [`site-reviews`](../prototype/propertyscope-v2/standalone.html#/site-reviews) | Feature 4 | R0 planned | Site-review CRUD collection | GET/POST /site-reviews |
| 30 | [`site-detail`](../prototype/propertyscope-v2/standalone.html#/site-detail) | Feature 4 | R0 planned | Constraint layers, coverage, building evidence and questions | Constraints/layers/building + review detail |
| 31 | [`buyer-workspace`](../prototype/propertyscope-v2/standalone.html#/buyer-workspace) | Feature 5 | R0 planned | Profile, watchlist, dossiers and next actions | Profile/watchlist/dossier/follow-up collections |
| 32 | [`shortlist`](../prototype/propertyscope-v2/standalone.html#/shortlist) | Feature 5 | R0 planned | Two-to-four property comparison with evidence gaps | Dossier comparison + provider projections |
| 33 | [`dossier-builder`](../prototype/propertyscope-v2/standalone.html#/dossier-builder) | Feature 5 | R0 planned | Create/update dossier objective and selected sections | GET/POST/PUT /dossiers |
| 34 | [`dossier-run`](../prototype/propertyscope-v2/standalone.html#/dossier-run) | Feature 5 / Shared AI-mode | R0 planned | Integrated provider retrieval, adaptation and review gate | POST /dossiers/{id}/agent-runs |
| 35 | [`dossier-review`](../prototype/propertyscope-v2/standalone.html#/dossier-review) | Feature 5 | R0 planned | Source-linked report, reviewer findings and human disposition | GET /dossiers/{id}; POST /review; /print |
| 36 | [`follow-ups`](../prototype/propertyscope-v2/standalone.html#/follow-ups) | Feature 5 | R0 planned | Stakeholder task CRUD linked to evidence gaps | GET/POST/PUT/DELETE /follow-ups |
| 37 | [`grounded-answer`](../prototype/propertyscope-v2/standalone.html#/grounded-answer) | Release 1 shared + feature | R1 planned | MCP structured facts + RAG citations and grounding state | MCP/RAG/AI-mode run projection |
| 38 | [`multi-agent-review`](../prototype/propertyscope-v2/standalone.html#/multi-agent-review) | Release 2 local | R2 planned | Planner/worker/reviewer/human queue and findings | Multi-agent + AI-mode review contracts |

## 3. Storyboard coverage

| Storyboard | Journey | Screens represented |
|---|---|---|
| [`01-buyer-research-journey.jpg`](../design-assets/storyboards/01-buyer-research-journey.jpg) | Search → property evidence → shortlist → dossier → review/follow-ups | Home, explore, property, workspace, shortlist, dossier builder/run/review |
| [`02-data-release-recovery.jpg`](../design-assets/storyboards/02-data-release-recovery.jpg) | Failed run → quality evidence → AI diagnosis → human review → release | Data overview, runs/detail, quality, AI diagnosis, agent run, release review |
| [`03-feature-landscape.jpg`](../design-assets/storyboards/03-feature-landscape.jpg) | Five-feature product scope and ownership | Shared shell plus Feature 1–5 primary screens |
| [`04-screen-system-and-design.jpg`](../design-assets/storyboards/04-screen-system-and-design.jpg) | Design system, screen anatomy and evidence states | Shell, cards, data tables, forms, maps, timelines and review |
| [`05-responsive-mobile-storyboard.jpg`](../design-assets/storyboards/05-responsive-mobile-storyboard.jpg) | Mobile task flow and navigation | Selected home, explore, property, operations, run, feature detail and dossier views |

## 4. Required implementation states per screen

Every implemented route must demonstrate the states relevant to it:

| State | Minimum visual/behavioral evidence |
|---|---|
| Loading | Stable skeleton or progress phase, `aria-busy`, no layout collapse |
| Empty | Valid empty result with task-oriented next action; never a generic failure |
| Success | Source/release/match metadata adjacent to substantive evidence |
| Partial | Successful sections preserved; failed/unassessed provider named |
| Stale | Effective/observed date and accepted release shown; not labelled current |
| Conflict | Both records/versions shown and human review required |
| Validation error | Field-level message with request ID/problem detail where applicable |
| Version conflict | Reload/compare path; no silent overwrite |
| Dependency unavailable | CRUD/read fallback stays usable where possible |
| Capability disabled | Planned/release-gated explanation, not a broken action |
| Protected action | Proposed effect, evidence and approve/reject controls are separate from generation |

## 5. Mobile captures

- [`01-home.png`](../design-assets/mobile-contact-sheet.jpg)
- [`02-explore.png`](../design-assets/mobile-contact-sheet.jpg)
- [`03-property.png`](../design-assets/mobile-contact-sheet.jpg)
- [`04-data-overview.png`](../design-assets/mobile-contact-sheet.jpg)
- [`05-run-detail.png`](../design-assets/mobile-contact-sheet.jpg)
- [`06-market-detail.png`](../design-assets/mobile-contact-sheet.jpg)
- [`07-site-detail.png`](../design-assets/mobile-contact-sheet.jpg)
- [`08-buyer-workspace.png`](../design-assets/mobile-contact-sheet.jpg)
- [`09-dossier-review.png`](../design-assets/mobile-contact-sheet.jpg)

## 6. Full-page captures

- [`01-home.png`](../prototype/propertyscope-v2/standalone.html#/home)
- [`02-property.png`](../prototype/propertyscope-v2/standalone.html#/property)
- [`03-data-overview.png`](../prototype/propertyscope-v2/standalone.html#/data-overview)
- [`04-release-review.png`](../prototype/propertyscope-v2/standalone.html#/release-review)
- [`05-dossier-review.png`](../prototype/propertyscope-v2/standalone.html#/dossier-review)

## 7. Prototype navigation notes

- Hash route form: `standalone.html#/home`, `#/data-overview`, `#/market-detail`, and so on.
- The single-file build is designed for easy local review and screenshot capture.
- All displayed data is static showcase data and must be replaced by feature API responses in implementation.
- Buttons that represent future mutations intentionally behave as prototype interactions rather than persisting data.
- Feature/release labels are visible so future screens are not mistaken for implemented runtime services.
