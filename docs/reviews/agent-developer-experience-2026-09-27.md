# Agent and developer experience review — 2026-09-27

Status: plan, then implementation record. Scope: agent instructions (`AGENTS.md`), agent skills,
and the `scripts/dev.py` helper. It does not change product behaviour, contracts, or another
student's slice.

## How this review was done

Everything below was exercised on this machine, not inferred from documentation alone:

- Read `README.md`, `CONTRIBUTING.md`, `AGENTS.md`, `scripts/README.md`, the Feature 1 README,
  consumer guide, reference-data runbook, the existing `live-app-browser` skill, `scripts/dev.py`
  and `scripts/devtools/*`.
- Ran the canonical gate on `main`: `uv run python scripts/check.py` passed in **6 min 28 s**.
- Created a fresh detached worktree (`git worktree add --detach ../41026ASDProject-fresh main`),
  ran `uv sync` (11 s), `stack doctor`, and `stack up --offline` with
  `COMPOSE_PROJECT_NAME=ps-fresh` (60 s with cached images).
- Drove Feature 1's data path end to end: `data collect fixture-property` (4 s),
  `data collect schools-master` (real Data.NSW source, 2,210 records, 4 s), then
  `submit-review` and `publish` through the public API, and confirmed the release became
  `accepted` and searchable.
- Checked what agent tools actually load. From each vendor's current docs: Claude Code loads
  skills only from `.claude/skills/` and reads `CLAUDE.md`, not `AGENTS.md`. VS Code Copilot loads
  `.github/skills/`, `.claude/skills/` and `.agents/skills/`. Codex loads `.agents/skills/` and
  reads `AGENTS.md`.

## Findings

### Agent instructions and skills

1. **Claude Code sees neither the instructions nor the skill.** There is no `CLAUDE.md`, and the
   only skill lives in `.github/skills/`, which Claude Code does not scan. Codex also ignores
   `.github/skills/`. Only Copilot currently discovers `live-app-browser`.
2. **`AGENTS.md` is a list of rules without a map.** A new agent has to read three long
   documents to learn the ports, which service owns what, which tests are relevant to a change,
   and that the full gate takes about six and a half minutes. It says nothing about:
   - the difference between a fresh database's seeded demonstration releases and real data. A new
     stack already reports *accepted* `gnaf-nsw`, `nsw-psi-sales`, `bocsar-crime` and schools
     releases, but each has only 10 seeded records. An agent can easily report that as "G-NAF
     is loaded";
   - the human review boundary (agents must not publish a release on their own initiative);
   - how to run a second, isolated stack without touching the developer's data.
3. **No skill covers Feature 1 data.** The knowledge needed to get real data (job names, the
   collect → review → publish flow, the request body fields `version`/`comment`/`approved`, the
   `Idempotency-Key` header, source caches, durations, what "accepted" means) is spread across
   the Feature 1 README, the consumer guide, the OpenAPI file and two runbooks.
4. **The `live-app-browser` skill is good but has gaps.** It lists only ports 5100 and 5200, does
   not mention an isolated stack, and recommends `stack logs`, which never returns (see 8).

### `scripts/dev.py`

5. **The Compose project name is used inconsistently. This can delete data.** Compose honours
   `COMPOSE_PROJECT_NAME`, and a test (`test_no_reload_preserves_explicit_compose_project`) shows
   an isolated project is intended to work. But three code paths hard-code `ps-dev`:
   - `stack reset` runs `docker volume prune --filter label=com.docker.compose.project=ps-dev`.
     Resetting an isolated project would therefore prune the **main** stack's unused volumes;
   - host-port preflight treats only `ps-dev` containers as owned by this stack;
   - `host_runtime.migrate_legacy_state` looks for the `ps-dev` AI history volume. Observed: the
     fresh `ps-fresh` stack printed "Preserved legacy AI run history" and copied the main stack's
     AI run history into the new worktree. The copy was read-only, so no data was lost.
6. **`.env` is loaded for only 6 of the 20 commands.** `stack down/reset/status/logs`,
   `data collect` and `operator report` ignore it. A `COMPOSE_PROJECT_NAME` or port override placed
   in `.env` works for `stack up` but not for `stack reset`, which is the dangerous direction. The
   loader never overrides the shell, so loading it for every command is safe.
7. **`data collect` hard-codes `http://127.0.0.1:5200`** and ignores `PROPERTYSCOPE_PORT`, although
   `operator report` already resolves it.
8. **`stack logs` always follows.** An agent or script that runs it blocks forever, and there is no
   `--tail` option. (`ai logs` already prints and exits.)
9. **The UI fixture port collides with the stack.** `ui serve`, `ui smoke`, `ui audit` and
   `ui readme-screenshots` default to 5300, which is also Feature 2's frontend port. With the stack
   up, `ui serve` fails: "UI fixture port 5300 is unavailable". The error message is clear, but the
   two defaults should not conflict.
