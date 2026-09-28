# Repository instructions for coding agents

PropertyScope NSW is a Python 3.12 `uv` monorepo: a Shared platform (edge, contracts, AI-mode,
MCP, RAG) plus five independently owned feature slices under `student-N/`. `CLAUDE.md` imports
this file, so every agent reads the same rules.

## Start here

1. Read `README.md`, `CONTRIBUTING.md`, and the README of the area you will change.
2. Read `docs/architecture/shared-platform-design.md` before changing service boundaries,
   contracts, persistence, orchestration, or deployment.
3. Inspect `git status` before editing. Preserve unrelated and user-authored changes.
4. Work only in the requested scope. Do not fill undecided product requirements with invented
   domain behaviour.
5. Treat the root README and living architecture documents as current guidance. Dated
   scaffold/review records are point-in-time evidence, not current build plans.

## Skills

Task-specific procedures live in `.github/skills/<name>/SKILL.md`. GitHub Copilot loads them
automatically. Every other agent (Claude Code, Codex, ...) must open the matching `SKILL.md` before
starting a task that fits one of these rows.

| Skill | Use it when |
|---|---|
| [`live-app-browser`](.github/skills/live-app-browser/SKILL.md) | Checking a change in the running stack: pages, APIs, AI-mode runs, grounded answers, screenshots |
| [`feature-1-data`](.github/skills/feature-1-data/SKILL.md) | Finding out what data is really loaded, collecting official sources, reviewing/publishing releases, querying accepted property data, or preparing an isolated data environment |

Keep a skill's `name` equal to its directory and list every skill here;
`scripts/tests/test_agent_skills.py` enforces both.

## Ownership and boundaries

- An allocated `student-N/` slice is owned by its named student (see the README team table).
  Do not edit another student's feature without explicit coordination.
- Student backends may import `shared_contracts`; tests may import `shared_testkit`.
- Student services must not import another student's code or `agent_core`.
- Student backends call `ai-mode` over HTTP. `ai-mode` may call allowlisted feature tool
  endpoints, but it must never access a student's database directly.
- Each database file has one owning database service. Do not mount or open it elsewhere.
- AI-mode, MCP, RAG and the agent loop run only as host processes (ADR-046). Never add them to a
  Compose file or give `ai-services/` a Dockerfile; backends reach them via `host.docker.internal`.
- Keep shared packages domain-neutral. Feature-specific entities and business rules stay in
  their owning student slice.
- `scripts/validate_architecture.py` enforces these rules inside the quality gate. Update its
  tests with any approved boundary change.

## Where things run

| Service | Host URL | Port variable |
|---|---|---|
| Shared home and edge | <http://localhost:5100> | `PROPERTYSCOPE_SHARED_PORT` |
| Feature 1 Data Platform | <http://localhost:5200> (API `/api/data-platform/v1`) | `PROPERTYSCOPE_PORT` |
| Feature 2 Market Intelligence | <http://localhost:5300> | `PROPERTYSCOPE_MARKET_INTELLIGENCE_PORT` |
| Feature 4 Due Diligence | <http://localhost:5400> | `PROPERTYSCOPE_DUE_DILIGENCE_PORT` |
| Feature 5 Buyer Workspaces | <http://localhost:5500> | `PROPERTYSCOPE_BUYER_WORKSPACES_PORT` |
| Feature 3 Suburb Analytics | <http://localhost:5600> | `PROPERTYSCOPE_SUBURB_ANALYTICS_PORT` |
| AI-mode / MCP / RAG (host processes) | 5005 / 5011 / 5012 | `AI_MODE_PORT` / `MCP_PORT` / `RAG_PORT` |
| Deterministic UI fixtures (`ui serve`) | <http://127.0.0.1:5990> | `PROPERTYSCOPE_UI_FIXTURE_PORT` |

`deployment/enabled-features.v1.json` is the generated source of truth for feature ports and
routes. `uv run scripts/dev.py stack doctor` shows the resolved project, host AI state and which
process owns each port.

## Commands

```text
uv sync --locked --all-packages --all-groups     # reproduce the environment
uv run python scripts/check.py                   # full gate, required before handoff (~6-7 min)
uv run scripts/dev.py stack up [--offline]       # complete Docker stack; --offline needs no model key
uv run scripts/dev.py stack status               # what is running
uv run scripts/dev.py ai probe                   # check the running MCP and RAG servers directly
uv run scripts/dev.py stack logs --no-follow f1-runner   # print recent logs and exit
uv run scripts/dev.py ui visual [--case ID]      # before/after screenshots of a UI change (docs/ui/visual-regression.md)
uv run scripts/dev.py --help                     # every workflow group and option
```

