# Release 2 handover: Shared and Feature 1, Phase 2 (ephemeral)

> **This file is a temporary handover note, not documentation.** It exists only to let the next
> agent or developer resume the work from branch `release-2/shared-feature-1`.
>
> **Step 0:** read it end to end.
> **Final step:** delete it (`git rm docs/release-2/HANDOVER.md`) in the PR that completes Phase 2,
> and move anything still useful into the permanent docs listed below.

Written 9 October 2026, at commit `cdc35d9` on `release-2/shared-feature-1`.

## 1. What is done (Phase 1)

Every Shared workstream in [`parts/shared.md`](parts/shared.md) is implemented except A8 (the
shared UI panel), Section G (evidence and report) and the actual Azure deployment. Feature 1 has
its endpoint tests and its workflow manifest.

| Area | State | Where |
|---|---|---|
| A. Multi-Agent Server | Done: contracts, state machine, Planner/Worker/Reviewer with model + deterministic providers, SQLite + JSONL audit, HTTP API on :5013, CLI, `dev.py ai` integration, Compose `MULTI_AGENT_*` wiring, `FakeMultiAgentServer`, ADR-047 | `ai-services/multi-agent-server/` (README has API, manifest format and CLI), `shared_contracts.multi_agent`, `shared_testkit.multi_agent` |
| A8. Shared multi-agent UI panel | **Not started (Phase 2)** | `shared/frontend/multi-agent/` |
| B. Review modes | Done: `dev.py ai review {multi-agent,testing,cloud}` and `ai review decide` | `scripts/devtools/review/`, [`review-modes.md`](review-modes.md) |
| C. Pre-commit security | Done: Ruff `S`, detect-secrets, pip-audit hooks, `dev.py security report`, CI job | `.pre-commit-config.yaml`, `scripts/security/`, `evidence/security/` |
| D. Endpoint testing | Done: `endpoint` marker, `shared_testkit.endpoints`, JUnit summary, `scripts/collect_ci_evidence.py` | `shared/testkit/README.md`, `evidence/ci/README.md` |
| E/F. Azure | Prepared, **not provisioned**: Bicep, `docker-compose.azure*.yml`, `deploy.sh`, `dev.py cloud`, `cloud_smoke.py`, gated `cloud-deployment.yml`, Caddy/nginx hardening, systemd AI units, validation scripts, ADR-048 | `deployment/azure/README.md` (one-time setup checklist) |
| F1 endpoint tests (F-7) | Done; `student-1.yml` runs them against 5200 and the edge with JUnit artifacts | `student-1/tests/endpoints/` |
| F1 workflow manifest (F-2) | Done: `f1-release-readiness-review` (2 read-only steps, 9 reviewer checks, never publishes) | `student-1/config/multi-agent/workflow.yaml` |
| F1 terminal workflow evidence (F-5, terminal half) | Done: live run with OpenAI agents, one `correct` round, final `partial` | `evidence/multi-agent/student-1/c17c66cc-terminal/` |

Verification at handover:
- The full `uv run python scripts/check.py` gate passed (exit 0). The shared suite had 1710 passed
  with 93.0% coverage, and every feature met its threshold.
- Live checks against the local stack (`ps-dev`, real Feature 1 data):
  - All four host AI services were running.
  - The F1 endpoint tests passed 15/15. They used
    `PROPERTYSCOPE_F1_ENDPOINT_SEARCH_QUERY="10 Boyce Street Glebe"`, because the local DB holds
    real G-NAF data rather than the CI seed.
  - `cloud_smoke.py --base-url http://localhost:5100 --expect-ai` passed 33/33 across all five
    features.
  - `ai review multi-agent` and `ai review testing` both ran through AI-mode. Every Student 1 check
    passed. Their `fail` verdicts are expected evidence gaps; see section 4.

## 2. Phase 2 scope (do this next)

The aim is Rubric 2's UI half: Frontend → Backend → Multi-Agent Server → Planner → Worker →
Reviewer → Human Review → response, demonstrated from the Feature 1 UI. It also serves as the
reference integration for the other four students.

