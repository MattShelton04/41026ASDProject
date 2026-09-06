# Release 1 delivery plan and completion checklist

| Field | Value |
|---|---|
| Project | PropertyScope NSW, Group 20, 41026 Advanced Software Development |
| Assessment | Release 1: MCP, RAG and Intelligent Agent Integration; Assessment 2; 30% |
| Submission baseline | 27 September 2026, 11:59 pm AEST; Week 9 in-class showcase |
| Review date | 6 September 2026 |
| Repository inspected | `840ce0f78287bfb572e8a904c34f1f6d4ab5d77d` |
| Course archive inspected | `C:\git\Uni`; last Canvas refresh recorded as 3 September 2026 |
| Status | Planning baseline derived from course requirements, approved scope and current source; not release sign-off |

## 1. What Release 1 needs to deliver

Release 1 must retain the integrated five-feature Release 0 application and add **working local
MCP and RAG servers, used by the application to produce grounded AI responses**. It also requires
updated Docker integration, all five student workflows, testing and execution evidence, architecture
diagrams, project and individual plans, a group technical report and a new showcase video.

The five feature slices, shared shell and bounded AI-mode runner already exist. The main new shared
implementation is MCP, ingestion/retrieval and verifiable grounding. Feature owners must integrate
these capabilities into their own workflows and close the remaining approved-scope gaps below.
Existing tool-returned evidence and source labels are useful foundations; they do not by themselves
prove an MCP protocol exchange or a RAG ingestion, embedding and retrieval pipeline.

The deadline above comes from the archived specification and assessment overview. The archive says
the detailed Release 1 assignment/rubric and Weeks 7-12 material were **unpublished at its last
refresh**. This review did not refresh Canvas. Reconcile this plan with the published Release 1
brief before freezing scope or submission formatting. Do not carry over the stale FAQ's two-release
assessment structure, or assume Release 0's special video instructions apply to Release 1.

### How to use the checklist

- **Course** means an explicit requirement in the project specification or assessment overview.
- **Scope** means an existing commitment in the registered feature scope or living architecture.
- **Proposed** means a concrete implementation or acceptance approach for owner agreement, not a
  new tutor-approved product requirement.
- **Build** means implementation is missing; **complete** means extend a partial implementation;
  **verify** means retain evidence for existing behavior; **decide** means resolve a recorded gap.
- An unchecked item is remaining work or evidence. It does not mean all related code is absent.
  Close it with a linked test, reviewed decision, execution record or submission artifact.

The course requires successful LLM interaction from every feature and MCP/RAG validation in every
student workflow. This plan proposes one demonstrable MCP-and-RAG-assisted task per feature as the
clearest way to satisfy that integration requirement. The available specification does not prescribe
five separate MCP/RAG servers, a minimum tool/chunk count or five different retrieval stacks.

## 2. Source authority and review evidence

### Course sources

The archive links below assume the `Uni` checkout remains beside this repository. They are reference
material, not runtime dependencies; do not copy the course archive into this repository.

| ID | Source | Relevant requirement |
|---|---|---|
| C1 | [Project specification PDF](../../../Uni/courses/41026-advanced-software-development/files/week-0/ASD_2026_Project_Specifications.pdf) | pp. 2-3: individual/team responsibilities; p. 5: AI release capabilities; pp. 8-11: local architecture and containers; p. 14: five updated workflows; p. 18: schedule; p. 20: full Release 1 submission checklist |
| C2 | [Assessment overview](../../../Uni/courses/41026-advanced-software-development/pages/get-started--2543779--assessment-overview.md) | Release 1 weighting, deadline and Week 9 showcase |
| C3 | [Course archive status](../../../Uni/courses/41026-advanced-software-development/README.md) | Refresh date and unpublished Release 1 brief/labs |
| C4 | [Archived release checklist](../../../Uni/planning/41026-project-release-checklists.md) and [content conflicts](../../../Uni/planning/content-conflicts.md) | Secondary cross-check; identifies stale FAQ and Release 0-specific changes |

### Repository sources

| ID | Source | Use in this plan |
|---|---|---|
| P1 | [Registered feature scope](../architecture/registered-feature-scope.md) | Approved owners, feature purposes and minimum boundaries |
| P2 | [Shared-platform design](../architecture/shared-platform-design.md), especially sections 11, 14-16 and 18 | MCP adapter, RAG pipeline, ownership, test and release design |
| P3 | [Integration and experience contract](../architecture/feature-integration-and-experience-contract.md) | Public APIs, shell integration and Feature 5 composition ownership |
| P4 | [Release 0 report](../reports/release-0-technical-report.md), especially sections 6-9 | Current retained baseline, per-feature data counts, CI/Compose evidence and limitations |
| P5 | [Feature enablement](../../deployment/features.yaml), [Compose](../../docker-compose.yml), [Integration CI](../../.github/workflows/integration-ci.yml) | Executable deployment and current CI selection |
| P6 | [AI services](../../ai-services/README.md), [AI-mode](../../ai-services/ai-mode/README.md), [agent contracts](../../shared/contracts/python/shared_contracts/agent.py) | Existing harness and missing retrieval/citation contract |
| P7 | [Feature 1](../../student-1/README.md), [Feature 2](../../student-2/README.md), [Feature 3](../../student-3/README.md), [Feature 4](../../student-4/README.md), [Feature 5](../../student-5/README.md) | Feature-specific implementation, integration and limitations |
| P8 | [Repository health review](../reviews/repository-health-review.md), section 6 | Carry-over risks; historical validation gaps must be rechecked, not assumed current |

