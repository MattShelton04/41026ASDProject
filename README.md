# 41026 Advanced Software Development Group Project

Shared repository for the Spring 2026 group project.

The project topic and individual features are still to be decided. The repository now
contains a reproducible Python workspace, strict shared contracts/test utilities, a
framework-independent bounded agent state machine, and an AI-mode foundation with
SQLite workflow persistence, versioned prompts, native Ollama integration, health and
agent-run APIs, a serial background worker, feature-scoped HTTP tools, resumable safe
events, request idempotency, and human-review gating. The non-product
`examples/integration-test-feature` proves the shared boundaries over real HTTP and
SQLite. Approved student feature business logic and feature-owned production endpoints
have not begun.

## Team

This scaffold contains the standard five-student workspace structure aligned with the
published course specification and registration requirements.

| Student | Name | Student ID | UTS email | Feature |
|---|---|---|---|---|
| 1 | Matthew Shelton | 24763373 | matthew.n.shelton@student.uts.edu.au | To be decided |
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
- `shared/`: contracts, test utilities, integrated home page, and configuration templates
- `student-1/` to `student-5/`: individual feature workspaces
- `ai-services/`: agent-core and AI-mode projects plus later-release service locations
- `scripts/`: shared quality, build, test, and deployment automation
- `docker-compose.yml`: Release 0 AI-mode and profiled Ollama integration; student
  services are added after feature allocation
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

For the assignment-aligned container runtime, start Docker Desktop and run:

```text
docker compose --profile release-0 --profile ollama-container up --detach --build --wait --wait-timeout 600
uv run ai-mode-ollama-smoke
```

Compose starts pinned Ollama and AI-mode containers and prepares the small Release 0
model; the installed diagnostic then performs a real structured-output provider check.
Native Ollama, routing choices, resource settings, lifecycle commands, and
troubleshooting are documented in
[`docs/release-0/ollama-operations.md`](docs/release-0/ollama-operations.md).

## Next decisions

Before implementation begins, the team should confirm its membership with the
tutor, select and obtain approval for an Agentic AI project topic, allocate one
integrated feature per student, and confirm the planned SQLite and Azure choices.
