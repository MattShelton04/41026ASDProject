# Repository instructions for coding agents

## Start here

1. Read `README.md`, `CONTRIBUTING.md`, and the relevant area README.
2. Read `docs/architecture/shared-platform-design.md` before changing service boundaries,
   contracts, persistence, orchestration, or deployment.
3. Inspect `git status` before editing. Preserve unrelated and user-authored changes.
4. Work only in the requested scope. Do not fill undecided product requirements with
   invented domain behaviour.
5. Treat the root README and living architecture documents as current guidance. Historical
   scaffold/review records preserve point-in-time evidence and are not current build plans.

## Ownership and boundaries

- An allocated `student-N/` slice is owned by its named student; unallocated slices remain
  placeholders. Do not edit another student's assigned feature without explicit coordination.
- Student backends may import `shared_contracts`; tests may import `shared_testkit`.
- Student services must not import another student's code or `agent_core`.
- Student backends call `ai-mode` over HTTP. `ai-mode` may call allowlisted feature tool
  endpoints, but it must never access a student's database directly.
- Each database file has one owning database service. Do not mount or open it elsewhere.
- Keep shared packages domain-neutral. Feature-specific entities and business rules stay in
  their owning student slice.
- `scripts/validate_architecture.py` makes these dependency/import rules executable and runs
  inside the canonical quality gate. Update its tests with any approved boundary change.

## Canonical commands

```text
uv sync --locked --all-packages --all-groups
uv run python scripts/check.py
uv run pytest
uv run flask --app ai_mode:create_app run --port 5005
uv run scripts/dev.py stack up
```

Use `uv run scripts/dev.py stack up` for the complete local Docker workflow. Source-only Python and
frontend changes reload through `docker-compose.dev.yml`; use `uv run scripts/dev.py stack rebuild`
after dependency, lockfile, or Dockerfile changes. The `stack` group also owns `status`, `logs`,
`restart`, and `down`; source quality remains under `uv run python scripts/check.py`. Ordinary
`stack down` preserves named volumes and therefore AI-mode run history and fixture records.

Use `uv add --package <project-name> <dependency>` to change dependencies, and commit the
resulting `pyproject.toml` and `uv.lock` together. Do not hand-edit `uv.lock`.

## Change standards

- Target Python 3.12 and add type annotations to production Python.
- Use application factories for Flask services and dependency injection at boundaries.
- Prefer small modules, explicit contracts, and deterministic tests. Do not hide network,
  model, clock, randomness, or filesystem access in domain logic.
- Use structured errors and the shared request/run correlation conventions.
- Never commit secrets, local databases, model weights, generated caches, or private
  reasoning traces.
- Update architecture documentation or add an ADR when a change alters a recorded decision.
- Add tests for changed behaviour. Tests must not require OpenAI credentials, Docker, Azure, or internet
  access unless explicitly marked as integration/evaluation tests.

## Before handing off

Run `uv run python scripts/check.py`. Report the checks run, any checks not run, and all
remaining assumptions. Keep commits focused and use an imperative Conventional Commit-style
message such as `feat(agent-core): add run transition policy`.
