# 41026 Advanced Software Development Group Project

Shared repository for the Spring 2026 group project.

The project is PropertyScope NSW. Feature 1, owned by Matthew Shelton, provides its data
operations and property-discovery platform. The repository contains a reproducible Python
workspace, strict shared contracts/test utilities, a
framework-independent bounded agent state machine, and an AI-mode foundation with
SQLite workflow persistence, versioned prompts, OpenAI Responses API integration, an opt-in
Gemini OpenAI-compatible development provider, health and
agent-run APIs, a serial background worker, feature-scoped HTTP tools, resumable safe
events, request idempotency, and human-review gating. Feature 1 is integrated through
independently deployed frontend,
backend, runner, database API/loader and PostgreSQL/PostGIS containers; Features 2–5 remain
unallocated placeholders.

## Team

This scaffold contains the standard five-student workspace structure aligned with the
published course specification and registration requirements.

| Student | Name | Student ID | UTS email | Feature |
|---|---|---|---|---|
| 1 | Matthew Shelton | 24763373 | matthew.n.shelton@student.uts.edu.au | PropertyScope Data Platform and Property Discovery |
| 2 | To be confirmed | To be confirmed | To be confirmed | To be decided |
| 3 | To be confirmed | To be confirmed | To be confirmed | To be decided |
| 4 | To be confirmed | To be confirmed | To be confirmed | To be decided |
| 5 | To be confirmed | To be confirmed | To be confirmed | To be decided |

Each student has an equivalent `student-N/` workspace for their frontend,
backend/API, database, tests, Dockerfile, and ownership notes.

## Release path

| Release | Planned scope |
|---|---|
| Release 0 | Integrated microservices, AI mode/OpenAI, shared agentic loop, Docker Compose, and student CI |
| Release 1 | Release 0 plus MCP, RAG, and grounded AI responses |
| Release 2 | Release 1 plus multi-agent orchestration, advanced testing, and Azure deployment |

MCP, RAG, and multi-agent services are intended for local execution. The course
specification requires these services to remain disabled in the Release 2 cloud
deployment.

## Repository guide

- `.github/workflows/`: executable integration CI plus student and cloud workflow placeholders
- `docs/`: architecture, reports, and release-specific evidence
- `shared/`: contracts, test utilities, the integrated product home/status/evidence surfaces,
  shared agent activity, design assets, and configuration templates
- `student-1/` to `student-5/`: individual feature workspaces
- `ai-services/`: agent-core and AI-mode projects plus later-release service locations
- `scripts/`: shared quality, build, test, and deployment automation
- `docker-compose.yml`: Release 0 AI-mode, remote provider configuration, the bounded PropertyScope Feature
  1 stack, and its exclusive PostgreSQL/PostGIS and artifact-volume boundaries
- `CONTRIBUTING.md`: environment setup, commands, ownership, and pull request workflow
- `AGENTS.md`: durable repository instructions for coding agents
- `docs/architecture/repository-architecture.md`: scaffold plan, architectural
  decisions, AI-assisted process record, and validation evidence
- `docs/architecture/feature-integration-and-experience-contract.md`: canonical feature routes,
  cross-feature data/API flows, shared UI contract, onboarding gates, and integration tests

## Developer quick start

Install `uv` using Astral's official installer.

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

macOS or Linux:

```sh
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the terminal if prompted, verify the installation with `uv --version`, then run:

```text
uv python install
uv sync --locked --all-packages --all-groups
uv run python scripts/check.py
```

See the official [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/)
for alternative installation methods. See [CONTRIBUTING.md](CONTRIBUTING.md) for editor setup,
hooks, dependency changes, ownership boundaries, and the complete developer/agent workflow.

For day-to-day work on the assignment-aligned integration stack, start Docker Desktop and run:

```text
uv run scripts/dev.py stack up
```

Export `OPENAI_API_KEY` in the launching shell before starting the complete stack. The development
command atomically materialises it into a Git-ignored runtime file and Compose mounts that file only
into AI-mode as a service-scoped secret. The value never enters rendered configuration, the
container environment, or an image. To work on deterministic data flows without an API key, use
`uv run scripts/dev.py stack up --offline`; AI calls are unavailable, but Feature 1 remains operational.

For Gemini development, create a Git-ignored `.env.gemini` with `AI_MODE_LLM_PROVIDER=gemini`,
`GEMINI_API_KEY`, and `AI_MODE_DEFAULT_MODEL_PROFILE=gemini-development.v1`, then run:

```text
uv run scripts/dev.py stack up --env-file .env.gemini
```

The helper still converts the credential to a service-scoped Compose file secret. Select
`gemini-quality.v1` only for an intentional Gemini 3.7 quality/cost comparison.

Then open the unified PropertyScope home at <http://localhost:5100> or Feature 1 at
<http://localhost:5200>.
The shared home also exposes live implemented-service status at
<http://localhost:5100/#system-status>, bounded evidence references at
<http://localhost:5100/#evidence>, and the honest deployment capability roadmap at
<http://localhost:5100/#release-roadmap>.
Python services reload when source changes and the frontends are bind-mounted. Each `stack up` asks
BuildKit to reconcile images, so a newly pulled lockfile or Dockerfile cannot leave stale local
images; unchanged layers remain cached. Use `stack rebuild [service ...]` for an explicit targeted
rebuild. The `stack` group owns lifecycle and diagnostics; `ui` owns fixture/browser work; `data`
owns acquisition. Source checks remain under `uv run python scripts/check.py`. `stack down`
preserves AI-mode run history and PropertyScope data/artifacts, while `stack reset` deletes only
volumes labelled for the selected Compose project.

The local stack is named `ps-dev`. Its generated containers group shared services as
`ps-dev-shared-*` and Feature 1 services as `ps-dev-f1-*`; the isolated source-scale stack uses
`ps-full`. Compose owns the final replica suffix so parallel projects and scaling remain available.

For browser/UI work that does not need Docker, databases or a model credential, start Shared and
Feature 1 against deterministic same-origin fixtures:

```text
uv run scripts/dev.py ui serve
```

The loopback-only host defaults to <http://127.0.0.1:5300> and prints the Shared, Property Discovery
and Data Operations URLs after its health check passes. Scenario selection, alternate ports and the
Playwright smoke command are documented in
[`docs/ui/feature-1-fixture-mode.md`](docs/ui/feature-1-fixture-mode.md).
Run `uv run scripts/dev.py ui audit quick` for the deterministic laptop/mobile interaction gate or
`uv run scripts/dev.py ui audit full` for the explicit route/state/four-viewport matrix. Resume,
shard, severity and artifact details are in
[`docs/ui/feature-1-audit.md`](docs/ui/feature-1-audit.md).

The default PropertyScope stack uses deterministic showcase data and never launches live or
source-scale acquisition. The explicit full-data path uses a separate Compose project and
therefore a separate PostgreSQL volume. It connects official schools, BOCSAR, G-NAF and PSI
acquisition. PSI uses optional unmodified annual archives under `.propertyscope-source-cache/psi/`
and acquires missing annual/current-weekly partitions with validated bounded requests. Complete
history streams every record from 1990 onward and never substitutes synthetic data:

```text
uv run scripts/dev.py data sync-psi --all
uv run scripts/dev.py stack up --full-data
uv run scripts/dev.py stack down --full-data
```

To reproduce a clean full-data deployment without deleting items in Docker Desktop manually:

```text
uv run scripts/dev.py stack reset --full-data
uv run scripts/dev.py stack up --full-data --offline
```

Collection does not require browser interaction. For example, the following command validates the
registered plan, queues the official schools acquisition, waits for the durable runner/loader
pipeline, and reports its candidate release:

```text
uv run scripts/dev.py data collect schools-master --profile full-data
```

Acquisition and candidate generation are automatic. Publication is deliberately not automatic:
the accepted-data pointer changes only after explicit human review and approval.

See [student-1/README.md](student-1/README.md) for the operator workflow, release-scoped dataset
preview, optional local G-NAF cache, real-source status and shared AI-mode boundary.

For the production-like Release 0 container runtime without development bind mounts, run:

```text
OPENAI_API_KEY=<set-in-your-shell>
OPENAI_API_KEY_FILE=<path-to-a-local-file-containing-that-key>
docker compose --profile release-0 up --detach --build --wait --wait-timeout 120 shared-ai-mode
uv run ai-mode-provider-smoke
```

Compose starts AI-mode without a local model runtime; the installed diagnostic performs a
real structured-output and model-access check against OpenAI. Secret handling, configuration,
lifecycle commands, and troubleshooting are documented in
[`docs/release-0/openai-api-operations.md`](docs/release-0/openai-api-operations.md).

For the shared read-only AI-mode operations dashboard, set
`AI_MODE_OPERATIONS_ENABLED=true` in the local environment or `.env`, start AI-mode, and open
<http://localhost:5005/operations/ai-mode/>. The feature flag is false by default and removes
the dashboard plus its list/evidence API routes when disabled. The implementation and
remaining remote-access decisions are documented in
[`docs/release-0/ai-mode-operations-interface-plan.md`](docs/release-0/ai-mode-operations-interface-plan.md).

## Remaining allocation decisions

The team should confirm its membership and project approval with the tutor, allocate Features
2–5, retain a durable link/copy of the confirmed tutor approval for Feature 1's
PostgreSQL/PostGIS exception, and confirm the eventual Azure-or-AWS provider. Features 2–5 retain
independent stores and never receive Feature 1 database credentials.
