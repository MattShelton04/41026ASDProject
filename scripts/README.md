# Automation scripts

- `check.py`: the single cross-platform deterministic quality runner. Its `format`, `lint`,
  `architecture`, `styles`, `typecheck`, `compile`, and `test` stages are independently callable;
  no argument runs the complete pre-PR gate. It keeps the 90% shared/AI core threshold separate
  from the 60% Feature 1 ratchet so uncovered feature code cannot hide behind core coverage.
- `dev.py`: grouped stack, UI-fixture, and data-acquisition workflows
- `devtools/`: focused command parsing and shared workflow configuration
- `generate_contracts.py`: generate or drift-check public JSON Schema and OpenAPI snapshots
- `generate_deployment.py`: generate or drift-check explicitly enabled feature projections
- `validate_architecture.py`: enforce workspace dependency, Python import, PostgreSQL credential,
  and Compose volume ownership boundaries
- `validate_model_registry.py`: validate supported model metadata, profiles, and budgets
- `validate_tool_catalogs.py`: fail-fast composition check for every feature tool catalogue
- `validate_workspace_packaging.py`: keep uv workspace/lock membership and Docker manifest inputs aligned
- `live_nginx_recreation.py`: live gate that recreates only Feature 1's backend and proves port 5200 recovers
- `ui_fixture_server.py` and `ui_fixtures.py`: deterministic same-origin Shared/Feature 1 browser
  fixtures used by local UI work, audits, and Playwright tests
- `ui_smoke.py`: the minimal browser render/console smoke
- `readme_screenshots.py`: deterministic 1440x1000 captures embedded in the root README
- `ui_audit/`: the resumable route, state, control, and viewport interaction audit

Scripts should validate and operate the integrated application rather than
deploying isolated student features. Empty future `build`, `test`, and `deploy` scaffolds are not
kept here; add an owned executable only when a release needs it.

Run `uv run scripts/dev.py --help` for the workflow groups. The common container loop is
`stack doctor`, `stack up`, edit source with automatic reload, and `stack down`. `stack up`
reuses healthy containers and builds only missing images. Use `stack up --build` or targeted
`stack rebuild` after Docker or dependency inputs change. `stack up --offline` keeps data workflows
available without an OpenAI credential.
For long data jobs, `stack up --no-reload --build --offline` uses built images without development
source mounts or reload polling. It keeps the same project and durable volumes. Source edits then
require rebuilding images; plain `stack up` returns to automatic development reload. The option is
per invocation, and `stack rebuild`/`stack restart` retain their development behavior. Start or
switch modes before queueing work so worker recreation does not interrupt an active job.
Use `uv run python scripts/check.py` for source quality; `dev.py` does not proxy that command.

Every `dev.py` command loads the optional root `.env` (or `--env-file` where offered)
without overriding shell variables. The Compose project is `COMPOSE_PROJECT_NAME` (default
`ps-dev`); `reset`, port preflight and legacy AI-state migration act only on that project's
labels. Host ports follow the `*_PORT` variables that `stack doctor` lists, and
`data collect`/`operator report` derive the Feature 1 URL from `PROPERTYSCOPE_PORT`. The
runner's read-only source cache is `PROPERTYSCOPE_SOURCE_CACHE_DIR` (default
`./.propertyscope-source-cache`), so worktrees can share one verified G-NAF/PSI download.
`stack logs --no-follow` prints recent lines and exits, for scripts and coding agents.

| Workflow | Actions | Responsibility |
|---|---|---|
| `dev.py stack` | `up`, `build`, `rebuild`, `restart`, `down`, `reset`, `status`, `config`, `doctor`, `logs [--no-follow] [--tail N]` | Compose lifecycle, reload, images, diagnostics, and labelled volumes |
| `dev.py ui` | `serve`, `smoke`, `readme-screenshots`, `audit {quick,full}` | Deterministic same-origin fixtures, README captures, and browser validation |
| `dev.py data` | `collect`, `sync-psi` | Registered Feature 1 acquisition and source-cache preparation |
| `dev.py operator` | `report` | Read-only release, publication, activation, and dependency evidence |
| `check.py` | `format`, `lint`, `architecture`, `styles`, `typecheck`, `compile`, `test` | Deterministic source-quality stages and the aggregate pre-PR gate |

