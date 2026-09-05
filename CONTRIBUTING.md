# Contributing

This repository is a Python 3.12 monorepo managed as a `uv` workspace. Every shared service,
shared package, and student slice owns its dependencies in a local `pyproject.toml`; one root
`uv.lock` keeps compatible versions reproducible across Windows, macOS, Linux, and CI.

## Prerequisites

- Git
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/)
- Node.js 20.6 or newer for the dependency-free Shared and feature-interface behavior tests; no npm
  install or browser test stack is required
- Docker Desktop or another Docker Engine with Compose support for container builds,
  integration checks, and the assignment-aligned runtime
- An OpenAI or Gemini API key with access to the configured model profile for live AI-mode
  requests; deterministic tests do not need credentials or internet access

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

1. Create a short-lived branch from `main`.
2. Confirm the directory owner and read its README before editing.
3. Keep changes within one feature or shared concern where practical.
4. Add or update deterministic tests alongside the change.
5. Run the full check command before opening a pull request.
6. Request review from affected owners when shared contracts or infrastructure change.

Never commit `.env`, SQLite files, credentials, logs, or generated runtime data.
Copy the root `.env.example` to the Git-ignored root `.env` for the default local OpenAI setup.
Stack commands load it automatically when present; an explicit `--env-file` selects an alternative
such as `.env.gemini`, and shell variables retain precedence. Use checked-in `.env.example` files
only for documented, non-secret defaults.

## Commands

| Purpose | Command |
|---|---|
| Reproduce the environment | `uv sync --locked --all-packages --all-groups` |
| Run every deterministic pre-PR check | `uv run python scripts/check.py` |
| Check/apply Python formatting | `uv run python scripts/check.py format` / `uv run python scripts/check.py format --write` |
| Lint Python | `uv run python scripts/check.py lint` |
| Validate contracts and architecture | `uv run python scripts/check.py architecture` |
| Validate frontend styles | `uv run python scripts/check.py styles` |
| Type-check canonical Python | `uv run python scripts/check.py typecheck` |
| Syntax-check first-party browser JavaScript | `uv run python scripts/check.py compile` |
| Run deterministic Python and frontend tests | `uv run python scripts/check.py test` |
| Run tests with enforced coverage | `uv run python scripts/check.py` (90% core branch coverage; 60% Feature 1 ratchet) |
| Generate contract artefacts | `uv run python scripts/generate_contracts.py` |
| Generate or drift-check deployment projections | `uv run python scripts/generate_deployment.py` / `uv run python scripts/generate_deployment.py --check` |
| Validate repository boundaries | `uv run python scripts/validate_architecture.py` |
| Validate the model registry | `uv run python scripts/validate_model_registry.py` |
| Validate feature tool catalogues | `uv run python scripts/validate_tool_catalogs.py` |
| Start the AI-mode service | `uv run flask --app ai_mode:create_app run --port 5005` |
| Start the complete reloadable stack | `uv run scripts/dev.py stack up` |
| Start data flows without a live model | `uv run scripts/dev.py stack up --offline` |
| Check Docker and Compose prerequisites | `uv run scripts/dev.py stack doctor` |
| Run a code-driven fixture acquisition | `uv run scripts/dev.py data collect fixture-property` |
| Follow local stack logs | `uv run scripts/dev.py stack logs` |
| Show generated runtime/service state | `uv run scripts/dev.py stack status` |
| Inspect release/publication readiness | `uv run scripts/dev.py operator report` |
| Restart changed workers or runtime configuration | `uv run scripts/dev.py stack restart [service ...]` |
| Rebuild changed container images | `uv run scripts/dev.py stack rebuild` |
| Stop the stack and preserve data | `uv run scripts/dev.py stack down` |
| Delete only this stack's durable data | `uv run scripts/dev.py stack reset` |
| Run the quick Shared/Feature 1 UI audit | `uv run scripts/dev.py ui audit quick` |
| Run the full resumable UI matrix | `uv run scripts/dev.py ui audit full` |
| Build production-like Release 0 images without starting them | `uv run scripts/dev.py stack build` |

The source-only `check.py` stages are cross-platform and require no shell-specific syntax. They do
not install a second frontend dependency tree: the browser code is dependency-free ES modules, so
Node performs syntax and behavior checks directly. The canonical aggregate deliberately excludes
browser tests; install Chromium once and use the separate commands below when changing rendered UI.

