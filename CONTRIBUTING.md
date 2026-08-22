# Contributing

This repository is a Python 3.12 monorepo managed as a `uv` workspace. Every shared service,
shared package, and student slice owns its dependencies in a local `pyproject.toml`; one root
`uv.lock` keeps compatible versions reproducible across Windows, macOS, Linux, and CI.

## Prerequisites

- Git
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 20 or newer for the dependency-free operations-interface behavior tests; no npm
  install or browser test stack is required
- Docker Desktop or another Docker Engine with Compose support for container builds,
  integration checks, and the assignment-aligned runtime
- An OpenAI API key with access to the configured model for live AI-mode requests; deterministic
  tests do not need credentials or internet access

Do not install project dependencies globally. `uv` creates and maintains `.venv` in the
repository root.

Install `uv` with Astral's official installer if `uv --version` is not recognised:

```powershell
# Windows PowerShell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

```sh
# macOS or Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart the terminal if the installer changes `PATH`, then confirm `uv --version` works.

## First-time setup

From the repository root:

```text
uv python install
uv sync --locked --all-packages --all-groups
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run python scripts/check.py
```

Select `.venv` as the Python interpreter in your editor. The same commands work in PowerShell,
Command Prompt, Bash, and zsh.

## Day-to-day workflow

1. Create a short-lived branch from the team's integration branch.
2. Confirm the directory owner and read its README before editing.
3. Keep changes within one feature or shared concern where practical.
4. Add or update deterministic tests alongside the change.
5. Run the full check command before opening a pull request.
6. Request review from affected owners when shared contracts or infrastructure change.

Never commit `.env`, SQLite files, credentials, logs, or generated runtime data.
Use the checked-in `.env.example` files for documented, non-secret defaults.

## Commands

| Purpose | Command |
|---|---|
| Reproduce the environment | `uv sync --locked --all-packages --all-groups` |
| Run every required local check | `uv run python scripts/check.py` |
| Format Python | `uv run ruff format .` |
| Lint and apply safe fixes | `uv run ruff check --fix .` |
| Type-check every canonical path | `uv run python scripts/check.py` (includes strict mypy over packages, the integration fixture, and typed scripts) |
| Run tests | `uv run pytest` |
| Run tests with coverage | `uv run pytest --cov --cov-report=term-missing` |
| Generate contract artefacts | `uv run python scripts/generate_contracts.py` |
| Validate repository boundaries | `uv run python scripts/validate_architecture.py` |
| Validate the model registry | `uv run python scripts/validate_model_registry.py` |
| Validate feature tool catalogues | `uv run python scripts/validate_tool_catalogs.py` |
| Start the AI-mode service | `uv run flask --app ai_mode:create_app run --port 5005` |
| Start the complete reloadable stack | `uv run scripts/dev.py up` |
| Start data flows without a live model | `uv run scripts/dev.py up --offline` |
| Check Docker and Compose prerequisites | `uv run scripts/dev.py doctor` |
| Follow local stack logs | `uv run scripts/dev.py logs` |
| Rebuild changed container images | `uv run scripts/dev.py rebuild` |
| Stop the stack and preserve data | `uv run scripts/dev.py down` |
| Delete only this stack's durable data | `uv run scripts/dev.py reset` |

The local service exposes health endpoints and the versioned `/api/v1/agent-runs`
create/read/cancel/review surface. Its default feature-tool registry remains empty until
approved feature backends publish their allowlisted tool contracts.

The development command composes `docker-compose.yml`, `docker-compose.integration-test.yml`,
and `docker-compose.dev.yml`. The root model includes the independently built shared shell, and the
final overlay bind-mounts frontend/source files and enables Gunicorn reload
for a short edit-refresh loop while retaining the same service-to-service HTTP and exclusive
database-ownership boundaries used by the production-like stack. PropertyScope source-scale
work requires the explicit `--full-data` option. It adds `docker-compose.full-data.yml` under
an isolated Compose project; ordinary `up` cannot silently enable live acquisition or reuse
the full-data PostgreSQL volume. `up` performs a cache-backed build reconciliation so dependency
changes from a pull cannot silently reuse stale images. `reset [--full-data]` is intentionally
destructive but label-scoped; it does not delete the host-side source cache.

## Dependencies and workspace projects

Add a runtime dependency to the project that actually imports it:

```text
uv add --package ai-mode flask
```

Add a root development dependency only when it is used across the repository:

```text
uv add --dev <package>
```

Commit both the affected `pyproject.toml` and `uv.lock`. CI uses `--locked`, so an uncommitted
resolution change fails instead of silently changing the environment.

When adding a Python project, give it its own `pyproject.toml`, use a `src` layout (or the
documented shared-package `python` layout), and add it to `[tool.uv.workspace].members` at the
root. Application projects that do not yet expose an importable package may set
`tool.uv.package = false`.

## Ownership and integration

Each student owns the frontend, backend/API, database service, tests, and Docker targets under
their `student-N/` directory. Shared code is limited to genuinely cross-cutting contracts,
test helpers, the edge, and AI services.

At runtime a student backend starts an agent run over HTTP. The shared orchestrator can call
that feature's allowlisted backend tools; the backend applies its own business rules and talks
to its own database service. Neither imports the other's implementation, and no service opens
another service's database. ADR-016 grants Feature 1 one PostgreSQL/PostGIS exception: only
its database API and serial loader receive the database URL. Its backend and runner continue
to use HTTP, the PostgreSQL volume is mounted only by PostgreSQL, and its verified artifact
volume is writable only by the runner and read-only at the loader boundary.

## Pull requests and commits

- Use focused, imperative commits such as `test(contracts): reject invalid problem details`.
- Describe the user-visible or architectural effect, validation performed, and any known
  limitations in the pull request.
- Treat changes to `shared/contracts`, workflow files, Compose, and architecture decisions as
  cross-team changes requiring affected-owner review.
- Do not bypass a failing check by weakening quality settings without documenting and reviewing
  the reason.

## Coding-agent workflow

Agents follow the root `AGENTS.md` plus any closer scoped instructions. Give an agent a concrete
goal, owned paths, acceptance criteria, and required checks. Agents should inspect the current
diff before acting, preserve unrelated work, and finish with an evidence-based handoff rather
than assuming that a passing unit test proves integration behaviour.