Some living documents still say Features 2-5 are unimplemented or disabled. Current manifests,
feature source and the Release 0 report show all five enabled. Use P1 for approved **scope**, not
its stale implementation paragraph. Similarly, historical Feature 1 marking evidence describes old
Ollama commands and limits; the current root README and developer command own operational guidance.

## 3. Current baseline and remaining gaps

| Area | Observed baseline | Release 1 delta or verification needed |
|---|---|---|
| Shared application | All five manifests enabled; common shell, routes, design system, mapping and AI chat; Release 0 report retains 21-service Compose evidence | Add truthful MCP/RAG capability, readiness and citation views; rerun integrated Release 1 checks |
| Agent core / AI-mode | Durable four-phase runs, versioned prompts, HTTP tool catalogues, limits, trusted identifiers, retries, cancellation, human review and provider adapters | Implement MCP dispatch and retrieval integration; typed citation/provenance propagation, validation and evaluation |
| MCP | `ai-services/mcp-server/` contains only `.gitkeep` | Build service, package, protocol adapter, authentication, tests, Docker target and operational docs |
| RAG | `ai-services/rag-server/` contains only `.gitkeep` | Build versioned corpus ingestion, embeddings/index, retrieval, citations, lifecycle, tests and Docker target |
| Feature 1 | Governed source ingestion/publication, canonical properties, consumer contracts and AI tools | Supply agreed RAG evidence; verify accepted/downloadable generations and downstream receipts; settle per-table evidence interpretation |
| Feature 2 | Case CRUD, deterministic sale summaries, read-only AI tools and durable streaming v3 sales import | Prove accepted PSI import and grounded explanations; preserve deterministic arithmetic and provenance |
| Feature 3 | Fixture UI/AI, saved comparisons; separate accepted-product ingestion and Published evidence APIs | Connect selected published evidence to AI/retrieval; resolve authenticated saved-suburb scope and fixture/official separation |
| Feature 4 | Review CRUD, evidence states, synthetic maps, question generation; PostgreSQL/PostGIS-owned store | Resolve database approval/documentation; implement agreed versioned evidence import or obtain explicit scope exception |
| Feature 5 | Buyer-case/shortlist/note/task CRUD, bounded API aggregation and AI summary | Replace hard-coded Feature 3 unavailability; resolve partial-page evidence lookup and UI pagination; integrate scoped retrieval |
| CI and evidence | Canonical source gate and five student workflows; retained Release 0 successes | Add MCP/RAG checks to every student workflow and full integrated Release 1 execution evidence |

Source checks confirm Feature 5's [evidence client](../../student-5/backend/src/propertyscope_buyer_workspaces/integrations.py)
unconditionally marks Feature 3 unavailable and searches only the first 25 Feature 2/4 candidates.
Its [frontend client](../../student-5/frontend/api.js) fixes child lists to page 1 with 100 records.
Feature 3's [tool catalogue](../../student-3/tool-catalog.yaml) explicitly describes fixture evidence.
Feature 4's README explicitly records the missing producer products/import route. These are concrete
integration gaps, not reasons to rebuild the already implemented slices.

## 4. Decisions to settle first

Shared responsibilities below need named team assignees; this plan does not allocate someone else's
assessed work. Each feature remains owned by its registered student.

| ID | Remaining decision/action | Owner | Closure evidence |
|---|---|---|---|
| D1 | Recheck Canvas for Release 1 brief, marking rubric, lab constraints, showcase date and report filename/submission rules | Team/report lead | Dated source reconciliation; update this plan if requirements change |
| D2 | Assign MCP, RAG, AI integration, shared UI, CI and report owners plus affected-feature reviewers | Team | Named backlog assignees and review responsibilities |
| D3 | Choose one bounded AI task and licensed corpus per feature; record formats, size, refresh policy, example questions and expected evidence | Each feature owner + RAG owner | Five reviewed task/corpus specifications; optional ideas below explicitly accepted or replaced |
| D4 | Confirm MCP protocol/SDK version, local transport, vector store, embedding provider/model, offline test strategy and laptop budgets | Shared maintainers | ADR and pinned dependencies; do not assume the current text-model profile supplies embeddings |
| D5 | Resolve identity and access scope: Feature 3 requires authenticated user-specific endpoints; Feature 5 currently uses a configured demo owner | Shared + James + Derek | Agreed identity contract and implementation, or explicitly approved release-specific deferral; internal tokens are not user authentication |
| D6 | Retain durable tutor approval for the OpenAI provider and Feature 1 PostgreSQL exception; separately resolve Feature 4 PostgreSQL/PostGIS divergence | Team + Matthew + Michael | Approval reference and aligned ADR/topology, or agreed migration; Feature 1 approval does not automatically cover Feature 4 |
| D7 | Resolve the literal minimum-ten-records-per-table requirement, particularly Feature 1 operational tables | Each owner, led by Matthew for F1 | Table inventory/count evidence and explicit tutor interpretation where a table is exempt; large warehouse counts do not prove every table meets it |
| D8 | Agree Feature 4 evidence publisher, dataset/license coverage and producer/consumer contracts | Michael + Matthew | Bounded product/import commitment, or explicit approved deferral; do not invent statewide planning/building ingestion as an implicit shared requirement |