Run `uv run python scripts/check.py --help` for the composable source-quality stages. JavaScript
`compile` uses Node directly against first-party `.js`, `.mjs` and `.cjs` modules under Shared,
all student frontends and `scripts/`. Vendor and dependency directories are excluded. Shared
`*.test.js`, `*.test.mjs` and `*.test.cjs` behavior tests are discovered automatically; enabled
feature tests remain selected by their owned manifests. Unrelated quality stages do not discover
JavaScript or feature test inputs.
`uv run scripts/dev.py stack build` uses the reviewed base Compose model plus the generated enabled-
feature overlay to build the production-like Release 0 application images; it excludes the development
bind-mount overlay and never starts or recreates a container. `stack rebuild` remains the development
build-and-recreate command.

The frontend-only audit loop is `uv run scripts/dev.py ui serve`. It serves Shared and Feature 1 on one
loopback origin with deterministic API fixtures and stops cleanly on Ctrl+C. Run
`uv run scripts/dev.py ui smoke` for the minimal Playwright render/console smoke after installing
Chromium once with `uv run playwright install chromium`. Scenario and port controls are documented
in [`docs/ui/feature-1-fixture-mode.md`](../docs/ui/feature-1-fixture-mode.md).

Refresh the three committed root README images with
`uv run scripts/dev.py ui readme-screenshots`. The command owns or reuses the loopback fixture host,
waits for each populated route's readiness marker, and captures every image at the same 1440x1000
light-theme viewport.

The resumable interaction audit uses `uv run scripts/dev.py ui audit quick` for the three core
Shared/Property Discovery/Data Operations routes at laptop-wide and mobile widths. Run
`uv run scripts/dev.py ui audit full` for the explicit route/state/four-viewport matrix. Advanced
selectors and stable shard controls are forwarded by both commands; use
`uv run scripts/dev.py ui audit full --help`. Generated JSON, HTML, Markdown, and screenshots stay
under the ignored `.propertyscope-runtime/ui-audit/` tree.

`stack reset` stops the local stack, removes its declared volumes, and prunes only unused volumes
with that exact Compose project label. The Git-ignored host source cache is not removed.

`data collect <job>` drives the same registered public HTTP path as the browser: it requests the
complete registered source, validates the plan, creates an idempotent durable run, waits by default,
and prints the retained candidate release. The synthetic fixture remains fast because its source is
finite. Use `--no-wait` for very long source-scale jobs. The command never publishes a release;
human review remains an intentional product safety boundary.

`operator report` queries only public read endpoints. It lists registered products, accepted
releases, outstanding review/publication prerequisites, durable consumer imports, activations and
optional dependency degradation. When a collection reaches its bounded item ceiling, the report marks
the evidence as possibly partial rather than presenting a truncated count as complete. It never submits
review, publishes, imports, or activates a release.

PropertyScope's official connectors and deterministic finite fixture are available in the default
stack at <http://localhost:5200>. Starting the stack performs no acquisition. Each browser or CLI
job explicitly starts a complete registered-source import and writes candidates through the same
durable database and human-review boundary.

AI-mode, MCP and RAG run only as host processes (ADR-046). `devtools/runtime_settings.py` holds
their port variables and capability modes, `devtools/host_runtime.py` manages their processes and
state, and `devtools/service_auth.py` applies AI-mode's internal proxy authentication. On first
start after upgrading, `host_runtime.retire_container_placement()` removes this Compose project's
old AI containers and projection. `ai validate mcp|rag` runs the agent loop over each protocol
(`release1_validation.py`), and `ai probe` checks the running servers directly
(`release1_probe.py`). Both refuse to run in CI. `ai review multi-agent|testing|cloud`
(`devtools/review/`) collects bounded, hashed Release 2 evidence, reviews it through an AI-mode run
or, with `--deterministic`, the same loop in-process, and writes a report and JSONL validation log;
`ai review decide` records the human release decision.

`collect_ci_evidence.py` records a successful `student-N.yml` run on `main` (URL, SHA, job and
step results, and the endpoint-test JUnit table) in `docs/release-2/evidence/ci/student-N.md`.
It reads through an authenticated `gh` and never triggers or re-runs a workflow; see
[`docs/release-2/evidence/ci/README.md`](../docs/release-2/evidence/ci/README.md).
