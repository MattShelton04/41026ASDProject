# PropertyScope NSW

**Release 1 / Technical report**

41026 Advanced Software Development — Assessment 2

| Submission | Group 20 |
|---|---|
| Due | 4 October 2026, 11:59 pm Sydney time |
| Repository | [MattShelton04/41026ASDProject](https://github.com/MattShelton04/41026ASDProject) |
| Showcase video | [Release 1 presentation](https://youtu.be/0Z0Rt146lD0) |
| Showcase | 2 October 2026 |
| Commit reference | [[BASELINE]] |

Evidence distinguishes real provider answers, deterministic decisions against live services,
and isolated tests. Repository links identify the selected report baseline.

[[PAGEBREAK]]

[[TOC]]

## 1 Project overview and Release 1 scope

PropertyScope NSW connects property discovery, recorded sales, suburb context, site due diligence
and buyer research. Release 1 retains five independently owned frontend/backend/database slices,
their CRUD and AI-mode, and the shared research shell. It adds shared host MCP and RAG servers,
grounded answers, and separate MCP/RAG loop validation modes. Cloud deployment and multi-agent
orchestration belong to Release 2.

Matthew owns Shared and Feature 1; Burhan owns Feature 2; James owns Feature 3; Michael owns
Feature 4; Derek owns Feature 5. Tutor approval for OpenAI and PostgreSQL was reconfirmed by
Matthew on 3 October; this is a team statement, not an attached original approval document.

### 1.2 Delivery plan and risks

The shared runtime and Feature 1 landed first; the adoption kit then let feature owners register
tools, corpora and backend routes independently. The final integration increment captures one
running stack, checks each feature, refreshes the report and reviews the submission against the
current rubric. The [release audit](../release-1/submission-plan-2026-10-03.md) records tasks,
owners and remaining checks. Missing data, provider availability and scope changes are the main
risks; versioned evidence, bounded failures and owner reviews limit their impact.

## 2 Functional requirements

| ID | Required behaviour | Evidence |
|---|---|---|
| FR1 | Retain each feature's UI, API and owned persistence | Live operations, Section 6.3 |
| FR2 | Discover registered MCP tools and return structured, scoped results | Tool catalogue and frontend captures |
| FR3 | Retrieve only the selected feature's versioned guidance | Corpus probe and cited answers |
| FR4 | Display citations, confidence and an insufficient-context response | Three assistant scenarios per feature |
| FR5 | Retain Plan/Act/Observe/Adapt; add separate MCP/RAG validation modes | Captured outputs, Section 6.2 |
| FR6 | Deploy feature microservices in Compose; keep AI tier on host | Status and architecture evidence |
| FR7 | Build/test each assigned workflow with MCP/RAG disabled | Five successful workflow links |

## 3 Non-functional requirements

| Quality | Target and validation boundary |
|---|---|
| Security | Token-protected host APIs; MCP/RAG bind to loopback. Live unauthenticated probes return 401. Signed calls bind feature, run, arguments, deadline and approval. |
| Isolation | No cross-feature imports or database access. Architecture checks enforce HTTP boundaries. Only Feature 1's two write tools require approval. |
| Grounding | Guidance findings cite retrieved passages; current facts cite successful tool calls. Corpus changes invalidate completion. Confidence describes evidence support, not probability. |
| Reliability | Timeouts and structured errors bound failed calls. RAG unavailability produces insufficient context; ordinary CRUD remains independent. Outage tests use controlled doubles. |
| Retrieval quality | Authored Feature 1 evaluation targets recall@5 ≥0.9; measured 0.963. This is not held-out five-feature answer accuracy. |
| Performance | Retrieval bounds top-k to five; registered tools have 2–10 second deadlines. The fresh RAG loop retrieves in 108 ms; one sample is not a latency benchmark. |
| Usability | Shared citations and activity remain keyboard accessible. Deterministic browser checks cover narrow layouts; live captures use Chromium at 1440×1000. |
| Reproducibility | Python 3.12, locked workspace dependencies, generated deployment manifests and versioned corpora. Tests require no provider credentials. |
| Maintainability | Corpus adoption changes only the owning manifest/documents; all five registrations pass generated-catalogue and architecture checks. |
| Interoperability | MCP Streamable HTTP and JSON Schema contracts; SDK round-trip tests require correlated, schema-valid results and reject unauthorised calls. |
| Availability | CRUD remains independent of unavailable AI; outage tests verify bounded degradation. Store-reopen and identical-ingestion tests require preserved history/version. These are recovery checks, not an uptime SLA. |

## 4 Release 1 architecture

Compose runs the edge and five feature slices. Each database has one owning service. AI-mode
contains the loop and calls the configured model over HTTPS; MCP and RAG are separate host
processes. Backends reach AI-mode through `host.docker.internal`; MCP dispatches only to registered
feature HTTP routes. Neither shared service opens a feature database.

![Figure 1 Overall Release 1 architecture and container boundary](assets/release-1/release-1-architecture.png)

| Path | Responsibility |
|---|---|
| `student-1/` … `student-5/` | Owned UI, API, persistence, tools and corpus |
| `ai-services/agent-core/` | Loop policies, grounding and confidence |
| `ai-services/ai-mode/` | Run API, provider and MCP/RAG adapters |
| `ai-services/mcp-server/`, `rag-server/` | Tool transport; local semantic retrieval |
| `shared/contracts/`, `tool-runtime/`, `frontend/` | Schemas, dispatch and research shell |
| `deployment/`, `.github/workflows/`, `scripts/` | Compose projections, CI and developer commands |

## 5 MCP and RAG design

A question goes from the frontend to its owning backend, then AI-mode with a fixed feature scope.
The planner selects allowlisted tools. MCP validates signed invocation metadata, dispatches to
the owning backend and validates correlation and output schemas. Successful MCP results carry
`transport:mcp`; an ordinary HTTP result cannot satisfy the capture check.

![Figure 2 Frontend, backend, MCP and RAG interaction flow](assets/release-1/mcp-rag-interaction.png)

### 5.1 Tools, inputs and outputs

MCP lists 29 feature tools. `context.retrieve.v1` is an internal AI-mode retrieval operation,
not a thirtieth MCP tool. Full JSON schemas remain in each feature's `tool-catalog.yaml`.

[[TOOL_TABLE]]

[[TOOL_DETAIL]]

### 5.2 Knowledge sources and grounded responses

Each corpus contains authored CC0 project guidance, not current property facts. Sources retain
document identifiers, dates and immutable corpus versions. The manifests link every Markdown
source: [F1](../../student-1/config/rag/corpus.json),
[F2](../../student-2/config/rag/corpus.json), [F3](../../student-3/config/rag/corpus.json),
[F4](../../student-4/config/rag/corpus.json), [F5](../../student-5/config/rag/corpus.json).

F1 covers publication and property-data limits; F2 explains sale matching and case eligibility;
F3 distinguishes missing locality evidence from zero; F4 explains review evidence states;
F5 explains case stages, shortlists and tasks. Live versions contain 19/3/8/3/5 documents.

![Figure 3 Versioned ingestion, retrieval and grounding](assets/release-1/rag-pipeline.png)

The prepared BGE model embeds passages locally. Retrieval combines semantic and lexical ranking,
limits repeated documents and applies a 0.55 relevance floor. Retrieved text is untrusted evidence.
Eligible grounded production runs use `default.v9`; ungrounded runs retain `default.v7`.
High confidence needs strong support and no reported gaps; one document plus one current tool
check can count as two supports. Reported gaps or weak support give moderate; model-reported
stale/conflicting evidence can retain low. An unsupported answer has no citations.

## 6 Validation and results

### 6.1 Terminal validation

On 3 October, the [live probe](../release-1/evidence/live-service-probe.json) passed authentication,
all five MCP registrations, corpus readiness, relevant retrieval and off-topic no-match checks.
AI-mode reports healthy provider/store readiness and accepts its token; this alone does not prove
a model answer. Feature screenshots below separately exercise the configured provider.

```text
$ uv run scripts/dev.py ai probe
MCP: HTTP 200; 29 tools; feature counts 14 / 3 / 4 / 3 / 5
RAG: BAAI/bge-small-en-v1.5 ready; 384 dimensions
Corpora: 19 / 3 / 8 / 3 / 5 documents
Each feature: relevant retrieval PASS; off-topic no_match PASS
Unauthenticated AI-mode / MCP / RAG: HTTP 401
All checks passed.
```

![Figure 4 Registered live knowledge sources](assets/release-1/screenshots/shared-knowledge-sources.png)

### 6.2 Shared agentic loop

Both named validation modes run the production loop against live local services with deterministic
`default.v8` decisions. They prove transport and phase execution; they do not measure provider
answer quality. The ordinary production mode remains available.

![Figure 5 Loop entry points and validation modes](assets/release-1/agent-loop-validation.png)

[[LOOP_OUTPUT docs/release-1/evidence/validation-mcp.json]]

[[LOOP_OUTPUT docs/release-1/evidence/validation-rag.json]]

### 6.3 Feature UI, API and persistence

The [live operations record](../release-1/evidence/live-feature-operations.json) identifies frontend
responses, backend reads and database-backed operations for each feature. Assistant captures use
existing saved contexts. Viewport captures use 1440×1000; focused cards reflow at 1100 pixels wide.
Each capture sidecar records the source SHA, time, run/request IDs,
successful tool calls, corpus version and image hashes; no private reasoning trace is exported.

| Feature | Live persistence observation |
|---|---|
| 1 | Draft source create/read/update/delete; cleanup GET 404 |
| 2 | Owning store: 10 cases, 26 sale records |
| 3 | Owning store: 10 suburbs, 400 indicators, 38 amenities, 10 overviews, 10 user-suburbs |
| 4 | Site review create/read/update/delete; cleanup GET 404 |
| 5 | Owning store: 10 cases, 11 notes, 12 properties, 12 tasks |

Counts include demonstration records; they establish persisted operations, not official coverage.

#### Feature 1 Property data

Full UI captures: [mcp](assets/release-1/screenshots/feature-1-mcp.png), [rag](assets/release-1/screenshots/feature-1-rag.png), [insufficient](assets/release-1/screenshots/feature-1-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-1-rag.json).

Published-release counts come from MCP; guidance explains why missing sale history is unknown.

![Figure 6 Feature 1 MCP result](assets/release-1/screenshots/feature-1-mcp.answer.png)

![Figure 7 Feature 1 cited answer and confidence](assets/release-1/screenshots/feature-1-rag.answer.png)

![Feature 1 supporting passage, source date and corpus version](assets/release-1/screenshots/feature-1-rag.citation.png)

![Figure 8 Feature 1 insufficient context](assets/release-1/screenshots/feature-1-insufficient.answer.png)

#### Feature 2 Market cases

Full UI captures: [mcp](assets/release-1/screenshots/feature-2-mcp.png), [rag](assets/release-1/screenshots/feature-2-rag.png), [insufficient](assets/release-1/screenshots/feature-2-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-2-rag.json).

The selected case constrains its eligible sales and recorded-price summary.

![Figure 9 Feature 2 MCP result](assets/release-1/screenshots/feature-2-mcp.answer.png)

![Figure 10 Feature 2 cited answer and confidence](assets/release-1/screenshots/feature-2-rag.answer.png)

![Feature 2 supporting passage, source date and corpus version](assets/release-1/screenshots/feature-2-rag.citation.png)

![Figure 11 Feature 2 insufficient context](assets/release-1/screenshots/feature-2-insufficient.answer.png)

#### Feature 3 Suburb analytics

Full UI captures: [mcp](assets/release-1/screenshots/feature-3-mcp.png), [rag](assets/release-1/screenshots/feature-3-rag.png), [insufficient](assets/release-1/screenshots/feature-3-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-3-rag.json).

The MCP example returns crime methodology; the cited answer distinguishes missing evidence from zero.

![Figure 12 Feature 3 MCP result](assets/release-1/screenshots/feature-3-mcp.answer.png)

![Figure 13 Feature 3 cited answer and confidence](assets/release-1/screenshots/feature-3-rag.answer.png)

![Feature 3 supporting passage, source date and corpus version](assets/release-1/screenshots/feature-3-rag.citation.png)

![Figure 14 Feature 3 insufficient context](assets/release-1/screenshots/feature-3-insufficient.answer.png)

#### Feature 4 Due diligence

Full UI captures: [mcp](assets/release-1/screenshots/feature-4-mcp.png), [rag](assets/release-1/screenshots/feature-4-rag.png), [insufficient](assets/release-1/screenshots/feature-4-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-4-rag.json).

The selected review exposes evidence states without treating an absent layer as clearance.

![Figure 15 Feature 4 MCP result](assets/release-1/screenshots/feature-4-mcp.answer.png)

![Figure 16 Feature 4 cited answer and confidence](assets/release-1/screenshots/feature-4-rag.answer.png)

![Feature 4 supporting passage, source date and corpus version](assets/release-1/screenshots/feature-4-rag.citation.png)

![Figure 17 Feature 4 insufficient context](assets/release-1/screenshots/feature-4-insufficient.answer.png)

#### Feature 5 Buyer workspace

Full UI captures: [mcp](assets/release-1/screenshots/feature-5-mcp.png), [rag](assets/release-1/screenshots/feature-5-rag.png), [insufficient](assets/release-1/screenshots/feature-5-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-5-rag.json).

The selected buyer case supplies its budget, target suburbs and shortlist.

![Figure 18 Feature 5 MCP result](assets/release-1/screenshots/feature-5-mcp.answer.png)

![Figure 19 Feature 5 cited answer and confidence](assets/release-1/screenshots/feature-5-rag.answer.png)

![Feature 5 supporting passage, source date and corpus version](assets/release-1/screenshots/feature-5-rag.citation.png)

![Figure 20 Feature 5 insufficient context](assets/release-1/screenshots/feature-5-insufficient.answer.png)

### 6.4 Retrieval evaluation

The authored Feature 1 baseline uses a disposable index and the same embedding model. Expected-source
recall measures document retrieval, not factual correctness of a generated answer.

[[RETRIEVAL_SUMMARY student-1/config/rag/evaluation-baseline-v2.json]]

### 6.5 GitHub Actions

All assigned workflows set `AI_MODE_MCP_ENABLED=false` and `AI_MODE_RAG_ENABLED=false` and test
contracts with doubles. The following successful runs cover integrated baseline `330e65f`,
1 October UTC, including all five merged Release 1 implementations. They precede this report-update
branch; [run metadata](../release-1/evidence/github-workflow-runs.json) preserves their full SHAs.
Student 5 starts offline direct AI-mode; MCP/RAG remain disabled. Its owner should reconcile this
with the brief's broader AI-mode-disabled instruction.

| Workflow | Successful run |
|---|---|
| Student 1 | [36905626023](https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626023) |
| Student 2 | [36905626184](https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626184) |
| Student 3 | [36905625989](https://github.com/MattShelton04/41026ASDProject/actions/runs/36905625989) |
| Student 4 | [36905626030](https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626030) |
| Student 5 | [36905626058](https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626058) |
| Integration | [36905626020](https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626020) |

### 6.6 Docker Compose deployment

The [3 October stack status](../release-1/evidence/live-stack-status.txt) records 20 running
containers: edge, F1's six, F2/F3/F5's three each, and F4's four. All 18 healthchecked containers
are healthy; F1 runner and loader have no Docker healthcheck. AI-mode/MCP/RAG are separate running
host processes. Shared home and all five feature pages return 200 in the operations record.
Backends retain the generated host connection configuration; Compose defines no AI service.

| Live service group | Running / healthy |
|---|---|
| Shared edge | 1 / 1 |
| Feature 1 | 6 / 4; runner/loader have no healthcheck |
| Features 2, 3 and 5 | 3 / 3 each |
| Feature 4 | 4 / 4 |
| Host AI-mode, MCP, RAG | 3 running; authenticated probe passes |

![Figure 21 CI and local deployment](assets/release-1/ci-and-deployment.png)

## 7 Integration summary

One Compose project and one host AI tier serve all five features. MCP reaches owned backend tools;
RAG retrieves each registered corpus. The frontend scenarios cover structured current facts, cited
guidance and insufficient context, while the operations record covers ordinary database-backed
behaviour. These selected paths establish integration; the limitations below constrain broader
claims. Activity history links runs to their feature and evidence.

![Figure 22 Cross-feature activity history](assets/release-1/screenshots/shared-activity-history.png)

## 8 Known issues and limitations

- Corpora are project guidance, not official methodology; confidence does not prove entailment.
- Related but irrelevant passages can exceed the relevance floor. The F2 password example still
  refuses with zero citations; retrieval similarity alone does not establish a supported answer.
- Live operation requires a prepared host, embedding model and working provider access.
- The [accepted-data snapshot](../release-1/evidence/live-data-status.json) records real G-NAF
  5,190,134; PSI 7,402,643; BOCSAR 318,122; SEIFA 4,320. Schools (10) and fixture properties (3)
  remain seeded demonstrations. Unpublished candidates are not current data.
- F2 can retain old history when cases change, and old context during an active turn; F4's native generated-question renderer
  does not handle all grounded finding objects. These owner fixes are outside this Shared/F1 increment.
- F3 locality coverage is incomplete. F4's selected review uses source-attributed synthetic demonstration
  constraints/building records, not verified official coverage; missing evidence remains unknown.
- One exploratory F4 off-topic turn failed adaptation validation; the captured password question
  returned valid insufficient context. Selected successful scenarios do not establish all-question reliability.
- F5's offline AI-mode CI start needs owner review. The report does not certify every persistence
  table has ten rows or Q&A quality from repository checks. Video coverage still needs human review.

## 9 Contributions, repository and showcase

[Repository](https://github.com/MattShelton04/41026ASDProject) and
[showcase presentation](https://youtu.be/0Z0Rt146lD0) accompany this report. Matthew confirmed on
3 October that all five attended and participated in the 2 October showcase. Recorded participation:
Matthew Shelton, Burhan Naeem, James Huang, Michael White and Derek Song. This confirms attendance;
the marker assesses each student's demonstration and Q&A. The unauthenticated watch page loads;
[player metadata](../release-1/evidence/showcase-metadata.json) reports 575 seconds (9:35).

### Student 1 Matthew Shelton

7 September: [1e109ac](https://github.com/MattShelton04/41026ASDProject/commit/1e109ac),
shared MCP/RAG, host runtime, loop modes and F1 grounding. 19 September:
[9bc4ee9](https://github.com/MattShelton04/41026ASDProject/commit/9bc4ee9), adoption kit.
26 September: [e7485af](https://github.com/MattShelton04/41026ASDProject/commit/e7485af), retrieval/confidence
evaluation. 3 October: [6aed375](https://github.com/MattShelton04/41026ASDProject/commit/6aed375),
verified MCP transport; this branch adds report guards, live capture and responsive Sources checks.

### Student 2 Burhan Naeem

28 September: [a1b8577](https://github.com/MattShelton04/41026ASDProject/commit/a1b8577),
F2 allowlist, corpus, capability tool and shared chat;
[d18dfee](https://github.com/MattShelton04/41026ASDProject/commit/d18dfee), UI evidence/capture fixes.
1 October: [f019e41](https://github.com/MattShelton04/41026ASDProject/commit/f019e41), assistant workspace
and refreshed screenshots.

### Student 3 James Huang

1 October: [da7556c2](https://github.com/MattShelton04/41026ASDProject/commit/da7556c2),
map access to F1 data. 2 October: [b1181cd](https://github.com/MattShelton04/41026ASDProject/commit/b1181cd),
tools, shared chat and corpus; [330e65f](https://github.com/MattShelton04/41026ASDProject/commit/330e65f),
guidance and published locality-context refinements.

### Student 4 Michael White

1 October: [bbd112d](https://github.com/MattShelton04/41026ASDProject/commit/bbd112d), grounded
allowlist/capability; [a6b7b7f](https://github.com/MattShelton04/41026ASDProject/commit/a6b7b7f), corpus;
[e0720f4](https://github.com/MattShelton04/41026ASDProject/commit/e0720f4), shared assistant;
[b4cf74a](https://github.com/MattShelton04/41026ASDProject/commit/b4cf74a), CI tests;
[7aa69f6](https://github.com/MattShelton04/41026ASDProject/commit/7aa69f6), live evidence.
[Owner log](../../student-4/docs/release-1-contribution.md).

### Student 5 Derek Song

1 October: [bb1e3b2](https://github.com/MattShelton04/41026ASDProject/commit/bb1e3b2), scoped
assistant routes, corpus, cited UI and MCP/RAG evidence.
[Owner log](../../student-5/docs/release-1-contribution.md).

Contribution identities resolve in the selected baseline. Reproduce with `stack up`, explicit
corpus ingestion, `ai probe`, `ai validate mcp`, `ai validate rag`,
`capture_release1_screenshots.py`, `capture_release1_integration.py` and the full `check.py` gate.
Build the single `group-20.pdf` with `build_release1_report.py --final --baseline <sha>`.

<!-- RELEASE1_METADATA
schema_version: 1
baseline: '[[BASELINE]]'
repository_url: https://github.com/MattShelton04/41026ASDProject
showcase_url: https://youtu.be/0Z0Rt146lD0
sections:
  scope: 1 Project overview and Release 1 scope
  requirements: 2 Functional requirements
  nonfunctional: 3 Non-functional requirements
  architecture: 4 Release 1 architecture
  design: 5 MCP and RAG design
  validation: 6 Validation and results
  integration: 7 Integration summary
  limitations: 8 Known issues and limitations
  contributions: 9 Contributions, repository and showcase
  planning: 1.2 Delivery plan and risks
evidence:
- kind: terminal
  section: 6.1 Terminal validation
  path: docs/release-1/evidence/live-service-probe.json
  boundary: Live local service probes; no generated-answer quality claim.
- kind: deployment
  section: 6.6 Docker Compose deployment
  path: docs/release-1/evidence/live-stack-status.txt
  boundary: Existing local ps-dev containers and host processes, no data reset.
- kind: loop-mcp
  section: 6.2 Shared agentic loop
  path: docs/release-1/evidence/validation-mcp.json
  boundary: Production runner and live local services; deterministic validation decisions.
- kind: loop-rag
  section: 6.2 Shared agentic loop
  path: docs/release-1/evidence/validation-rag.json
  boundary: Production runner and live local services; deterministic validation decisions.
- kind: feature-mcp
  student: 1
  section: Feature 1 Property data
  path: docs/reports/assets/release-1/screenshots/feature-1-mcp.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-rag
  student: 1
  section: Feature 1 Property data
  path: docs/reports/assets/release-1/screenshots/feature-1-rag.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-crud
  student: 1
  section: 6.3 Feature UI, API and persistence
  path: docs/release-1/evidence/live-feature-operations.json
  boundary: Actual local frontend/API and owner persistence checks; see per-feature actions and cleanup.
- kind: ci
  student: 1
  section: 6.5 GitHub Actions
  workflow: student-1.yml
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626023
  boundary: Successful retained integrated baseline330e65f run; precedes report-update branch; MCP/RAG disabled.
- kind: feature-mcp
  student: 2
  section: Feature 2 Market cases
  path: docs/reports/assets/release-1/screenshots/feature-2-mcp.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-rag
  student: 2
  section: Feature 2 Market cases
  path: docs/reports/assets/release-1/screenshots/feature-2-rag.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-crud
  student: 2
  section: 6.3 Feature UI, API and persistence
  path: docs/release-1/evidence/live-feature-operations.json
  boundary: Actual local frontend/API and owner persistence checks; see per-feature actions and cleanup.
- kind: ci
  student: 2
  section: 6.5 GitHub Actions
  workflow: student-2.yml
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626184
  boundary: Successful retained integrated baseline330e65f run; precedes report-update branch; MCP/RAG disabled.
- kind: feature-mcp
  student: 3
  section: Feature 3 Suburb analytics
  path: docs/reports/assets/release-1/screenshots/feature-3-mcp.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-rag
  student: 3
  section: Feature 3 Suburb analytics
  path: docs/reports/assets/release-1/screenshots/feature-3-rag.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-crud
  student: 3
  section: 6.3 Feature UI, API and persistence
  path: docs/release-1/evidence/live-feature-operations.json
  boundary: Actual local frontend/API and owner persistence checks; see per-feature actions and cleanup.
- kind: ci
  student: 3
  section: 6.5 GitHub Actions
  workflow: student-3.yml
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/36905625989
  boundary: Successful retained integrated baseline330e65f run; precedes report-update branch; MCP/RAG disabled.
- kind: feature-mcp
  student: 4
  section: Feature 4 Due diligence
  path: docs/reports/assets/release-1/screenshots/feature-4-mcp.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-rag
  student: 4
  section: Feature 4 Due diligence
  path: docs/reports/assets/release-1/screenshots/feature-4-rag.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-crud
  student: 4
  section: 6.3 Feature UI, API and persistence
  path: docs/release-1/evidence/live-feature-operations.json
  boundary: Actual local frontend/API and owner persistence checks; see per-feature actions and cleanup.
- kind: ci
  student: 4
  section: 6.5 GitHub Actions
  workflow: student-4.yml
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626030
  boundary: Successful retained integrated baseline330e65f run; precedes report-update branch; MCP/RAG disabled.
- kind: feature-mcp
  student: 5
  section: Feature 5 Buyer workspace
  path: docs/reports/assets/release-1/screenshots/feature-5-mcp.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-rag
  student: 5
  section: Feature 5 Buyer workspace
  path: docs/reports/assets/release-1/screenshots/feature-5-rag.png
  boundary: Owning frontend/backend, live configured provider and local MCP/RAG; selected saved context.
- kind: feature-crud
  student: 5
  section: 6.3 Feature UI, API and persistence
  path: docs/release-1/evidence/live-feature-operations.json
  boundary: Actual local frontend/API and owner persistence checks; see per-feature actions and cleanup.
- kind: ci
  student: 5
  section: 6.5 GitHub Actions
  workflow: student-5.yml
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/36905626058
  boundary: Successful retained integrated baseline330e65f run; precedes report-update branch; MCP/RAG disabled.
contributions:
- student: 1
  section: Student 1 Matthew Shelton
  commits:
  - 1e109ac
  - 9bc4ee9
  - e7485af
  - 6aed375
- student: 2
  section: Student 2 Burhan Naeem
  commits:
  - a1b8577
  - d18dfee
  - f019e41
- student: 3
  section: Student 3 James Huang
  commits:
  - da7556c2
  - b1181cd
  - 330e65f
- student: 4
  section: Student 4 Michael White
  commits:
  - bbd112d
  - a6b7b7f
  - e0720f4
  - b4cf74a
  - 7aa69f6
- student: 5
  section: Student 5 Derek Song
  commits:
  - bb1e3b2
attendance:
  1: Matthew Shelton
  2: Burhan Naeem
  3: James Huang
  4: Michael White
  5: Derek Song
-->