10. **Every checkout has its own source cache.** The runner mounts `./.propertyscope-source-cache`,
    so each worktree or fresh clone has to download G-NAF (1.6 GB) and PSI (≈390 MB) again, even when
    another checkout on the same machine already holds verified copies.
11. **Smaller discoverability gaps:**
    - many arguments have no `--help` text (`data collect --timeout/--base-url`, all `ui audit`
      filters, `data sync-psi` flags);
    - the `stack up` summary lists only 5100/5200 and says "small and complete job scopes", which
      is out of date since reduced scopes were removed;
    - `stack doctor` does not report the Compose project, AI placement or host-port availability;
    - running `data collect` or `operator report` against a stopped stack prints a raw socket error
      with no hint to run `stack up`.
12. **`main()` is a 290-line `if/elif` chain.** Handlers share the argument namespace implicitly.
    This makes the script harder to extend, but it is not a user-facing defect.

### Repository hygiene

13. `.gitignore` does not cover Claude Code's local `.claude/settings.local.json` and
    `.claude/worktrees/`, or `playwright-cli`'s `.playwright-cli/` snapshot directory, which the
    browser skill tells agents to create.

## Plan

Each step is a focused commit on `Matt/Agent_Developer_Experience`.

1. **Plan document** (this file).
2. **`fix(dev): honour the selected Compose project everywhere`.** Add one resolver
   (`COMPOSE_PROJECT_NAME` or `ps-dev`) and use it for reset pruning, port preflight and legacy
   AI-state migration. Tests: reset under a custom project prunes only that label, and migration
   ignores other projects.
3. **`feat(dev): make the helper consistent for isolated and agent use`.**
   - Load the optional `.env` (or `--env-file`) for every command, keeping shell precedence.
   - Default `data collect --base-url` from the resolved Feature 1 port.
   - `stack logs --no-follow` and `--tail N`.
   - Move the UI fixture default port to 5700, so it no longer collides with any stack port.
     Update scripts and docs.
   - `PROPERTYSCOPE_SOURCE_CACHE_DIR`: an optional shared host cache directory, used both by the
     runner bind mount and by the PSI cache discovery and `data sync-psi` in `dev.py`.
   - Help text for all arguments; a complete `stack up` URL summary; `doctor` reports the project,
     placement and port state; a clear hint when the stack is not reachable.
   - Tests for each behaviour.
4. **`refactor(dev): dispatch commands through a handler table`.** Behaviour-preserving split of
   `main()` into one function per command. The existing `main([...])` tests are the safety net.
5. **`docs(agents): make instructions and skills discoverable by every agent`.**
   - Add `CLAUDE.md`, which imports `@AGENTS.md`, so there is one source of truth.
   - Move skills to `.claude/skills/`. This is the one directory read by both Claude Code and
     Copilot. Symlinks are avoided because Windows checkouts do not materialise them by default.
     `AGENTS.md` gets a skills index, so Codex and other tools find them too.
   - Restructure `AGENTS.md` around: start here, repository map and ports, the right check for the
     change (targeted commands plus gate duration), running the app, data (seeded versus real, the
     human review boundary), isolated environments, ownership rules, and handoff.
   - Add `scripts/tests/test_agent_skills.py`, which checks that each skill has valid front matter
     with `name` equal to its directory, is listed in `AGENTS.md`, and references repository paths
     that exist, and that `CLAUDE.md` imports `AGENTS.md`.
   - Refresh `live-app-browser` (all ports, isolated stacks, non-following logs).
   - `.gitignore` entries for agent-local files.
6. **`feat(skills): add a Feature 1 data skill`.** Covers checking what is really loaded, the
   job catalogue with sizes and measured durations, collecting, the review and publish API (only
   with the user's explicit approval), source caches, querying the accepted data, recovery, and
   isolated environments.
7. **Documentation alignment.** Update `README.md`, `CONTRIBUTING.md`, `scripts/README.md`, the
   UI fixture docs and the Release 1 handoff reference so the new paths, port and options are
   consistent.
8. **Validation.** Run the full `scripts/check.py`. Then, from a fresh worktree of this branch,
   run an isolated project (`COMPOSE_PROJECT_NAME` in `.env`) with the shared source cache. Collect
   and publish real sources (schools, SEIFA, G-NAF and PSI where time allows), confirm real-address
   search and sale history, confirm that `stack reset` of the isolated project leaves `ps-dev`
   volumes untouched, and then remove the isolated worktree and volumes.

## Deliberately not changed

- **No `data publish` CLI.** The README, the ADRs and `dev.py` all describe human approval before
  publication as an intentional product boundary. The skill documents the existing API and
  requires explicit user approval before an agent calls it.
- **Other students' ports and READMEs.** Feature 2 keeps 5300. The student-3 README sentence that
  says 5300 is shared with the fixture server becomes stale; this is left for its owner.
- **A shared `.claude/settings.json` permission allowlist.** Permission policy is a per-developer
  choice.
- **Port-offset automation for running two stacks at the same time.** Individual port variables
  already exist; the documentation shows how to set them in the isolated checkout's `.env`.

## Implementation record

Filled in after implementation: see the end of this document.
