# PropertyScope NSW

**Release 1 / Technical report**

41026 Advanced Software Development — Assessment 2

| Submission | Group 20 |
|---|---|
| Team | Matthew Shelton, Burhan Naeem, James Huang, Michael White, Derek Song |
| Due | 4 October 2026, 11:59 pm Sydney time |
| Repository | [MattShelton04/41026ASDProject](https://github.com/MattShelton04/41026ASDProject) |
| Showcase video | [Release 1 presentation (9:35)](https://youtu.be/0Z0Rt146lD0) |
| Showcase | 2 October 2026 |
| Commit reference | [[BASELINE]] |

[[PAGEBREAK]]

[[TOC]]

## 1 Project overview and Release 1 scope

PropertyScope NSW helps buyers research NSW property. In Release 0 each student built a
containerised frontend, backend/API and database feature behind a shared home page, using the host
AI-mode's Plan/Act/Observe/Adapt loop. Release 1 keeps these and adds a shared MCP server, a shared
RAG server and MCP/RAG loop validation modes, all host processes outside Docker. Every feature's
assistant now calls its tools through MCP and answers from its own cited corpus. Tutor approval for
OpenAI and PostgreSQL was reconfirmed by Matthew on 3 October.

### 1.1 Responsibilities

| Owner | Release 1 responsibility |
|---|---|
| Group (shared; led by Matthew) | MCP and RAG servers, AI-mode adapters, loop validation modes, adoption kit, Compose host configuration and integration evidence |
| Matthew Shelton, F1 Property data | 14 tools (two approval-gated writes), data-platform corpus, grounded assistant |
| Burhan Naeem, F2 Sales and market | 3 market-case tools, sale-matching corpus, assistant workspace |
| James Huang, F3 Suburb analytics | 4 suburb and crime tools, analytics corpus, map of F1 data |
| Michael White, F4 Due diligence | 3 site-review tools, evidence-state corpus, assistant, CI tests |
| Derek Song, F5 Buyer workspace | 5 buyer-case tools, workflow corpus, scoped assistant routes |

Each student also maintains their feature's Compose services and `student-N.yml` workflow.

### 1.2 Delivery plan and risks

The shared runtime and Feature 1 landed first (7 September); an adoption kit (19 September) let
each owner register tools, a corpus and a route independently. A final increment captured one
running stack ([release audit](../release-1/submission-plan-2026-10-03.md)). Versioned evidence
and bounded failures limited the main risks: missing data and provider availability.

## 2 Functional requirements

| ID | Requirement | Evidence |
|---|---|---|
| FR1 | Each feature keeps its Release 0 frontend, backend/API, database CRUD and AI-mode | 6.3 |
| FR2 | MCP lists registered tools, runs only a feature's allowlisted tools and returns schema-validated results | 5.1, 6.1, 6.3 |
| FR3 | RAG ingests versioned corpora and searches only the requesting feature's corpus | 5.2, 6.1 |
| FR4 | Every feature frontend reaches MCP and RAG through its own backend `assistant/turns` route | 6.3, 7 |
| FR5 | Answers show citations and a confidence category, or an insufficient-context response when nothing relevant is found | 6.3 |
| FR6 | The shared loop keeps its Release 0 mode and adds separate MCP and RAG validation modes | 6.2 |
| FR7 | Compose deploys the feature containers with host AI-mode, MCP and RAG addresses; no AI service is containerised | 6.6 |
| FR8 | Each `student-N.yml` builds and tests its feature with MCP and RAG disabled | 6.5 |

## 3 Non-functional requirements

A shared AI tier risks one feature reaching another's tools or passages, untraceable answers, and
AI failures breaking ordinary feature work. These targets address those risks.

| Quality | Requirement and target | Validation |
|---|---|---|
| Security | Host AI APIs need a service token; MCP and RAG bind to 127.0.0.1. Every unauthenticated call is refused. | Live probe: unauthenticated calls return 401 |
| MCP tool boundaries | A run calls only its feature's allowlisted tools; each call is signed for feature, run, arguments and deadline. Writes need approval. | Architecture checks block cross-feature imports and database access; tests reject out-of-scope calls |
| RAG grounding and traceability | Every guidance finding cites a retrieved passage with document, corpus version and content hash; current facts cite a tool call. | Citation figures; corpus version recorded per run |
| Retrieval quality | Expected-source recall@5 ≥ 0.9 on authored F1 questions | Measured 0.963 (6.4) |
| Reliability | Every tool call has a deadline and a structured error; RAG failure gives insufficient context, never an unsupported answer | Outage tests with controlled doubles |
| Performance | At most five passages per retrieval; tool deadlines 2–10 s | Loop: MCP tool 15 ms, retrieval 108 ms |
| Usability | Citations and run activity are keyboard accessible and reflow in narrow panels | Browser checks |
| Maintainability | A feature adopts MCP and RAG by editing only its own catalogue, corpus and allowlist | All five pass catalogue and architecture checks |
| Interoperability | MCP Streamable HTTP with JSON Schema tool contracts | SDK round-trip tests validate schema-valid results |
| Availability | Feature CRUD works while AI services are down; RAG history survives restarts | Outage, store-reopen and re-ingestion tests |

## 4 Release 1 architecture

Compose runs the shared edge and five feature slices, each with a frontend, backend/API and owned
database service. AI-mode (containing the agentic loop), MCP and RAG run as separate host
processes and are never containerised. Backends reach AI-mode through `host.docker.internal`;
AI-mode calls MCP, RAG and the OpenAI model; MCP dispatches only to registered feature routes.
Neither shared server opens a feature database.

![Figure 1 Overall Release 1 architecture and container boundary](assets/release-1/release-1-architecture.png)

### 4.1 Repository structure

| Path | Responsibility |
|---|---|
| `student-1/` … `student-5/` | Owned UI, API, persistence, tools and corpus |
| `ai-services/agent-core/` | Loop policies, grounding and confidence |
| `ai-services/ai-mode/` | Run API, provider and MCP/RAG adapters |
| `ai-services/mcp-server/`, `rag-server/` | Tool transport; local semantic retrieval |
| `shared/contracts/`, `tool-runtime/`, `frontend/` | Schemas, dispatch and research shell |
| `docker-compose.yml`, `deployment/` | Release 0 Compose with host MCP/RAG addresses |
| `.github/workflows/`, `scripts/` | CI and developer commands |

## 5 MCP and RAG design

A question goes from a feature's frontend to its own backend, which starts an AI-mode run fixed to
that feature's tool allowlist and corpus. MCP checks
each call's signed metadata, dispatches it to the owning backend and validates the result against
the tool's output schema. Results carry `transport: mcp`, distinguishing them from direct HTTP.

![Figure 2 Frontend, backend, MCP and RAG interaction flow](assets/release-1/mcp-rag-interaction.png)

### 5.1 Tools, inputs and outputs

MCP lists 29 feature tools; a run sees only its own feature's tools. 27 are read-only and
Feature 1's two writes need human approval. `context.retrieve.v1` is AI-mode's internal retrieval
step, not an MCP tool. Full JSON schemas are in each feature's `tool-catalog.yaml`.

[[TOOL_TABLE]]

[[TOOL_DETAIL]]

### 5.2 Knowledge sources and grounded responses

Each feature has its own corpus of authored CC0 project guidance; current facts come from MCP
tools. Manifests list every source:
[F1](../../student-1/config/rag/corpus.json), [F2](../../student-2/config/rag/corpus.json),
[F3](../../student-3/config/rag/corpus.json), [F4](../../student-4/config/rag/corpus.json),
[F5](../../student-5/config/rag/corpus.json). F1 covers publication and data limits (19
documents); F2 sale matching and case eligibility (3); F3 zero versus missing evidence (8); F4
site-review evidence states (3); F5 case stages, shortlists and tasks (5).

![Figure 3 Versioned ingestion, retrieval and grounding](assets/release-1/rag-pipeline.png)

Passages are embedded locally with BGE-small. Retrieval fuses semantic and keyword ranking,
returns at most five passages (two per document) and drops anything below a 0.55 relevance score.
Retrieved text is treated as untrusted evidence. Confidence is derived from the evidence, not
reported by the model: **high** needs two or more supports (documents or tool results), strong
matches and no gaps; gaps, weaker matches or a single support give **moderate**; **low** marks
stale or conflicting evidence; **insufficient** means no relevant context and carries no
citations.

![Figure 4 Registered knowledge sources in the running application](assets/release-1/screenshots/shared-knowledge-sources.png)

## 6 Validation and results

### 6.1 Terminal validation

On 3 October the [live probe](../release-1/evidence/live-service-probe.json) checked the running
host services directly from a terminal:

```text
$ uv run scripts/dev.py ai probe
MCP: HTTP 200; 29 tools; feature counts 14 / 3 / 4 / 3 / 5
RAG: BAAI/bge-small-en-v1.5 ready; 384 dimensions
Corpora: 19 / 3 / 8 / 3 / 5 documents
Each feature: relevant retrieval PASS; off-topic no_match PASS
Unauthenticated AI-mode / MCP / RAG: HTTP 401
All checks passed.
```

### 6.2 Shared agentic loop

`ai validate mcp` and `ai validate rag` run the production Plan/Act/Observe/Adapt loop against the
live MCP and RAG servers. Model decisions are scripted so each run is repeatable; Section 6.3
shows real model answers. The Release 0 mode remains available.

![Figure 5 Loop entry points and validation modes](assets/release-1/agent-loop-validation.png)

[[LOOP_OUTPUT docs/release-1/evidence/validation-mcp.json]]

[[LOOP_OUTPUT docs/release-1/evidence/validation-rag.json]]

### 6.3 Feature UI, API and persistence

The [live operations record](../release-1/evidence/live-feature-operations.json) checked every
feature on the running stack. F1 and F4 created, changed and deleted a labelled temporary record;
the others report rows in their owning store, including demonstration records.

[[OPERATIONS_TABLE docs/release-1/evidence/live-feature-operations.json]]

Each assistant then answered three questions through its own UI with the live OpenAI provider:
current records via MCP, cited guidance via RAG, and an off-topic question. Captions summarise
each question; full captures show its wording, and run metadata records tool transports.

#### Feature 1 Property data

Full UI captures: [mcp](assets/release-1/screenshots/feature-1-mcp.png), [rag](assets/release-1/screenshots/feature-1-rag.png), [insufficient](assets/release-1/screenshots/feature-1-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-1-rag.json).

![Figure 6 F1 MCP: published datasets and record counts](assets/release-1/screenshots/feature-1-mcp.answer.png)

![Figure 7 F1 RAG: why a sold property can lack sales](assets/release-1/screenshots/feature-1-rag.answer.png)

![Figure 8 F1 cited passage](assets/release-1/screenshots/feature-1-rag.citation.png)

![Figure 9 F1 off-topic: cake oven temperature](assets/release-1/screenshots/feature-1-insufficient.answer.png)

#### Feature 2 Market cases

Full UI captures: [mcp](assets/release-1/screenshots/feature-2-mcp.png), [rag](assets/release-1/screenshots/feature-2-rag.png), [insufficient](assets/release-1/screenshots/feature-2-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-2-rag.json).

![Figure 10 F2 MCP: case eligible sales and median price](assets/release-1/screenshots/feature-2-mcp.answer.png)

![Figure 11 F2 RAG: what the match tier excludes](assets/release-1/screenshots/feature-2-rag.answer.png)

![Figure 12 F2 cited passage](assets/release-1/screenshots/feature-2-rag.citation.png)

![Figure 13 F2 off-topic: password reset](assets/release-1/screenshots/feature-2-insufficient.answer.png)

#### Feature 3 Suburb analytics

Full UI captures: [mcp](assets/release-1/screenshots/feature-3-mcp.png), [rag](assets/release-1/screenshots/feature-3-rag.png), [insufficient](assets/release-1/screenshots/feature-3-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-3-rag.json).

![Figure 14 F3 MCP: crime methodology and rate rules](assets/release-1/screenshots/feature-3-mcp.answer.png)

![Figure 15 F3 RAG: recorded zero versus missing](assets/release-1/screenshots/feature-3-rag.answer.png)

![Figure 16 F3 cited passage](assets/release-1/screenshots/feature-3-rag.citation.png)

![Figure 17 F3 off-topic: cake oven temperature](assets/release-1/screenshots/feature-3-insufficient.answer.png)

#### Feature 4 Due diligence

Full UI captures: [mcp](assets/release-1/screenshots/feature-4-mcp.png), [rag](assets/release-1/screenshots/feature-4-rag.png), [insufficient](assets/release-1/screenshots/feature-4-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-4-rag.json).

![Figure 18 F4 MCP: the review's recorded evidence](assets/release-1/screenshots/feature-4-mcp.answer.png)

![Figure 19 F4 RAG: evidence-state meanings](assets/release-1/screenshots/feature-4-rag.answer.png)

![Figure 20 F4 cited passage](assets/release-1/screenshots/feature-4-rag.citation.png)

![Figure 21 F4 off-topic: password reset](assets/release-1/screenshots/feature-4-insufficient.answer.png)

#### Feature 5 Buyer workspace

Full UI captures: [mcp](assets/release-1/screenshots/feature-5-mcp.png), [rag](assets/release-1/screenshots/feature-5-rag.png), [insufficient](assets/release-1/screenshots/feature-5-insufficient.png). [Run metadata](assets/release-1/screenshots/feature-5-rag.json).

![Figure 22 F5 MCP: case budget, suburbs and shortlist](assets/release-1/screenshots/feature-5-mcp.answer.png)

![Figure 23 F5 RAG: journey stages and shortlists](assets/release-1/screenshots/feature-5-rag.answer.png)

![Figure 24 F5 cited passage](assets/release-1/screenshots/feature-5-rag.citation.png)

![Figure 25 F5 off-topic: cake oven temperature](assets/release-1/screenshots/feature-5-insufficient.answer.png)

### 6.4 Retrieval evaluation

The authored Feature 1 baseline uses a disposable index and the production embedding model.

[[RETRIEVAL_SUMMARY student-1/config/rag/evaluation-baseline-v2.json]]

### 6.5 GitHub Actions

Each workflow builds its feature's images, runs its tests with coverage and smoke-tests the
frontend, API and database in Compose. MCP and RAG stay integrated but disabled; contract tests
use doubles:

```yaml
# .github/workflows/student-1.yml ... student-5.yml
env:
  AI_MODE_MCP_ENABLED: "false"
  AI_MODE_RAG_ENABLED: "false"
```

Student 5's workflow also starts host AI-mode offline with an unreachable provider; MCP and RAG
remain disabled. All six workflows passed on `main` at the report's commit reference on 3 October:

| Workflow | Successful run |
|---|---|
| Student 1 | [37093164388](https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164388) |
| Student 2 | [37093164409](https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164409) |
| Student 3 | [37093164399](https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164399) |
| Student 4 | [37093164366](https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164366) |
| Student 5 | [37093164432](https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164432) |
| Integration | [37093164370](https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164370) |

### 6.6 Docker Compose deployment

The Release 0 `docker-compose.yml` still deploys the whole containerised application. Each
backend now also receives the host MCP and RAG addresses beside AI-mode's, for example:

```yaml
f1-backend:
  environment:
    AI_MODE_BASE_URL: http://host.docker.internal:${AI_MODE_PORT:-5005}
    MCP_SERVER_URL: http://host.docker.internal:${MCP_PORT:-5011}/mcp
    RAG_SERVER_URL: http://host.docker.internal:${RAG_PORT:-5012}
```

Backends call AI-mode, which holds the MCP and RAG credentials; containers receive no MCP or RAG
token. Compose defines no AI-mode, MCP, RAG or loop service. The
[3 October stack status](../release-1/evidence/live-stack-status.txt) shows all 20 containers
running beside the three host processes (extract):

```text
Host AI processes (outside Compose)
  ai-mode  running  http://127.0.0.1:5005
  mcp      running  http://127.0.0.1:5011/mcp
  rag      running  http://127.0.0.1:5012
$ docker compose ... --profile release-0 ps
ps-dev-shared-frontend-1   Up (healthy)   127.0.0.1:5100->8080/tcp
ps-dev-f1-frontend-1       Up (healthy)   127.0.0.1:5200->8080/tcp
ps-dev-f2-frontend-1       Up (healthy)   127.0.0.1:5300->8080/tcp
ps-dev-f3-frontend-1       Up (healthy)   127.0.0.1:5600->8080/tcp
ps-dev-f4-frontend-1       Up (healthy)   127.0.0.1:5400->8080/tcp
ps-dev-f5-frontend-1       Up (healthy)   127.0.0.1:5500->8080/tcp
+ 14 backend, database and worker containers: 12 healthy, 2 workers without healthchecks
```

![Figure 26 CI and local deployment](assets/release-1/ci-and-deployment.png)

## 7 Integration summary

On 3 October one Compose project and one host AI tier served all five features together. Each
reached MCP and its own corpus through its own `/api/<feature>/v1/assistant/turns` backend route,
and its Release 0 page, API and database kept working (6.3).

[[CAPTURE_MATRIX]]

![Figure 27 Cross-feature activity history](assets/release-1/screenshots/shared-activity-history.png)

## 8 Known issues and limitations

- **Local execution only.** AI-mode, MCP, RAG and the loop are host processes on one machine,
  bound to loopback; containers reach them through `host.docker.internal`. They are disabled in CI
  and will not run in the Release 2 cloud deployment.
- **Setup and provider.** First use needs the embedding model and explicit corpus ingestion.
  Answers need a working OpenAI key; without one, feature CRUD still works.
- **Grounding limits.** Corpora are project guidance, not official methodology; confidence
  summarises evidence support rather than proving an answer. Irrelevant passages can pass the
  relevance floor: F2's password question retrieved some, yet correctly returned insufficient
  context.
- **Data.** The [accepted-data snapshot](../release-1/evidence/live-data-status.json) holds real
  G-NAF (5,190,134), PSI sales (7,402,643), BOCSAR (318,122) and SEIFA (4,320) records. Schools
  (10) and fixture properties (3) remain demonstration data. F3 locality coverage is incomplete,
  and F4's sample review uses synthetic, source-attributed records.
- **Open feature defects.** F2 can keep the previous case's chat history after switching cases.
  F4's suggested follow-up questions omit some grounded findings, and one exploratory F4 off-topic
  question failed validation instead of returning insufficient context.
- **Evidence scope.** Captures show selected successful scenarios per feature, not reliability
  across every question.

## 9 Contributions, repository and showcase

[Repository](https://github.com/MattShelton04/41026ASDProject) and
[showcase presentation](https://youtu.be/0Z0Rt146lD0) (public; 9:35 per
[player metadata](../release-1/evidence/showcase-metadata.json)). All five members attended and
participated in the 2 October showcase: Matthew Shelton, Burhan Naeem, James Huang, Michael White
and Derek Song.

### Student 1 Matthew Shelton

| Date | Commit | Release 1 work |
|---|---|---|
| 7 Sep | [1e109ac](https://github.com/MattShelton04/41026ASDProject/commit/1e109ac) | Shared MCP and RAG servers, host runtime, loop validation modes, F1 grounding |
| 19 Sep | [9bc4ee9](https://github.com/MattShelton04/41026ASDProject/commit/9bc4ee9) | Self-service MCP/RAG adoption kit for feature owners |
| 26 Sep | [e7485af](https://github.com/MattShelton04/41026ASDProject/commit/e7485af) | Retrieval and confidence calibration, corpus inspection |
| 3 Oct | [7fc9b29](https://github.com/MattShelton04/41026ASDProject/commit/7fc9b29) | Verified MCP transport, readiness fixes, integration evidence, report |

### Student 2 Burhan Naeem

| Date | Commit | Release 1 work |
|---|---|---|
| 28 Sep | [a1b8577](https://github.com/MattShelton04/41026ASDProject/commit/a1b8577) | Tool allowlist, guidance corpus, capability tool and shared assistant |
| 28 Sep | [d18dfee](https://github.com/MattShelton04/41026ASDProject/commit/d18dfee) | Feature evidence; screenshot-capture fix for all features |
| 1 Oct | [f019e41](https://github.com/MattShelton04/41026ASDProject/commit/f019e41) | Dedicated assistant workspace; refreshed screenshots |

### Student 3 James Huang

| Date | Commit | Release 1 work |
|---|---|---|
| 1 Oct | [da7556c2](https://github.com/MattShelton04/41026ASDProject/commit/da7556c2) | Map displays Feature 1's published data |
| 2 Oct | [b1181cd](https://github.com/MattShelton04/41026ASDProject/commit/b1181cd) | Suburb and crime tools, shared assistant, guidance corpus |
| 2 Oct | [330e65f](https://github.com/MattShelton04/41026ASDProject/commit/330e65f) | Guidance and published locality-context refinements |

### Student 4 Michael White

| Date | Commit | Release 1 work |
|---|---|---|
| 1 Oct | [bbd112d](https://github.com/MattShelton04/41026ASDProject/commit/bbd112d) | Grounded tool allowlist and capabilities MCP tool |
| 1 Oct | [a6b7b7f](https://github.com/MattShelton04/41026ASDProject/commit/a6b7b7f) | Due-diligence guidance corpus |
| 1 Oct | [e0720f4](https://github.com/MattShelton04/41026ASDProject/commit/e0720f4) | Shared grounded assistant in site reviews |
| 1 Oct | [b4cf74a](https://github.com/MattShelton04/41026ASDProject/commit/b4cf74a) | Assistant tests in Feature 4 CI |
| 1 Oct | [7aa69f6](https://github.com/MattShelton04/41026ASDProject/commit/7aa69f6) | MCP, RAG and loop evidence |

Detailed [owner log](../../student-4/docs/release-1-contribution.md).

### Student 5 Derek Song

| Date | Commit | Release 1 work |
|---|---|---|
| 1 Oct | [bb1e3b2](https://github.com/MattShelton04/41026ASDProject/commit/bb1e3b2) | Scoped assistant routes, guidance corpus, cited UI and MCP/RAG evidence |

Detailed [owner log](../../student-5/docs/release-1-contribution.md).

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
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164388
  boundary: Successful push run on main at the report baseline 7fc9b29; MCP/RAG disabled.
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
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164409
  boundary: Successful push run on main at the report baseline 7fc9b29; MCP/RAG disabled.
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
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164399
  boundary: Successful push run on main at the report baseline 7fc9b29; MCP/RAG disabled.
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
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164366
  boundary: Successful push run on main at the report baseline 7fc9b29; MCP/RAG disabled.
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
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/37093164432
  boundary: Successful push run on main at the report baseline 7fc9b29; MCP/RAG disabled.
contributions:
- student: 1
  section: Student 1 Matthew Shelton
  commits:
  - 1e109ac
  - 9bc4ee9
  - e7485af
  - 7fc9b29
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