OpenAI is the approved project direction recorded in P1, despite C1's generic Ollama/open-source
requirements. Preserve that approval trail rather than adding an unrequested local-model rewrite.
The embedding choice is a separate decision, including permission to send corpus content to a remote
embedding service. Local MCP/RAG deployment does not imply that the approved LLM API runs locally.

## 5. Shared functionality work packages

### S1. Contracts, trust boundaries and backward compatibility

**Owner:** shared contracts / AI maintainers, reviewed by all feature owners. **Basis:** Scope P2/P3;
implementation details are Proposed. **Dependencies:** D3-D5.

- [ ] Define versioned ingestion, retrieval and citation contracts with bounded input/output schemas.
  Include feature/corpus scope, query, filter semantics and explicit empty/unavailable outcomes.
- [ ] Give every retrieved chunk a source URI, document ID, chunk ID, content hash, location in the
  document, ingestion time and corpus version as specified in P2. Include source release/date and
  synthetic/official status where applicable; do not confuse ingestion time with evidence currency.
- [ ] Define how grounded answers link claims to returned evidence identifiers and how feature API,
  persisted run/event, operations UI and chat projections preserve those references. Existing generic
  JSON observations and prose `evidence_references` are not a validated citation contract.
- [ ] Specify retrieval authorization before search: allowed feature/corpus and, if applicable,
  authenticated owner/case. Do not make all feature data visible merely because tools share an MCP server.
- [ ] Preserve current `feature_key`, tool allowlists, trusted-identifier checks, correlation,
  approval, time/size limits and idempotency through new adapters. Citation identifiers must not
  automatically become trusted identifiers for a mutation.
- [ ] Generate and drift-check affected JSON Schema/OpenAPI artifacts; add compatible persistence
  migration/read tests for existing Release 0 runs. Update architecture-validator tests for approved
  new boundaries and document any ADR-level changes.

**Done when:** each feature can consume the same neutral retrieval/citation envelope; old runs remain
readable; cross-feature/owner leakage and unsupported citation IDs fail deterministic tests.

### S2. MCP server and orchestrator client

**Owner:** MCP maintainer + AI-mode maintainer; feature owners retain tools. **Basis:** Course C1
pp. 5, 9, 14, 20; Scope P2 section 11.1. **Dependencies:** S1 and D4.

- [ ] Create the `ai-services/mcp-server` workspace package, service README, application lifecycle,
  health/readiness, configuration and Docker target. Pin a tested official Python MCP SDK/protocol.
- [ ] Implement and test capability/version negotiation, tool discovery and invocation over the
  planned local Streamable HTTP transport. Support stdio only if useful for isolated tests.
- [ ] Project enabled feature catalogues into MCP tools without duplicating domain CRUD, changing
  ownership, or exposing disabled/unknown tools. Preserve JSON Schema inputs/outputs, deadlines and
  side-effect classification. Expose approved contextual resources; add reusable prompts only where useful.
- [ ] Add AI-mode's MCP client/dispatch adapter so a real application run actually invokes MCP and
  reaches the owning feature backend over HTTP. Merely running an Inspector demo is insufficient.
- [ ] Prevent arbitrary target URLs, paths and database access. Apply service authorization and
  run/feature scope on every invocation; ensure MCP cannot bypass Feature 1 publication/retry approval.
- [ ] Handle connection loss, timeout, malformed results, protocol mismatch and cancellation with
  bounded behavior and safe errors. Never replay a side effect blindly after an uncertain result.
- [ ] Retain redacted discovery/request/response evidence linked to a run and owning feature.

**Done when:** an integrated feature request follows frontend -> backend -> AI-mode -> MCP -> owning
backend; tests reject unauthorized tools, and the same domain tool has equivalent HTTP/MCP behavior.

### S3. RAG ingestion and corpus lifecycle

**Owner:** RAG maintainer; feature owners own corpus meaning and permitted sources. **Basis:** Course
C1 p. 20; Scope P2 section 11.2. **Dependencies:** D3/D4/D8, S1.

- [ ] Create the `ai-services/rag-server` workspace package, service README, Docker target, health,
  configuration and exclusive ownership of its index/metadata storage.
- [ ] Implement approved-source loading -> parse -> normalize -> chunk -> hash -> embed -> versioned
  index. Keep parsing/chunking separate from model, network and filesystem adapters for deterministic tests.
- [ ] Start with a simple local vector store. Record model/dimensions, chunk strategy, corpus bounds,
  provenance and licensing. Reranking or a distributed database needs measured justification.
- [ ] Ingest only approved documents or owner-provided HTTP/publication projections. Do not open a
  feature database, reuse its credentials, or turn RAG into a second authoritative property warehouse.
- [ ] Make ingestion explicit, reproducible and idempotent. Test changed-content reindexing, duplicate
  input, deletion/withdrawal, failed build recovery and atomic activation of a complete corpus version.