For a Shared-only change, run the `format`, `lint`, `styles`, `compile` and relevant Shared Node
tests while iterating, then audit with
`uv run scripts/dev.py ui audit quick --workspace shared --port 5311`. For Property Discovery use
`--workspace feature-1-property-discovery --port 5312`; for Data Operations use
`--workspace feature-1-data-operations --port 5313`. Finish any of those paths with
`uv run python scripts/check.py` before pushing. Ports are examples: each concurrent audit must use
a distinct free loopback port. The required form-behavior browser suite remains separate because it
owns a random fixture port and needs installed Chromium:

```text
uv run pytest student-1/tests/e2e/test_form_behaviour_playwright.py --no-cov -q
```

`Integration CI / Canonical quality gate` is the single required source-quality job. The
path-filtered Student 1 workflow adds only the Chromium form suite and the integrated Shared plus
Feature 1 container check; it does not repeat the whole repository gate or a second shared-image
build on the same pull request. Its working set is limited to Feature 1, agent-core/AI-mode, shared
runtime contracts/frontend assets, Compose/build metadata, workspace manifests, and the exact dev
command used by that check. Compose readiness and a deterministic fixture collection exercise the
service pipeline; a short inline smoke then checks the shared Feature 1 route/proxy and migrated
database schema fingerprint.

AI-mode exposes health endpoints and the versioned `/api/v1/agent-runs`
create/read/cancel/review surface. Enabled feature manifests contribute only their validated,
allowlisted HTTP tool catalogues; disabled placeholders do not enter the runtime registry.

The development command composes the base model, generated enabled-feature projection, and
`docker-compose.dev.yml`. The final overlay bind-mounts source and enables reload without changing
the production-like HTTP or database-ownership boundaries. Frontend edits need only a browser
refresh, and Python HTTP services reload automatically. Long-running workers do not auto-restart
because that could interrupt an active durable job; use targeted `stack restart <service>` when a
worker is idle. Use `stack rebuild <service>` after dependency, lockfile or Dockerfile changes.
Starting the stack does not acquire
official data; each job imports its complete registered source by default through the same durable
review path. PSI can instead create an explicitly partial candidate from completed publisher archive
years; that candidate cannot replace accepted complete history. The label-scoped `reset` removes
stack volumes but preserves the host source cache.

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


## Cross-feature frontend changes

The Shared browser public API and feature-shell contract are documented in
`shared/frontend/browser/README.md`. Use that barrel instead of copying request, abort, polling,
HTML escaping or product-navigation implementations. Feature API adapters, business states and
local screen composition remain feature-owned. A new Shared asset must be available in both the
Docker image and the development bind mounts; a production-only copy is not enough.

Node behavior tests need the repository bootstrap to resolve these shared source assets without
copying or installing them:

```text
node --import ./scripts/frontend-test-bootstrap.mjs --test shared/frontend/browser/browser.test.mjs student-3/tests/frontend.test.mjs
```

The canonical test command supplies this automatically. For rendered shell changes, install the
workspace browser dependencies and Chromium, then run:

```text
uv run playwright install chromium
uv run python -m scripts.ui_feature_smoke --output .propertyscope-runtime/feature-smoke
```

This matrix covers five real feature entrypoints at 320, 390, 768 and 1440 pixels, with empty and
unavailable API fixtures, product-link checks, horizontal-overflow checks, uncaught page errors
and selected mobile dialog/drawer interactions. It is not a live-stack CRUD or provider test.
Use `--feature buyer-workspaces` (or another feature slug) to shard it. `--chromium /path/to/binary`
selects an existing browser.

`--injected-document` is an explicitly weaker DOM/CSS/module test profile for environments where
normal browser navigation is unavailable. It uses `about:blank`, an injected base URL and CORS
headers only in intercepted test responses. It does **not** validate real-origin navigation, CSP,
cookies, service workers, storage persistence or authentication. Do not substitute its result for
the normal-origin smoke or the existing Feature 1 form/e2e suite before merging.

See `docs/reviews/repository-health-review.md` for the September 2026 review, the implemented
changes, outstanding work and the exact validation boundary.
