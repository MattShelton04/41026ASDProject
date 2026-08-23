# Automation scripts

- `check.py`: cross-platform deterministic formatting, lint, type, Python/frontend test, and
  coverage gate; it keeps the 90% shared/AI core threshold separate from the 60% Feature 1
  ratchet so uncovered feature code cannot hide behind core coverage
- `dev.py`: one-command Compose lifecycle with fast source reloads for the integration stack
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

Run `uv run scripts/dev.py --help` for the local development commands. The common loop is
`doctor`, `up`, edit source with automatic reload, `test`, and `down`. `up` performs a
cache-backed image reconciliation, while `rebuild` remains available for explicit targeted
rebuilds. `up --offline` keeps data workflows available without an OpenAI credential.

The frontend-only audit loop is `uv run scripts/dev.py ui`. It serves Shared and Feature 1 on one
loopback origin with deterministic API fixtures and stops cleanly on Ctrl+C. Run
`uv run scripts/dev.py ui-smoke` for the minimal Playwright render/console smoke after installing
Chromium once with `uv run playwright install chromium`. Scenario and port controls are documented
in [`docs/ui/feature-1-fixture-mode.md`](../docs/ui/feature-1-fixture-mode.md).

The resumable interaction audit uses `uv run scripts/dev.py ui-audit-quick` for the three core
Shared/Property Discovery/Data Operations routes at laptop-wide and mobile widths. Run
`uv run scripts/dev.py ui-audit-full` for the explicit route/state/four-viewport matrix. Advanced
selectors and stable shard controls are available through `uv run python -m scripts.ui_audit
full --help`; generated JSON, HTML, Markdown, and screenshots stay under the ignored
`.propertyscope-runtime/ui-audit/` tree.

`reset` stops the selected stack, removes its declared volumes, and prunes only unused volumes
with that exact Compose project label. Add `--full-data` to reset the isolated source-scale
project; the Git-ignored host source cache is not removed.

`collect <job> --profile <test|showcase|full-data>` drives the same registered public HTTP path as
the browser: it validates the plan, creates an idempotent durable run, waits by default, and prints
the retained candidate release. Use `--no-wait` for very long source-scale jobs. The command never
publishes a release; human review remains an intentional product safety boundary.

PropertyScope's bounded showcase profile is part of the default stack at
<http://localhost:5200>. Source-scale acquisition is deliberately separate: append
`--full-data` to `up`, `status`, `logs`, `rebuild`, or `down`. That option adds the
`docker-compose.full-data.yml` overlay and uses an isolated Compose project, so it cannot
silently replace the ordinary showcase database volume.