- [ ] Retain the previous working corpus on failed refresh. Invalidate stale retrieval/cache entries
  using corpus/model/source versions; make retired evidence identifiable in historical runs.
- [ ] Bound document size, parsing expansion, batch memory, embedding requests and disk use. Validate
  source URLs and redirects; report unsupported or inaccessible documents instead of silently omitting them.
- [ ] Keep fixtures and official sources explicitly distinct. Provide a small reproducible demonstration
  corpus that can run without a source-scale download; keep restricted/raw data and secrets out of Git.

**Done when:** a fresh environment builds the agreed corpus, repeat ingestion is stable, source metadata
survives chunking, and a failed/withdrawn source cannot silently yield falsely current evidence.

### S4. Retrieval, grounded answers and safe degradation

**Owner:** RAG + AI-mode maintainers with each feature owner. **Basis:** Course C1 pp. 5, 20;
Scope P2 sections 11-14. **Dependencies:** S1-S3.

- [ ] Implement scoped vector retrieval with bounded top-k/context budget, deterministic filters,
  version/score metadata and explicit no-match, unavailable and ambiguous-source outcomes.
- [ ] Integrate retrieval into the existing Plan -> Act -> Observe -> Adapt loop. Keep the route
  between AI-mode and RAG documented; whether retrieval is exposed through MCP is a reviewed adapter
  choice, not a reason to bypass the owning feature's policy.
- [ ] Extend versioned prompts to delimit retrieved text as untrusted evidence. Keep calculations,
  permissions and protected actions in deterministic code; retrieved instructions cannot grant authority.
- [ ] Require generated factual explanations to cite supplied evidence. Validate identifier existence
  and scope in code; assess whether the cited passage actually supports the claim through evaluation.
  Do not treat a syntactically valid citation as proof of factual support.
- [ ] Keep facts, interpretations, user notes, suggested actions and missing evidence distinguishable.
  Preserve disagreement, source dates, geographic match confidence and synthetic-data labels.
- [ ] Handle no retrieval, stale/conflicting evidence and provider/service outage honestly. If a fallback
  answer uses ordinary tool evidence, label it accurately; do not call it a successful RAG response.
- [ ] Extend safe run evidence with retrieval time, corpus version, selected chunk IDs, scores,
  citation validation outcome and final limitations, without storing private reasoning or secrets.

**Done when:** a user can follow a material claim to the retrieved passage and version; no-match and
injection scenarios produce bounded, truthful outcomes while CRUD remains usable.

### S5. Shared UI and experience

**Owner:** shared frontend maintainer + feature owners. **Basis:** Course common UI/integration;
Scope P3. **Dependencies:** S1/S4.

- [ ] Extend the common chat/evidence presentation with readable source titles, passage/location,
  version/date, coverage and links. Reuse neutral components; feature-specific meaning stays in its slice.
- [ ] Display retrieval and generation progress, empty corpus, no relevant evidence, stale evidence,
  service failure and retry states. Do not render raw model HTML or unsafe links.
- [ ] Project MCP/RAG health and enabled status into shared status/roadmap/operations views; remove
  planned labels only when the deployed capability exists. Ordinary feature readiness must remain
  distinguishable from optional AI/provider degradation.
- [ ] Verify deep links, shell/direct-origin navigation, citation inspection, keyboard/focus behavior,
  narrow screens, populated/error states and repeated navigation without leaking polls/listeners.

**Done when:** all five features use coherent grounding states and users can inspect citations through
the shared origin without understanding internal service ports or identifiers.

### S6. Local deployment and developer operations

**Owner:** deployment maintainer. **Basis:** Course C1 pp. 9-11, 20. **Dependencies:** S2/S3.

- [ ] Implement Release 1 service selection in Compose and `scripts/dev.py`, including the existing
  enabled-feature projection. The architecture's `release-1` profile is a target, not a working command today.
- [ ] Add pinned non-root image targets, lockfile/workspace inputs, storage owners, internal networking,
  startup/readiness ordering, resource limits and development mounts for MCP/RAG.
- [ ] Add non-secret environment examples and explicit corpus setup/rebuild/status/recovery instructions.
  Keep credentials in runtime secrets and preserve data on ordinary stack shutdown.
- [ ] Verify a clean build/start and an upgrade using existing feature databases and agent runs. Restart
  RAG/MCP independently; test index persistence, failed ingestion recovery and unavailable-provider behavior.
- [ ] Prove the full five-feature Release 1 stack on the nominated showcase computer, including resource
  usage and embedding preparation time. Avoid requiring official-source downloads during the video.
- [ ] Keep Release 0 operation compatible and multi-agent functionality disabled. Preserve the design
  that excludes MCP/RAG from the later cloud graph; Azure deployment itself is Release 2 work.

**Done when:** documented commands reproduce the integrated local increment, retain data across normal
restarts and expose no unowned database mounts or credentials.

## 6. Feature work and acceptance

Every feature owner must retain frontend/backend/database separation, visible CRUD, minimum table
data, shared navigation/style, successful approved-LLM interaction and four-phase run evidence.
The tasks below add to those common responsibilities; they do not transfer domain work to Shared.
Suggested retrieval sources/questions are **Proposed**, pending D3 and source licensing.

### F1. Data Platform and Property Discovery — Matthew Shelton

