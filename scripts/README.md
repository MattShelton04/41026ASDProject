# Automation scripts

- `check.py`: the single cross-platform deterministic quality runner. Its `format`, `lint`,
  `architecture`, `styles`, `typecheck`, `compile`, and `test` stages are independently callable;
  no argument runs the complete pre-PR gate. It keeps the 90% shared/AI core threshold separate
  from the 60% Feature 1 ratchet so uncovered feature code cannot hide behind core coverage.
- `dev.py`: grouped stack, UI-fixture, and data-acquisition workflows
- `devtools/`: focused command parsing and shared workflow configuration
- `generate_contracts.py`: generate or drift-check public JSON Schema and OpenAPI snapshots
- `validate_architecture.py`: enforce workspace dependency, Python import, PostgreSQL credential,
  and Compose volume ownership boundaries
- `validate_model_registry.py`: validate supported model metadata, profiles, and budgets
- `validate_tool_catalogs.py`: fail-fast composition check for every feature tool catalogue
- `build/`: shared application and container build automation
- `test/`: shared local and integration test automation
- `deploy/`: Release 2 Azure deployment automation

Scripts should validate and operate the integrated application rather than
deploying isolated student features.

Run `uv run scripts/dev.py --help` for the three workflow groups. The common container loop is
`stack doctor`, `stack up`, edit source with automatic reload, and `stack down`. `stack up`
performs a cache-backed image reconciliation, while `stack rebuild` remains available for explicit
targeted rebuilds. `stack up --offline` keeps data workflows available without an OpenAI credential.
Use `uv run python scripts/check.py` for source quality; `dev.py` does not proxy that command.

| Workflow | Actions | Responsibility |
|---|---|---|
| `dev.py stack` | `up`, `build`, `rebuild`, `restart`, `down`, `reset`, `status`, `config`, `doctor`, `logs` | Compose lifecycle, images, diagnostics, and labelled volumes |
| `dev.py ui` | `serve`, `smoke`, `audit {quick,full}` | Deterministic same-origin fixtures and browser validation |
| `dev.py data` | `collect`, `sync-psi` | Registered Feature 1 acquisition and source-cache preparation |
| `check.py` | `format`, `lint`, `architecture`, `styles`, `typecheck`, `compile`, `test` | Deterministic source-quality stages and the aggregate pre-PR gate |

Run `uv run python scripts/check.py --help` for the composable source-quality stages. JavaScript
`compile` uses Node directly against every first-party Shared and Feature 1 browser module; the
checked-in MapLibre vendor module is excluded and behavior tests cover its integration boundary.
`uv run scripts/dev.py stack build` uses only `docker-compose.yml` to build the production-like Release 0
application images and never starts or recreates a container. `stack rebuild` remains the development
build-and-recreate command.

The frontend-only audit loop is `uv run scripts/dev.py ui serve`. It serves Shared and Feature 1 on one
loopback origin with deterministic API fixtures and stops cleanly on Ctrl+C. Run
`uv run scripts/dev.py ui smoke` for the minimal Playwright render/console smoke after installing
Chromium once with `uv run playwright install chromium`. Scenario and port controls are documented
in [`docs/ui/feature-1-fixture-mode.md`](../docs/ui/feature-1-fixture-mode.md).

The resumable interaction audit uses `uv run scripts/dev.py ui audit quick` for the three core
Shared/Property Discovery/Data Operations routes at laptop-wide and mobile widths. Run
`uv run scripts/dev.py ui audit full` for the explicit route/state/four-viewport matrix. Advanced
selectors and stable shard controls are forwarded by both commands; use
`uv run scripts/dev.py ui audit full --help`. Generated JSON, HTML, Markdown, and screenshots stay
under the ignored `.propertyscope-runtime/ui-audit/` tree.

`stack reset` stops the selected stack, removes its declared volumes, and prunes only unused volumes
with that exact Compose project label. Add `--full-data` to reset the isolated source-scale
project; the Git-ignored host source cache is not removed.

`data collect <job> --profile <test|showcase|full-data>` drives the same registered public HTTP path as
the browser: it validates the plan, creates an idempotent durable run, waits by default, and prints
the retained candidate release. Use `--no-wait` for very long source-scale jobs. The command never
publishes a release; human review remains an intentional product safety boundary.

PropertyScope's bounded showcase profile is part of the default stack at
<http://localhost:5200>. Source-scale acquisition is deliberately separate: append
`--full-data` to the relevant `stack` action (`up`, `status`, `logs`, `rebuild`, or `down`). That option adds the
`docker-compose.full-data.yml` overlay and uses an isolated Compose project, so it cannot
silently replace the ordinary showcase database volume.
