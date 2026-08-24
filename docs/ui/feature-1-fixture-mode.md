# Shared and Feature 1 UI fixture mode

## Purpose and safety boundary

The UI fixture host serves the production Shared and Feature 1 frontend source from one origin and
answers their existing public HTTP paths with deterministic contract-shaped data. It does not add a
fixture switch to production JavaScript, change a production API contract, start Docker, open a
database, or require a model credential. The server binds only to `127.0.0.1`, rejects non-loopback
Host headers, disables caching and is not copied into either production frontend image.

This is the browser-audit path. Use `uv run scripts/dev.py stack up [--offline]` when persistence,
service boundaries or the production-like Compose topology are under test.

## One-command startup

After the normal repository dependency install, run:

```text
uv sync --locked --all-packages --all-groups
uv run scripts/dev.py ui serve
```

The command waits for its fixture-only JSON readiness response, prints all three URLs, stays in the
foreground and closes its listener on Ctrl+C or startup failure. It uses port `5300` by default, away from the
canonical Compose ports. Select another loopback port with either
`PROPERTYSCOPE_UI_FIXTURE_PORT=5301` or `--port 5301`.

The canonical paths remain:

```text
Shared              http://127.0.0.1:5300/?scenario=populated#home
Property Discovery  http://127.0.0.1:5300/features/data-platform/?scenario=populated#properties
Data Operations     http://127.0.0.1:5300/features/data-platform/?scenario=populated#overview
Health              http://127.0.0.1:5300/healthz
Fixture readiness   http://127.0.0.1:5300/__ui-fixture__/ready
```

## Deterministic scenarios

Choose the server default with `--scenario <name>` or `PROPERTYSCOPE_UI_SCENARIO`. A URL query such
as `?scenario=empty` selects the scenario for that browser session through a same-origin cookie;
the query stays outside the hash router and requires no component branch. Audit tooling may instead
send `X-PropertyScope-UI-Scenario` when it does not already have a scenario cookie.

| Scenario | Deterministic behavior |
|---|---|
| `populated` | Representative property, source, update, run, release, product and AI-review records. |
| `empty` | Valid zero-result collection and search envelopes; detail fixtures remain addressable. |
| `slow` | API responses wait 1.25 seconds so existing loading states remain observable. |
| `error` | Recoverable `503` Problem Details with a stable request ID. |
| `partial` | Primary content stays populated while overview or optional map/report/evidence calls fail independently. |
| `long-content` | Long names, addresses, status text and markup-like text remain plain content. |
| `large` | Eighty deterministic rows exercise result and table density. |
| `validation-error` | Reads remain populated; writes return a deterministic `422` Problem Details response. |

There is deliberately no permission/read-only scenario. The current product has no approved
authentication or permission contract, so fixture mode does not invent one.

## Real-browser smoke

Install the browser binary once after dependency sync, then run the smoke command. The command
starts and owns a fixture child when port 5300 is free, reuses an already-running fixture host, and
always cleans up a child it started when the browser succeeds or fails.

```text
uv run playwright install chromium
uv run scripts/dev.py ui smoke
uv run scripts/dev.py ui smoke --all-routes
```

The smoke opens Shared Home, a populated Property Discovery search and Data Operations overview at
1440x1000. It fails on a page exception, any console error, a missing route heading or a missing
property result. Missing Chromium and occupied ports produce an actionable error. The broader
command additionally covers Shared status and accepted-release evidence, every populated Feature 1
route family, the shared AI activity detail projection, and the real AI-review submit-to-detail
flow. The broader route/state/viewport audit remains the responsibility of the resumable Prompt 2
harness.

Run that harness with `uv run scripts/dev.py ui audit quick` or
`uv run scripts/dev.py ui audit full`. Its scenario matrix, resume/shard controls, generated
artifacts, severity policy and stateless destructive-action guard are documented in
[`feature-1-audit.md`](feature-1-audit.md).

Feature 1's required form-behavior suite starts its own random-port fixture host and covers every
existing Property Discovery and Data Operations form, including native keyboard submission,
validation focus, retained server failures, duplicate-submit protection and guarded dialog close:

```text
uv run pytest student-1/tests/e2e/test_form_behaviour_playwright.py --no-cov -q
```

The Student 1 workflow installs Chromium and runs this suite as a dedicated required job. The
ordinary repository quality gate excludes it deliberately so source-only checks remain deterministic
on machines that have not installed a browser.

## Compose coordination preflight

`dev.py stack up`, `restart` and `rebuild` validate the final configured host ports before writing the
runtime secret or invoking any Compose build/recreate operation. Empty environment values use the
Compose defaults; invalid, duplicated or externally occupied ports fail with the owning Docker
Compose project/service where available. Containers already owned by the selected Compose project
are allowed so an ordinary repeat startup remains idempotent. Printed URLs use the resolved port
overrides. An occupied port is exempt only when its structured Compose labels identify the exact
project and service currently being started.