**Existing:** governed acquisitions, release review/publication, consumer contracts, canonical
property search and tools including `property.inspect.v1`, `data.coverage.v1`,
`data.run_explain.v1` and protected retry/publication actions. See [consumer guide](../../student-1/DATA_PRODUCT_CONSUMER_GUIDE.md).

- [ ] **Complete:** choose the Release 1 retrieval task, for example explaining property coverage or
  diagnosing a failed import using approved source methodology, dataset metadata and operator guidance.
  Expose bounded evidence over owned APIs, with release provenance and safe run diagnostics.
- [ ] **Build/integrate:** expose the selected existing tools through MCP and consume S4 grounding in
  discovery/diagnosis. Keep the human approval path for retry/publication; RAG must not approve a dataset.
- [ ] **Verify:** canonical property references, accepted artifact availability, contract discovery,
  checksums/schema versions and consumer delivery receipts for the chosen Feature 2/3 demonstrations.
  A successful candidate import is not proof of accepted, downloadable downstream evidence.
- [ ] **Decide/complete:** coordinate only the explicitly agreed Feature 4 product work under D8.
  Preserve complete-source publication rules; partial PSI archive-year candidates cannot be silently
  promoted to complete accepted history to make a demo pass.
- [ ] **Verify:** source/job CRUD and scope validation; cancellation/retry/resume; release review,
  rejection and publication; property discovery; freshness/coverage/provenance and AI failure states.
- [ ] **Decide/verify:** close D6/D7 with durable approval and per-table evidence; refresh stale source
  commands/limits in marking guidance if referenced in the Release 1 report.

**Acceptance example:** select a property or failed run, invoke a bounded MCP tool and retrieve relevant
methodology; display a supported explanation with exact source/corpus references. Missing coverage
stays missing, and a proposed operational action still requires its existing approval.

### F2. Property Sales Explorer and Market Cases — Burhan Naeem

**Existing:** market-case CRUD, date/filter validation, counts/median/volume, two read-only tools,
26 synthetic sale observations and 10 cases; durable streaming `propertyscope.property-sales.v3`
import support as documented in [ADR-042](../architecture/decisions/ADR-042-durable-streaming-sales-import.md).

- [ ] **Verify:** import an agreed accepted `nsw-psi-sales` release from Feature 1 and retain digest,
  schema/generation checks, complete row accounting, receipt and atomic accepted-pointer evidence.
  Exercise interrupted/duplicate import and show the prior generation remains readable on failure.
- [ ] **Complete:** select sale methodology, field definitions, exclusions and approved provenance
  material for RAG. Use current case scope and deterministic summary from the owning tools as facts.
- [ ] **Integrate:** expose `market.cases.inspect.v1` and `market.sales.summary.v1` through MCP;
  make the explanation cite selected sale evidence and retrieved methodology without mixing releases.
- [ ] **Verify:** CRUD, property-reference/date/filter validation, match tiers, exclusions, insufficient
  sample, missing/zero prices, stale edits, synthetic labels and provider-unavailable UI.
- [ ] **Verify:** keep median/sample count/volume calculations in backend code. No valuation, price
  forecast, buy recommendation or invented comparable-selection feature is part of this increment.

**Acceptance example:** open a saved property/date case, inspect recorded sales and deterministic
summary, then obtain a cited explanation of the figures and exclusions; an unsupported question
reports the missing evidence without manufacturing a sale or metric.

### F3. Suburb, Crime and Liveability Analytics — James Huang

**Existing:** fixture search/maps/comparisons and AI tools; independent Published evidence ingestion
for BOCSAR, government schools and accepted ABS SEIFA population. The README's historical activation
failures are prerequisites to recheck, not assumed current outages.

- [ ] **Complete:** verify accepted/downloadable upstream products, import receipts and the resulting
  Published evidence views. Preserve fenced staging, capacity limits and atomic activation.
- [ ] **Complete:** agree how the selected published dataset feeds the Release 1 AI workflow. Current
  `suburb.snapshot.v1`, `crime.compare.v1` and `crime.methodology.v1` describe fixture data; do not
  silently relabel them as official merely because a separate import panel works.
- [ ] **Build/integrate:** index approved methodology/definitions and expose scoped tools through MCP;
  show retrieved source passages alongside the selected locality, period, measure and evidence release.
- [ ] **Complete/decide:** reconcile the approved saved/favourite suburb and user-data CRUD scope with
  saved-comparison CRUD and browser-local bookmarks. Implement authenticated, durable user-specific
  saved-suburb behavior with D5, or record an explicitly approved release-specific exception.
- [ ] **Coordinate:** define the bounded public locality/property-context projection consumed by
  Feature 5, including ambiguous locality matching, pagination and unavailable/partial states.
- [ ] **Verify:** same-period comparisons, count/rate separation, zero versus missing, category coverage,
  geography alignment and population date compatibility. Recent crime divided by incompatible 2021
  population is not an approved current rate. No causal/safety ranking or school-catchment claim.
- [ ] **Verify:** search/filter/sort, approved amenity/location indicators, saved records and map/chart
  table alternatives; document unsupported categories instead of inventing data.