### 2.1 Shared panel `shared/frontend/multi-agent/` (shared.md A8)
- Model it on `shared/frontend/ai-chat/`: plain ES modules, `index.js` entry, `styles.css`,
  Node tests (`*.test.mjs`, run as in `CONTRIBUTING.md`), no build step.
- Make it feature-agnostic. It takes a base URL for the **feature backend's** proxy routes (never
  the server directly) and renders the template's `inputs` as a form.
- Stages: a live timeline from `run.stages`, polling `GET .../runs/{id}` until the state is not
  `planning`, `working` or `reviewing`.
- Show the plan steps, the Worker findings per step, and the Reviewer recommendation plus findings
  (severity, outcome, recommendation).
- Decision controls appear only when `available_actions` allows them:
  - approve, correct, partial and reject
  - a note, required unless approving
  - a step checklist for `partial` (`accepted_step_ids`)
  - an actor field
- Show the correction round (`round`, `superseded`), errors as Problem Details, and a link to the
  history.
- Mount it like ai-chat:
  - add a `docker-compose.dev.yml` bind mount `./shared/frontend/multi-agent:/usr/share/nginx/html/multi-agent:ro`
    for every feature frontend that needs it;
  - add `COPY shared/frontend/multi-agent ...` in each frontend's Dockerfile stage (start with
    `student-1/Dockerfile`);
  - add an empty `student-1/frontend/multi-agent/README.md` mount point, as for ai-chat.
- Check `scripts/validate_frontend_styles.py` and `scripts/check.py compile` for rules on shared
  frontend packages.

### 2.2 Feature 1 backend proxy routes (F-3)
- Follow `student-1/backend/src/propertyscope_data_platform/assistant_routes.py` and `clients.py`
  (how `AiModeClient` is injected through `app.py`).
- Add a `MultiAgentClient` built from `MULTI_AGENT_BASE_URL` and `MULTI_AGENT_SERVICE_TOKEN`. Both
  are already in Compose for f1, f2, f4 and f5. **f3-backend is not wired**; see section 4.
- Use bounded timeouts and the `X-Request-ID` passthrough.
- Routes, suggested under `/api/data-platform/v1/release-reviews`:
  - start: `POST`, with `template_id` fixed to `f1-release-readiness-review` server-side
  - read: `GET /{run_id}`
  - decide: `POST /{run_id}/decision`
  - optionally list and history
- Ownership: keep only runs whose `feature_id` is `student-1-propertyscope-data-platform`, the
  same idea as `assistant_run(..., owned)`.
- Return the server's Problem Details unchanged. When the server is unreachable, return a 503
  `multi_agent_unavailable` problem (the cloud baseline runs with AI off).
- Tests use `shared_testkit.FakeMultiAgentServer`, through `fake.transport()` or `fake.serve()`.
  **Never import `multi_agent_server` or `agent_core`**; `validate_architecture.py` enforces this.
- Update `student-1/contracts/data-platform-api.v1.openapi.yaml`, and the tool catalog only if
  needed.

### 2.3 Mount in the Feature 1 UI (F-4)
- Put a "Readiness review" action on the candidate release review page (find it from
  `student-1/frontend/routes/` and the release review fragments). It starts a run for that release
  and shows the panel inline.
- The human decision is about the recommendation. Publishing stays the existing separate button.
- Add a Playwright check next to `student-1/tests/e2e/test_form_behaviour_playwright.py` if it is
  cheap. Otherwise add Node tests for the panel and a backend test for the routes.

### 2.4 Evidence (F-5 UI half, R2-15)
- Run one full workflow from the UI in the live stack (`uv run scripts/dev.py stack up`, then
  `ai start --mode combined`; see `.github/skills/live-app-browser/SKILL.md`). Take screenshots of
  the plan, the review and the decision.
- Then run `uv run multi-agent-server export <run> --server --out docs/release-2/evidence/multi-agent/student-1/<run8>-ui`.
- Then `uv run scripts/dev.py ai review multi-agent` to refresh the review.

### 2.5 Acceptance for Phase 2
- [ ] `uv run python scripts/check.py` passes.
- [ ] A UI workflow reaches a human decision locally. Its export and screenshots are under
      `evidence/multi-agent/student-1/`.