Choose the smallest relevant check while iterating, then run the full gate once:

| Changed | Iterate with |
|---|---|
| Any Python | `uv run python scripts/check.py lint`, `... format --write`, `... typecheck` |
| `scripts/` | `uv run pytest scripts/tests -q` |
| `student-N/` | `uv run pytest student-N/tests -q --ignore-glob="*/tests/e2e/*"` |
| `shared/contracts` | `uv run pytest shared/contracts/tests -q` and `uv run python scripts/generate_contracts.py --check` |
| `ai-services/<svc>` | `uv run pytest ai-services/<svc>/tests -q` |
| Manifests, Compose, boundaries | `uv run python scripts/check.py architecture` |
| Browser JavaScript | `uv run python scripts/check.py compile` then the `node --import ./scripts/frontend-test-bootstrap.mjs --test <files>` command in `CONTRIBUTING.md` |

Bare `pytest` runs do not enforce coverage; `check.py` does (90% shared/AI core, per-feature
thresholds from each `feature.yaml`). Source-only Python and frontend edits reload inside the
stack. After dependency, lockfile, or Dockerfile changes use `uv run scripts/dev.py stack rebuild`.
AI services need `ai stop` then `ai start --mode combined` after their source changes. Change
dependencies with `uv add --package <project-name> <dependency>` and commit `pyproject.toml` with
`uv.lock`; never hand-edit `uv.lock`.

## Data and safety rules

- A fresh database contains a **seeded demonstration baseline**: accepted `gnaf-nsw`,
  `nsw-psi-sales`, `bocsar-crime` and schools releases with about 10 records each, plus a
  fixture property set. That is not real data. Check record counts before claiming a dataset is
  loaded; the `feature-1-data` skill shows how.
- Starting the stack never downloads or publishes data. Acquisition is explicit
  (`uv run scripts/dev.py data collect <job>`) and ends at a reviewable candidate.
- Publishing makes a candidate the current data. Agents may review and publish on the user's
  behalf, which is routine in a local stack when the task needs data. First check the record
  count and quality results, record in the review comment what you checked and for whom, and
  report what you published. Confirm first on shared environments, or before replacing accepted
  data the task did not ask to change.
- Never run `stack reset`, `docker volume rm/prune`, or `docker compose down --volumes` against a
  stack you did not create for the task. `stack down` preserves data; `reset` deletes it.
- Never commit secrets, `.env`, local databases, source caches, model weights, generated runtime
  data, or private reasoning traces.

## Isolated environments

Use a separate worktree and Compose project when you need a clean database or must not disturb
the developer's stack:

```text
git worktree add ../41026ASDProject-scratch
cd ../41026ASDProject-scratch
uv sync --locked --all-packages --all-groups
# In this checkout's .env (dev.py and Compose both read it):
#   COMPOSE_PROJECT_NAME=ps-scratch
#   PROPERTYSCOPE_SOURCE_CACHE_DIR=../41026ASDProject/.propertyscope-source-cache
uv run scripts/dev.py stack up --offline
```

- Every `dev.py` command uses the selected project for volumes, pruning, and port ownership. AI
  history and tokens live in that checkout's `.propertyscope-runtime/`.
- Only one stack can own the default host ports. Stop the other stack first, or set every port
  variable in the table above in the scratch `.env`.
- Built images share the global `propertyscope/<service>:dev` tags. `--build` or `stack rebuild` in
  one checkout replaces the images the other checkout starts next. Rebuild back from the main
  checkout if a branch changed Dockerfiles or dependencies.
- Container names follow `<project>-<service>-1`. Prefer `docker compose exec <service>` through
  the stack commands over hard-coded `ps-dev-...` names.
- Clean up with `uv run scripts/dev.py stack reset` **from the scratch checkout**, then
  `git worktree remove`.

## Change standards

- Target Python 3.12 and add type annotations to production Python.
- Use application factories for Flask services and dependency injection at boundaries.
- Prefer small modules, explicit contracts, and deterministic tests. Do not hide network,
  model, clock, randomness, or filesystem access in domain logic.
- Use structured errors and the shared request/run correlation conventions.
- Update architecture documentation or add an ADR when a change alters a recorded decision.
- Add tests for changed behaviour. Tests must not require OpenAI credentials, Docker, Azure, or
  internet access unless explicitly marked as integration/evaluation tests.

## Before handing off

Run `uv run python scripts/check.py`. Report the checks you ran, any checks you did not run, and
all remaining assumptions. Say which observations came from the live stack and which came from
fixtures or deterministic validation. Keep commits focused and use an imperative Conventional
Commit-style message such as `feat(agent-core): add run transition policy`.