**Acceptance example:** retrieve locality evidence plus methodology and explain a supported comparison
with period/coverage limitations. A missing locality, mismatched geography or absent denominator
produces an explicit limit rather than zero, a fabricated rate or a safety judgement.

### F4. Site, Planning and Building Due Diligence — Michael White

**Existing:** site-review CRUD, checklist/questions/notes/disposition, evidence states, two read-only
tools and synthetic planning/building observations/maps. The store uses PostgreSQL/PostGIS; an
equivalent tutor-approved exception is not established by the Feature 1 ADR.

- [ ] **Decide:** resolve D6's database approval/documentation discrepancy and D8's evidence source
  dependency before claiming the registered feature boundary complete.
- [ ] **Build:** implement the agreed versioned evidence-release import into the owned store, with
  product schemas, provenance, matching/confidence, verification, retries and atomic visibility;
  alternatively retain a specific approved deferral and explicit fixture limitation.
- [ ] **Complete:** select bounded approved planning/environmental/building guidance for RAG. Keep
  general guidance distinct from verified observations about the selected property.
- [ ] **Integrate:** expose `duediligence.review.inspect.v1` and `duediligence.evidence.summary.v1`
  through MCP and generate a question pack that cites retrieved passages and observation sources.
- [ ] **Verify:** zoning/heritage/FSR/height, supported environmental evidence, strata/building-order/
  tribunal observations, evidence states, match method/confidence, property selection and review CRUD
  against the agreed source coverage. A missing layer is not a confirmed non-intersection.
- [ ] **Verify:** map extent/payload bounds and honest synthetic labels. The current generated polygons
  must not be presented as real parcel intersections or current planning certificates.
- [ ] **Verify:** evidence-service failures and failed question-pack saves remain visible in UI and
  tests. Generated questions request professional verification; they do not certify legal compliance,
  building safety or suitability.

**Acceptance example:** open a review and generate source-linked verification questions while retaining
confirmed/partial/non-intersection/unavailable states. An absent source produces a verification gap,
not a definitive finding.

### F5. Buyer Journey and Agent Workspace — Derek Song

**Existing:** buyer-case, shortlist, note and task CRUD; stages/ratings/preferences; four read-only
tools; bounded public-API aggregation; configured single-user demo ownership.

- [ ] **Complete:** replace unconditional Feature 3 unavailability with the agreed F3 public API,
  configuration and contract tests. Preserve real timeout, ambiguity and unavailable states.
- [ ] **Complete:** replace first-page-only Feature 2/4 matching with an owner-agreed bounded lookup or
  pagination strategy. Distinguish an incomplete search from no evidence; test a match beyond record 25.
  Do not make Feature 1 or Shared perform these cross-domain joins.
- [ ] **Complete:** make all cases and child collections reachable in UI; test more than 100 records,
  stable ordering and filter scope. This is separate from deliberately bounded AI context.
- [ ] **Complete/decide:** apply D5 identity scope to case/child reads, writes, tool calls and retrieval.
  Until resolved, keep the configured demo owner explicit and do not claim multi-user isolation.
- [ ] **Integrate:** expose the existing buyer inspect/notes/tasks/evidence tools through MCP. Agree a
  corpus of permitted buyer guidance or owner-scoped case material; do not index private notes into a
  shared unrestricted corpus. Preserve feature/source/case identity in the summary citations.
- [ ] **Verify:** stages, shortlist add/remove, preferences, notes/ratings, task CRUD/completion,
  ownership/version validation, evidence refresh and AI unavailable/cancel/retry behavior.
- [ ] **Verify:** distinguish user preferences from external facts and missing evidence from conflicts.
  Suggested next actions remain suggestions; do not automatically create tasks, contact agents or
  recommend a purchase as an unapproved extension.

**Acceptance example:** summarize a buyer case using supported property/sales/suburb/site evidence and
retrieved guidance, cite the evidence for each material finding and name unavailable sections. A note
containing instructions to ignore policy must not change tool permissions or expose another case.

## 7. Testing, CI and evidence work

### Q1. Deterministic validation

**Owner:** shared test maintainer plus all five feature owners. **Basis:** Course C1 p. 14/p. 20;
Scope P2 section 14. Use existing thresholds; do not invent course-mandated RAG score targets.

- [ ] Add contract/unit/component tests for S1-S4: protocol discovery/invocation, scoped retrieval,
  chunk provenance, index lifecycle, citation validity, bounded context and safe rendering.
- [ ] Add negative tests for unknown/disabled tools, invalid arguments, cross-feature/case access,
  prompt injection, forged citations, corrupt imports, missing corpora, upstream outage and timeout.
- [ ] Keep ordinary CI independent of paid APIs, credentials, internet, Docker and Azure unless a job
  explicitly runs integration tests. Use injected model/embedding/transport doubles and small corpora.
- [ ] Extend architecture, packaging, deployment and catalogue validators to cover the new services.
  Test prior-release schema/run/index upgrades where applicable.
- [ ] Run `uv run python scripts/check.py`; retain stage results and skip/failure reasons. The command
  covers source checks, Python suites/coverage and Node behavior, but excludes browser E2E and does
  not by itself prove real MCP/RAG containers, real databases or approved-provider interaction.

### Q2. All five student workflows and integrated containers