- [ ] Panel README, an ADR-047 note if the design changed, and the root README feature notes are
      updated.
- [ ] **This file is deleted.**

### 2.6 Suggested agent prompt

> Implement Release 2 Phase 2 for PropertyScope on a branch from `release-2/shared-feature-1`
> (or `main` once that branch merges). Read `AGENTS.md`, then `docs/release-2/HANDOVER.md`
> sections 2 and 4, then `ai-services/multi-agent-server/README.md` and
> `shared/testkit/README.md` (FakeMultiAgentServer).
> Build the shared panel `shared/frontend/multi-agent/` (2.1), Feature 1's proxy routes (2.2), the
> UI mount (2.3), and capture live UI evidence (2.4). Meet 2.5, commit in Conventional Commit
> style, and delete `docs/release-2/HANDOVER.md` in the final commit.

## 3. Other remaining Release 2 work (not Phase 2)

| Item | Owner | Notes |
|---|---|---|
| F-8 CI evidence | Matthew, after merge | Once `student-1.yml` is green on `main`, run `uv run python scripts/collect_ci_evidence.py --student 1`. Then rerun `ai review testing` |
| Azure provisioning and deploy (E, R2-42..45) | Matthew | Follow the checklist in `deployment/azure/README.md`: subscription, RG, federated credential `repo:MattShelton04/41026ASDProject:environment:production`, GitHub `production` environment and variables, then `deploy.sh provision` and `secrets`. Then run the workflow, `ai review cloud`, and `ai review decide` |
| Bicep compile | Matthew | Not compiled locally because the bicep CLI was not installed. Run `az bicep build --file deployment/azure/main.bicep` first. A BCP318 warning on the conditional module output is possible |
| Bonus B1–B6 | Matthew | Prepared only. Order B5, B6, B1..B4 (plan §F) |
| G. Evidence and report | All | Local deployment report with multi-terminal logs, then `release-2-technical-report.md` and its builder |
| Other features (F-2..F-11) | Students 2–5 | Copy Feature 1's manifest, routes and panel mount once Phase 2 lands. Endpoint test recipe: `shared/testkit/README.md` |

## 4. Known issues and things to tell people

- **Other students' slices were touched in two ways only, both by the shared packaging work:**
  - a single `COPY ai-services/multi-agent-server/pyproject.toml` line in each
    `student-{1..5}/Dockerfile`, which the new workspace member requires for `uv sync --locked`;
  - per-file Ruff `S` ignores for their existing findings in the root `pyproject.toml`.

  Tell the owners.
- **Ruff `S` findings pending their owners** (each fixes the code or adds an inline
  `# noqa: Sxxx - reason`, then deletes their entries from `extend-per-file-ignores`):
  - Student 2: 8
  - Student 3: 10
  - Student 4: 8
  - Student 5: 59

  Details are in `evidence/security/pre-commit-report.md`.
- **f3-backend has no `MULTI_AGENT_*` environment.** `student-3/tests/test_deployment.py` asserts
  its exact environment, so Student 3 adds the variables and updates that test.
- **MCP tool timeout under load.** `data.release_inspect.v1` (3 s `timeout_ms` in
  `student-1/tool-catalog.yaml`) timed out once on the large local database while the gate was
  running. The Reviewer handled it correctly, and the `correct` round succeeded. Consider raising
  that tool's timeout if UI runs hit it.
- **Seeded address.** The F1 search endpoint test's default query (`11 Example Street`) exists
  only in a fresh, seeded database. Use `PROPERTYSCOPE_F1_ENDPOINT_SEARCH_QUERY` locally.
- **Load-sensitive tests.** `scripts/tests/test_ui_audit_browser.py::test_configured_named_flows_reach_their_response_state`
  and a student-3 MCP socket test failed once under heavy load and passed on rerun. Host RAG can
  also exceed the 30 s readiness wait in `scripts/devtools/host_runtime.py`; rerun `stack up`.
- **Package name.** The package is `multi-agent-server`, matching its siblings, not
  `propertyscope-multi-agent-server` as `parts/shared.md` says.
- **Interim review evidence.** The review reports committed under `evidence/reviews/` are
  interim. Regenerate them at the 20 October freeze.
