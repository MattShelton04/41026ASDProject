# PropertyScope NSW

A NSW property-research application for Group 20, 41026 Advanced Software Development.
Five owned feature slices share a research shell, strict contracts and a bounded AI assistant.
Release 1 adds registered MCP tools, versioned guidance retrieval, cited answers, confidence
categories and insufficient-context handling.

The tutor-approved project uses Python 3.12 and a `uv` monorepo. Frontends, feature APIs and
owned databases run in Docker Compose. AI-mode, its Plan/Act/Observe/Adapt loop, MCP and RAG
run as host processes. Matthew reconfirmed the tutor's OpenAI and PostgreSQL/PostGIS approval on
3 October 2026. Release 2 adds an Azure deployment (one VM behind a Caddy TLS edge, images in
ACR, secrets in Key Vault, AI tier off by default) and a host Multi-Agent Server. Feature 1's
release review page runs its Planner → Worker → Reviewer → human readiness review through the
shared [multi-agent panel](shared/frontend/multi-agent/README.md); the other features adopt the
same panel and proxy contract.

## Start here

- [Developer workflow](CONTRIBUTING.md): dependencies, tests and contribution commands.
- [Shared platform architecture](docs/architecture/shared-platform-design.md): boundaries and contracts.
- [Release 1 report](docs/reports/release-1-technical-report.md), [submission PDF](docs/reports/submissions/release-1/group-20.pdf) and [submission plan](docs/release-1/submission-plan-2026-10-03.md).
- [Presentation](https://youtu.be/0Z0Rt146lD0): Release 1 showcase, 9 minutes 35 seconds.
- [Release 2 requirements, plan and status](docs/release-2/README.md): requirements, implementation plan, per-feature responsibilities, remaining work and known issues.
- [Azure deployment](deployment/azure/README.md): one-time setup, `deploy.sh` / `dev.py cloud`, costs and teardown ([ADR-048](docs/architecture/decisions/ADR-048-azure-vm-hosting.md)).
- [Agent instructions](AGENTS.md): ownership, safe data operations and required checks.

## Team and features

| Student | Owner / student ID | Feature | Local frontend | Owned storage |
|---|---|---|---|---|
| 1 | Matthew Shelton / 24763373 | [Data Platform and Property Discovery](student-1/README.md) | [5200](http://localhost:5200) | PostgreSQL/PostGIS |
| 2 | Burhan Naeem / 24764134 | [Property Sales Explorer and Market Cases](student-2/README.md) | [5300](http://localhost:5300) | SQLite |
| 3 | James Huang / 24970865 | [Suburb, Crime and Liveability Analytics](student-3/README.md) | [5600](http://localhost:5600) | SQLite |
| 4 | Michael White / 24846267 | [Site, Planning and Building Due Diligence](student-4/README.md) | [5400](http://localhost:5400) | PostgreSQL/PostGIS |
| 5 | Derek Song / 24833978 | [Buyer Journey and Agent Workspace](student-5/README.md) | [5500](http://localhost:5500) | SQLite |

The [shared home](http://localhost:5100) links all five features. Their edge routes and ports
come from [enabled-features.v1.json](deployment/enabled-features.v1.json), generated from the
feature manifests. Each backend accesses its own database service; cross-feature data travels
through HTTP contracts. See the [registered scope](docs/architecture/registered-feature-scope.md).

## Run the local application

Install Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 20.6 or newer,
and Docker Desktop with Compose. Run commands from the repository root:

```text
uv python install
uv sync --locked --all-packages --all-groups
```

Create the ignored environment file once and configure the approved model provider:

```powershell
Copy-Item .env.example .env
# Set OPENAI_API_KEY in .env, then start Docker Desktop.
uv run scripts/dev.py stack doctor
uv run scripts/dev.py stack up
uv run scripts/dev.py stack status
```

`stack up` starts the host AI tier before the feature containers and builds missing images.
It does not acquire datasets, prepare a model or ingest corpora. Shell variables override `.env`.
Use `stack up --offline` for ordinary feature/database development without a provider key;
that starts direct AI-mode with provider readiness optional and leaves MCP/RAG stopped.
Offline mode does not generate real model answers.

| Host component | URL | Purpose |
|---|---|---|
| Shared edge | <http://localhost:5100> | Home, feature proxy and operations pages |
| AI-mode | <http://127.0.0.1:5005> | Token-protected run API and loop worker |
| MCP | <http://127.0.0.1:5011/mcp> | Streamable HTTP over 29 registered feature tools |
| RAG | <http://127.0.0.1:5012> | Local embeddings, corpus versions and cited retrieval |
| Multi-Agent Server | <http://127.0.0.1:5013> | Planner, Worker, Reviewer and human-decision workflows ([README](ai-services/multi-agent-server/README.md)) |

Containers reach AI-mode and the Multi-Agent Server through `host.docker.internal`. AI-mode
calls MCP/RAG on loopback; MCP calls allowlisted feature HTTP endpoints. The chat agent loop is
inside AI-mode; the Multi-Agent Server is the separate Release 2 workflow service, whose Worker
uses the same MCP tools.
Provider credentials, service tokens, histories, index and model cache stay in the ignored
`.propertyscope-runtime/` host directory. Tokens never belong in browser code or Git.

## Prepare all five guidance corpora

Semantic retrieval needs an explicit model preparation and ingestion step. The default model
is `BAAI/bge-small-en-v1.5`, with 384 dimensions. Preparation may download model assets;
ordinary startup does not.

```text
uv run rag-server prepare-model
uv run scripts/dev.py ai stop rag
uv run scripts/dev.py ai start --mode combined
```

In PowerShell, load the managed ingestion token without printing it, then ingest each registered
manifest. If `RAG_SERVICE_TOKEN` was configured explicitly, keep that configured value instead.

```powershell
$env:RAG_SERVICE_TOKEN = (Get-Content -Raw .propertyscope-runtime/host/rag.token).Trim()
uv run rag-server ingest student-1/config/rag/corpus.json
uv run rag-server ingest student-2/config/rag/corpus.json
uv run rag-server ingest student-3/config/rag/corpus.json
uv run rag-server ingest student-4/config/rag/corpus.json
uv run rag-server ingest student-5/config/rag/corpus.json
uv run scripts/dev.py ai probe
```

The manifests currently contain 19/3/8/3/5 authored guidance documents. They explain feature
behaviour and limits; live property facts come from owned backend tools. Ingestion creates an
immutable corpus version. Identical replay preserves it; replacement can withdraw omitted documents.
The [host runtime guide](docs/release-1/host-runtime.md) covers POSIX shells, tokens, provider
profiles and diagnostics. Feature 3's optional generated official-context corpus has separate
publication prerequisites; its registered guidance manifest works without those datasets.

Inspect [Knowledge sources](http://localhost:5100/operations/ai-mode/knowledge/) for passages
and retrieval rankings, and [Activity history](http://localhost:5100/operations/ai-mode/) for
public run evidence. Grounded production runs use `default.v9` where eligible; ungrounded runs
retain `default.v7`. Named validation modes use deterministic decisions against live services:

```text
uv run scripts/dev.py ai validate mcp
uv run scripts/dev.py ai validate rag
```

These commands establish transport and loop execution. Assess provider answers separately through
the owning feature UI. Citations identify supporting passages; confidence is an evidence category,
not an accuracy probability. Off-topic or unavailable context should produce an explicit refusal.

## Data and publication

A fresh stack contains labelled seeded demonstrations, not complete official sources. The current
local evidence snapshot has real accepted G-NAF, PSI, BOCSAR and SEIFA data alongside demonstration
schools and fixture properties. That snapshot does not describe a new checkout's volumes.
Check your own stack before making any loaded-data claim:

```text
uv run python .github/skills/feature-1-data/data_status.py
uv run scripts/dev.py operator report
```

Acquisition is explicit, for example `uv run scripts/dev.py data collect schools-master`.
It ends at a reviewable candidate. Publication requires checking counts, quality and provenance;
it makes that candidate current. Pending spatial/reference candidates are not accepted data.
See [Feature 1 operations](student-1/README.md), the
[data consumer guide](student-1/DATA_PRODUCT_CONSUMER_GUIDE.md) and the
[data skill](.github/skills/feature-1-data/SKILL.md). Starting a stack never publishes a release.

## Develop and verify

```text
uv run python scripts/check.py
uv run scripts/dev.py --help
```

The canonical gate checks formatting, lint, generated contracts/deployment, architecture,
packaging, model configuration, frontend code, typing and tests with configured coverage.
Choose the focused command in [CONTRIBUTING.md](CONTRIBUTING.md) while iterating, then run the
full gate before handoff. Tests use deterministic doubles without provider credentials.
Student workflows build and smoke their owned services with MCP/RAG disabled. Student 5 currently
starts offline direct AI-mode; the submission plan records the owner's CI follow-up.

| Task | Command |
|---|---|
| Diagnose ports, Docker and host services | `uv run scripts/dev.py stack doctor` |
| Read recent container logs | `uv run scripts/dev.py stack logs --no-follow f1-backend` |
| Read host AI logs | `uv run scripts/dev.py ai logs ai-mode mcp rag` |
| Stop and preserve data | `uv run scripts/dev.py stack down` |
| Rebuild after dependency/Dockerfile changes | `uv run scripts/dev.py stack rebuild` |
| Verify live service contracts | `uv run scripts/dev.py ai probe` |
| Capture verified live assistant evidence | `uv run python scripts/capture_release1_screenshots.py` |
| Capture safe UI/API/persistence evidence | `uv run python scripts/capture_release1_integration.py --project ps-dev --output Temp/live-feature-operations.json` |
| Check report readiness | `uv run python scripts/build_release1_report.py --status` |

Frontend edits reload after a browser refresh; feature Python services reload in the development
stack. After AI-service Python changes, stop the affected host service and restart combined mode.
Run `stack up` after token/environment changes. Use a separate Compose project and ports for
isolated experiments; [AGENTS.md](AGENTS.md) explains worktrees, cache reuse and cleanup.
`stack reset` deletes the selected project's volumes and is only for an explicitly disposable stack.

## UI fixtures and visual evidence

Shared and Feature 1 also run with deterministic same-origin fixtures:

```text
uv run scripts/dev.py ui serve
uv run scripts/dev.py ui audit quick
uv run scripts/dev.py ui visual
```

Fixture pages at <http://127.0.0.1:5990> need no Docker or model credential. Their screenshots
verify layout and browser behaviour; they do not prove live MCP/RAG or database integration.
See [fixture mode](docs/ui/feature-1-fixture-mode.md),
[visual regression](docs/ui/visual-regression.md) and the
[Fieldbook design record](docs/deliverables/propertyscope-ux-overhaul/00_EXECUTIVE_SUMMARY.md).

![PropertyScope research workspace using deterministic fixture data](docs/images/readme/propertyscope-home.png)

![Property search using deterministic fixture data](docs/images/readme/property-search.png)

![Data overview using deterministic fixture data](docs/images/readme/data-overview.png)

Refresh the README image set with `uv run scripts/dev.py ui readme-screenshots`. Release 1 evidence
uses actual local services and allowlisted public run projections; inspect every captured image.

## Repository map and delivery limits

| Directory | Contents |
|---|---|
| `student-1/` … `student-5/` | Owned feature microservices, schemas, tools, corpora and tests |
| `ai-services/` | Host AI-mode, deterministic agent core, MCP and RAG |
| `shared/` | Contracts, HTTP/tool runtime, testkit and common frontend packages |
| `deployment/` | Feature selection, generated Compose/routes and the Azure IaC, scripts and edge (`deployment/azure/`) |
| `scripts/` | Quality gates, runtime, data operations and evidence capture |
| `docs/` | Living architecture, reports and dated evidence |
| `.github/workflows/` | Assigned feature CI, integration, visual checks and the gated Azure deployment |

The current evidence covers selected working paths across all five slices. Owner follow-ups
include Feature 2 context switching, Feature 4's native generated-question renderer and Feature 5's
CI startup. Official locality/spatial coverage is incomplete; missing evidence is not clearance or
zero. The [submission plan](docs/release-1/submission-plan-2026-10-03.md) records these limits and
remaining delivery tasks. [docs/README.md](docs/README.md) indexes maintained guides; dated reviews
are historical evidence, not current implementation instructions.