- [ ] Update **each** `.github/workflows/student-1.yml` through `student-5.yml` to build/validate its
  feature with MCP/RAG integration. Include relevant shared MCP/RAG/contract changes in path triggers.
  One shared green workflow does not replace the five individual workflow obligations.
- [ ] Reuse the canonical quality gate and small shared fixtures where appropriate; retain an owned
  integration assertion/evidence artifact for each student instead of duplicating unrelated full suites.
- [ ] Extend `integration-ci.yml` or a clearly linked integration job to build/start the full local
  Release 1 topology and exercise the shared origin, five slices, MCP, RAG and AI-mode with test doubles.
  Current Integration CI validates Release 0 Compose configuration but does not start the full stack.
- [ ] Run real database/container smoke: migrations, seed/table counts, CRUD through each frontend/API,
  data persistence after restart, accepted release consumption and failure isolation.
- [ ] Retain successful workflow URLs, commit SHA, image identity, Compose status/health, JUnit/coverage
  and redacted logs. Capture failures and clean only disposable CI data.
- [ ] Complete relevant dependency/secret/container checks required by the living design and retain
  results; do not claim vulnerability or licence clearance from the source gate alone.

### Q3. Retrieval and real-model evaluation

- [ ] Version a small evaluation set per selected feature task: answerable, ambiguous, absent evidence,
  stale/conflicting evidence, outage and malicious retrieved text. Identify expected sources and
  forbidden claims before changing prompts or tuning retrieval.
- [ ] Measure retrieval relevance (for example expected-source recall at the chosen k), citation
  correctness/support, unsupported claims, task success, tool selection, latency and token/embedding
  cost. Agree thresholds before sign-off; numeric targets are a team decision, not in the available rubric.
- [ ] Compare a tool-only baseline with the new retrieved-context workflow on the same cases to show
  what RAG contributes. Record failures and corpus/model/prompt versions, not only successful examples.
- [ ] Retain one successful approved-provider run through each feature's actual frontend/backend path
  on the release candidate, with Plan/Act/Observe/Adapt, MCP request/response, retrieval and final citations.
  Provider diagnostics and fake-model tests do not replace per-feature LLM evidence.
- [ ] Rehearse no-model/no-MCP/no-RAG scenarios: CRUD and deterministic evidence remain usable, and no
  fallback is falsely described as retrieved or grounded when it lacks the claimed source support.

### Q4. Browser and user acceptance

- [ ] Exercise all five populated feature routes from the shared home, CRUD, deep links and AI results
  using normal browser origins. Include unavailable data/services, stale updates and more-than-one-page data.
- [ ] Inspect citations, keyboard navigation, focus return, errors/live regions, accessible chart tables,
  narrow screens and zoom; repeat route changes to expose abandoned pollers or obsolete responses.
- [ ] Use the existing quick/full UI audit and feature browser suites where applicable, and add the
  small missing MCP/RAG/citation scenarios. Keep browser evidence separate from the canonical source gate.

## 8. Report, planning and showcase deliverables

These are Course requirements from C1 p. 20, not optional polish. Use a new Release 1 report source
under `docs/reports/` and retained evidence under `docs/release-1/`; preserve Release 0 history.

### Group and individual planning

- [ ] Updated project overview, overall project plan and Agile team plan.
- [ ] Group sprint backlog with owners, dependencies, acceptance criteria and completion evidence.
- [ ] Each student's updated functional/non-functional requirements, feature plan and risk plan.
- [ ] Updated repository structure and implementation summary explaining MCP/RAG integration.
- [ ] Contribution logs, meaningful commit/PR records and attendance checkpoints for this increment.
- [ ] Human validation of AI-assisted code, documents and tests; retain useful development/testing
  evidence without secrets or private reasoning. Do not fabricate missing historical transcripts.

### Architecture and technical evidence

- [ ] Five individual software architecture diagrams matching the actual service/database choices.
- [ ] Integrated Release 1 software architecture and Docker Compose architecture diagrams.
- [ ] MCP server architecture and actual request/response flow.
- [ ] RAG ingestion/index/retrieval architecture and grounded-response flow through the agent loop.
- [ ] Description and execution evidence for `student-1.yml` through `student-5.yml`.
- [ ] Local integration tests, Compose execution, MCP requests/responses, RAG retrieval and grounded
  answer evidence; screenshots of the integrated app with MCP and RAG enabled.
- [ ] Known issues, fixture/licensing/coverage limitations, unresolved decisions and approval references.
- [ ] Evidence index mapping every requirement/task to its file, test/log, workflow URL or demonstration
  step, with software commit, corpus/source versions and capture date. Historical evidence stays labelled.

### Submission and demonstration

- [ ] Prepare a **new maximum-ten-minute published video** for the Week 9 showcase. Every student
  participates and demonstrates their own feature inside the integrated application.
- [ ] Demonstrate from one team member's computer; show the shared home, working feature paths,
  MCP tool use, retrieval and inspectable grounded answers. Use prevalidated corpora/data and prepared
  cases so ingestion or a cold provider response does not consume the recording.
- [ ] Rehearse the integrated sequence and Q&A; confirm exact Week 9 session/attendance instructions
  from the new brief. Release 0's five-minute Q&A and special video exclusion are not assumed R1 rules.
