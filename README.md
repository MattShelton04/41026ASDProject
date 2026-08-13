# 41026 Advanced Software Development Group Project

Shared repository for the Spring 2026 group project.

The project is PropertyScope NSW. Feature 1, owned by Matthew Shelton, provides its data
operations and property-discovery platform. The repository contains a reproducible Python
workspace, strict shared contracts/test utilities, a
framework-independent bounded agent state machine, and an AI-mode foundation with
SQLite workflow persistence, versioned prompts, native Ollama integration, health and
agent-run APIs, a serial background worker, feature-scoped HTTP tools, resumable safe
events, request idempotency, and human-review gating. The non-product
`examples/integration-test-feature` proves the shared boundaries over real HTTP and
SQLite and provides a browser integration console at `http://localhost:5190` when its
Compose profile is enabled. Feature 1 is integrated through independently deployed frontend,
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
| Release 0 | Integrated microservices, AI mode/Ollama, shared agentic loop, Docker Compose, and student CI |
| Release 1 | Release 0 plus MCP, RAG, and grounded AI responses |
| Release 2 | Release 1 plus multi-agent orchestration, advanced testing, and Azure deployment |

MCP, RAG, and multi-agent services are intended for local execution. The course
specification requires these services to remain disabled in the Release 2 cloud
deployment.

## Repository guide

- `.github/workflows/`: executable integration CI plus student and cloud workflow placeholders
- `docs/`: architecture, reports, and release-specific evidence
- `shared/`: contracts, test utilities, operations assets, the eventual integrated
  home-page location, and configuration templates
- `student-1/` to `student-5/`: individual feature workspaces
- `ai-services/`: agent-core and AI-mode projects plus later-release service locations
- `scripts/`: shared quality, build, test, and deployment automation
- `docker-compose.yml`: Release 0 AI-mode, profiled Ollama, the bounded PropertyScope Feature
  1 stack, and its exclusive PostgreSQL/PostGIS and artifact-volume boundaries
- `CONTRIBUTING.md`: environment setup, commands, ownership, and pull request workflow
- `AGENTS.md`: durable repository instructions for coding agents
- `docs/architecture/repository-architecture.md`: scaffold plan, architectural
  decisions, AI-assisted process record, and validation evidence

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
uv run scripts/dev.py up
```

Then open PropertyScope at <http://localhost:5200> or the non-product integration fixture at
<http://localhost:5190>. Python services reload when source changes and the frontends are
bind-mounted, so normal source edits do not require an image rebuild. Use
`uv run scripts/dev.py rebuild` after changing dependencies, `uv.lock`, or a Dockerfile;
`status`, `logs`, `test`, `restart`, and `down` cover the rest of the common loop. `down`
preserves Ollama models, AI-mode run history, PropertyScope data/artifacts, and example records.

The default PropertyScope stack uses deterministic showcase data and never launches live or
source-scale acquisition. The explicit full-data path uses a separate Compose project and
therefore a separate PostgreSQL volume:

```text
uv run scripts/dev.py up --full-data
uv run scripts/dev.py down --full-data
```

For the production-like Release 0 container runtime without development bind mounts, run:

```text
docker compose --profile ollama-container up --detach --wait --wait-timeout 120 ollama
docker compose --profile ollama-container run --rm ollama-init
docker compose --profile release-0 up --detach --build --wait --wait-timeout 120 ai-mode
uv run ai-mode-ollama-smoke
```

Compose starts pinned Ollama and AI-mode containers and prepares the small Release 0
model; the installed diagnostic then performs a real structured-output provider check.
Native Ollama, routing choices, resource settings, lifecycle commands, and
troubleshooting are documented in
[`docs/release-0/ollama-operations.md`](docs/release-0/ollama-operations.md).

The helper above previews the non-product integration feature as a working vertical slice.
To reproduce its production-like Compose commands directly, add the integration overlay and
profile:

```text
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile ollama-container up --detach --wait --wait-timeout 120 ollama
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile ollama-container run --rm ollama-init
docker compose --file docker-compose.yml --file docker-compose.integration-test.yml --profile release-0 --profile integration-test up --detach --build --wait --wait-timeout 120 ai-mode integration-test-feature-database integration-test-feature-backend integration-test-feature-frontend
```

Then open <http://localhost:5190>. Detailed behavior and teardown commands are in
[`examples/integration-test-feature/README.md`](examples/integration-test-feature/README.md).

For the shared read-only AI-mode operations dashboard, set
`AI_MODE_OPERATIONS_ENABLED=true` in the local environment or `.env`, start AI-mode, and open
<http://localhost:5005/operations/ai-mode/>. The feature flag is false by default and removes
the dashboard plus its list/evidence API routes when disabled. The implementation and
remaining remote-access decisions are documented in
[`docs/release-0/ai-mode-operations-interface-plan.md`](docs/release-0/ai-mode-operations-interface-plan.md).

## Remaining allocation decisions

The team should confirm its membership and project approval with the tutor, allocate Features
2–5, link the formal approval evidence for Feature 1's PostgreSQL/PostGIS exception, and
confirm the eventual Azure-or-AWS provider. Features 2–5 retain independent stores and never
receive Feature 1 database credentials.