- [ ] Produce one group technical-report PDF including the repository and published video URLs;
  verify access as a reviewer and confirm Release 1 naming/upload requirements on Canvas.
- [ ] Freeze a release candidate and capture evidence from that software/corpus version. If fixes
  change demonstrated behavior, update the affected evidence before final submission.

This document is a delivery backlog, not the final technical report or proof that a showcase passed.

## 9. Proposed sequence and critical dependencies

The following dates are a **proposed working schedule**, not additional course deadlines. Bring
forward the final rehearsal to suit the actual Week 9 class; do not wait until the Sunday PDF deadline.

| Window | Focus | Exit condition |
|---|---|---|
| 6-9 September | D1-D8, task/corpus definitions, shared contracts and five baseline gap lists | Named owners; bounded sources/tasks; unresolved approval/scope decisions visible |
| 10-15 September | MCP and RAG minimum services; first complete feature path; begin F3/F4/F5 gaps | One frontend-to-MCP-to-feature run plus indexed retrieval and validated citations |
| 16-20 September | Integrate remaining features and five workflows; complete source/data prerequisites | Every selected feature task works against the same shared contract and local stack |
| 21 September to showcase | Full container/browser/evaluation run, issue closure, evidence and rehearsal | Five feature demonstrations, report draft and accessible video ready before class |
| Before 27 September, 11:59 pm AEST | Final brief reconciliation, report/video access check and PDF submission | Complete, coherent group submission with known limitations stated |

Critical paths:

1. Task/corpus and access decisions -> retrieval/citation contract -> RAG and MCP integration -> five
   feature adapters -> integrated validation -> report/video.
2. Feature 1 accepted, downloadable releases -> Feature 2/3 imports -> Feature 5's relevant summaries.
   Feature 1 publication remains producer-owned; consumer acceptance does not gate its publication.
3. Feature 4 source/contract decision -> producer product if required -> owned importer -> reliable
   property-specific evidence. A small approved document corpus can prove RAG earlier, but it does not
   itself close the missing evidence-import commitment.
4. Identity decision -> authenticated saved suburbs/case scope -> private-corpus permission tests.
   Keep public document retrieval separate from private-case indexing until this is resolved.

## 10. Release acceptance gates

- [ ] **G1 — Requirements:** published brief reconciled; all five approved feature commitments are
  implemented/verified or have an explicit approved deferral; D6/D7 evidence discrepancies resolved.
- [ ] **G2 — Working software:** five integrated frontend/backend/database slices retain CRUD and data;
  actual MCP and RAG services run locally and participate in user-facing AI workflows.
- [ ] **G3 — Grounding:** representative answers cite retrieved evidence; missing/conflicting/adversarial
  evidence is handled truthfully; data/corpus provenance and access scope are preserved.
- [ ] **G4 — Engineering:** canonical gate passes; five updated workflows pass; real local container,
  browser, persistence and per-feature approved-provider evidence is retained with its limits.
- [ ] **G5 — Submission:** updated plans, diagrams, implementation/evaluation evidence, contributions,
  attendance, accessible video and final report are complete for the same release candidate.

## 11. What not to turn into a Release 1 blocker

Release 2 introduces the multi-agent server, distinct Planner/Worker/Reviewer agent roles, expanded
pre-/post-commit AI-assisted testing and Azure deployment. Do not move those into Release 1 merely
because the shared runner already uses multiple model roles or parallel read-only tool calls.
Ordinary testing and the existing human-review protections remain required now.

Broad module decomposition, a frontend framework/TypeScript migration, complete CSS cleanup,
distributed vector infrastructure, reranking and a full telemetry platform are not necessary to
prove this release. Carry relevant P8 findings forward, fixing correctness/accessibility defects
on the selected paths. Resolve identity where approved scope requires it; wider production identity
hardening remains a separate decision. Do not add valuation, automatic purchasing, agent outreach,
legal certification or unapproved data-source expansion.

## 12. Validation of this planning review

The review read the local course specification and archived assessment/planning material, current
project/feature READMEs, living architecture, Release 0 report, manifests/Compose/workflows, tool
catalogues and selected implementation paths. It does not claim an exhaustive line-by-line audit
or a refreshed Canvas deadline check. The working tree was clean before documentation edits.

Validation performed on 6 September 2026:

- `uv run python scripts/check.py` **passed** (exit 0): formatting, lint, generated-contract and
  deployment drift, architecture/packaging/model/tool checks, styles, type checking, JavaScript
  syntax, Python tests with configured coverage gates and 195 passing Node behavior tests.
  Platform-dependent tests can skip; the onboarding symlink case skipped on this Windows host.
- All 26 Markdown links in this plan resolve to existing local files, including the adjacent archive.
- `git diff --check` passed for the tracked documentation changes.

Not run for this documentation review: a new Docker build/full-stack execution, browser E2E,
live-provider/embedding evaluation, official-source ingestion, GitHub Actions execution or Canvas
refresh. Existing retained Release 0 evidence is cited, not represented as a fresh Release 1 run.
The remaining planning assumptions are D1-D8 and the explicitly proposed task/corpus choices and
schedule; no new domain scope or implementation technology is treated as approved by this document.

Only this plan and its documentation-index links were changed. No application changes, source
acquisitions, publications, deployments, commits or pushes were performed.
