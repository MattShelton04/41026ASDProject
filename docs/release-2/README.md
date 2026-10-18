# Release 2

Release 2 keeps everything from Release 1 and adds:

- a shared, non-containerised Multi-Agent Server (Planner → Worker → Reviewer → Human Review)
- three new agentic-loop review modes
- pre-commit security scans
- CI tests for two endpoints per student
- deployment of the integrated application to **Azure**

In the baseline cloud deployment, AI-mode, MCP, RAG and Multi-Agent are disabled. Enabling them
is bonus work. The showcase is on 23 October 2026 and the report (`group-20.pdf`) is due on
25 October 2026.

- [Requirements](requirements.md): the brief and rubric restated as numbered requirements, report
  contents and showcase coverage.
- [Implementation plan](implementation-plan.md): key decisions, target architecture, workstreams,
  timeline, evidence layout and risks.
- [Agentic-loop review modes](review-modes.md): `dev.py ai review {multi-agent,testing,cloud}`,
  the evidence each mode reads, the review output schema, the validation logs and the human
  release decision.
- [Responsibilities by part](parts/README.md): what Shared and each feature must deliver, with a
  plan for each part:
  [Shared](parts/shared.md) · [F1](parts/feature-1.md) · [F2](parts/feature-2.md) ·
  [F3](parts/feature-3.md) · [F4](parts/feature-4.md) · [F5](parts/feature-5.md)
- [Showcase runbook](showcase-runbook.md): the rehearsable script for the 10-minute video and the
  live showcase, with segment owners and timings, exact commands, preparation and fallbacks.

Evidence collected for the report goes in `evidence/`, as described in the implementation plan.

## Status (18 October 2026)

| Area | State | Where |
|---|---|---|
| Multi-Agent Server (Shared A1–A7) | Done: contracts, state machine, model and deterministic agents, SQLite and JSONL audit, HTTP API, CLI, `FakeMultiAgentServer` | [README](../../ai-services/multi-agent-server/README.md), [ADR-047](../architecture/decisions/ADR-047-multi-agent-server.md) |
| Shared multi-agent panel (A8) | Done: feature-agnostic "mission relay" panel (live lanes, now line, one-question decision, drawers, replay of recorded runs) with the proxy contract every feature implements, including incremental history cursors | [`shared/frontend/multi-agent/`](../../shared/frontend/multi-agent/README.md) |
| Review modes (B) | Done, with `v2` prompts. Every group-wide check names its owner, a student's checks are `blocked` behind one evidence gate, and each report shows **Coverage by owner** and a **Verdict basis**. Shared and Feature 1 therefore show as complete while the group verdict is `fail` for Students 2–5's missing evidence. The committed testing and multi-agent reviews (16 October, `v1` prompts) predate this and are regenerated at the freeze | [review-modes.md](review-modes.md), [`evidence/reviews/`](evidence/reviews/README.md) |
| Pre-commit security (C), endpoint testing (D) | Done. The committed report (16 October) passes, but it scanned a branch commit **with uncommitted changes** and lists 85 pending-owner Ruff findings for Students 2–5. It is regenerated on clean `main` at the freeze | `.pre-commit-config.yaml`, [`evidence/security/`](evidence/security/pre-commit-report.md), [`shared/testkit`](../../shared/testkit/README.md) |
| Local deployment report (G1) | Done: `scripts/capture_local_deployment.py`, 109 of 109 live checks, six terminal logs and a real-provider terminal Multi-Agent run. `dev.py ai serve SERVICE` runs any host service in its own terminal. RAG and MCP now log one line per request with its request ID (after the 16 October capture) | [`evidence/local/`](evidence/local/README.md) |
| CI release gate (E4) | Done: `cloud-deployment.yml` runs `verify-ci` (Integration CI and Student 1–5 CI green for the deployed commit, `scripts/verify_release_gate.py`) and `build-validate` (every image built and the Azure Compose model validated, `scripts/validate_release_images.py`) before its `deploy` job | [`cloud-deployment.yml`](../../.github/workflows/cloud-deployment.yml), [`evidence/cloud/`](evidence/cloud/README.md) |
| Technical report (G2) | Builder and source done; Shared and Feature 1 content written, including the cloud figures, the release decision and Student 1's contribution log to PR #157 (2,102 of 3,000 words). Matthew's remaining TODOs are the freeze refreshes, PR #157's merged commit and the bonus section. Students 2–5 fill their TODOs | [`docs/reports/`](../reports/README.md), `scripts/build_release2_report.py --status` |
| Azure (E/F) | **Provisioned and deployed** on 17 October: *Azure for Students*, `newzealandnorth`, `Standard_D4as_v4`. **AI-off evidence captured on 18 October** from [run 39112162750](https://github.com/MattShelton04/41026ASDProject/actions/runs/39112162750) (`3c25c083`): gate passed, 21/21 containers, smoke 37/37 with 0 skipped (full CRUD for all five features against real Feature 1 releases), AI `503 ai_disabled`, B5 and B6 with no failure, `ai review cloud` pass 18/18 (deterministic), human release decision **RELEASE**, plus 15 portal and 5 app screenshots. Feature 1 holds six real accepted releases there and no demonstration data (#153, #154). The Cloud AI Tier workflow (`cloud-ai.yml`, #156) turns the AI tier on for B1–B4. Automatic deployments are paused (`AZURE_AUTO_DEPLOY=false`); the VM is deallocated nightly. Bicep compiles and lints cleanly (`deployment/azure/validate-iac.sh`, Integration CI job `iac-lint`) | [deployment/azure](../../deployment/azure/README.md), [`evidence/cloud/`](evidence/cloud/README.md) |
| Showcase (G) | Runbook written: segments, timings, commands and fallbacks. Students 2–5 write their own segments | [showcase-runbook.md](showcase-runbook.md) |
| Feature 1 (F-1..F-9, F-11) | Done: workflow manifest (template v2), `/release-reviews` proxy routes with input validation, "Readiness review" UI (disabled with a visible reason where the deployment has no AI tier), demonstration-data notice, endpoint tests, terminal and UI evidence, CI evidence (run #353, 34/34 endpoint tests), report sections. F-9 done on Azure: Feature 1 CRUD passes the cloud smoke test against real releases, and the suburb-map spatial API serves Feature 3 (#151). F-10 waits for the cloud AI bonus run. The CI record (15 October) is refreshed at the freeze | [student-1 README](../../student-1/README.md), [`evidence/ci/student-1.md`](evidence/ci/student-1.md) |

### Remaining work

| Item | Owner | Notes |
|---|---|---|
| Evidence refresh at the freeze | Matthew | The [ordered checklist](#evidence-refresh-at-the-freeze-on-clean-main) below |
| Azure evidence and release decision (R2-45) | Matthew | AI-off evidence, cloud review and screenshots are in [`evidence/cloud/`](evidence/cloud/README.md) (run 39112162750). Human decision recorded: **RELEASE** by Matthew Shelton on 18 October ([`release-decision.md`](evidence/cloud/release-decision.md)). The freeze refresh reruns `ai review cloud`, so record the decision again after it. Optional: rerun the review with a live AI-mode provider, and add the Key Vault secret names to `portal/12` (needs a temporary firewall rule) |
| Cloud gate | Matthew | **Addressed** by the `verify-ci` and `build-validate` jobs (see the status table) |
| Bicep compile | Matthew | **Done**: `deployment/azure/validate-iac.sh` builds and lints every template; Integration CI runs it with `--strict` in the `iac-lint` job |
| Bonus B1–B6 | Matthew | B5: passes in run 39112162750 (52 PASS, 0 FAIL). B6: passes from a laptop on 18 October (43 PASS, 0 FAIL). B1–B4: all pass in Cloud AI Tier run 39119158736 on commit `817ef779` (18 October). All six outputs are in [`evidence/bonus/`](evidence/bonus/README.md). No bonus is claimed until report Section 13 claims it |
| Report and video (G) | All | `build_release2_report.py --status` lists each owner's TODOs; the [showcase runbook](showcase-runbook.md) holds each student's video segment |
| Features 2–5 workflows (F-2..F-11) | Students 2–5 | Copy Feature 1: a `config/multi-agent/workflow.yaml`, proxy routes tested with `FakeMultiAgentServer`, and a panel mount (Dockerfile `COPY`, `docker-compose.dev.yml` bind mount, empty `frontend/multi-agent/README.md`). Endpoint test recipe: `shared/testkit/README.md`; then `collect_ci_evidence.py --student N`, and `multi-agent-server export <run> --out docs/release-2/evidence/multi-agent/student-N/<run> --server` |

### Evidence refresh at the freeze (on clean main)

One command runs every capture in order and logs each step:
`scripts/refresh_release2_evidence.py` (see its docstring). It copies nothing into the repository
in a dry run, and under `--final` it refuses to start unless the checkout is `main` at
`origin/main` with a clean source tree. The capture tools ignore `docs/release-2/evidence` when
they check for uncommitted changes, so one step's output never marks the next capture as dirty.

1. Start the stack and the four host services, each in its own foreground terminal
   ([layout](evidence/local/README.md#several-real-terminals)): `uv run scripts/dev.py stack up`,
   `uv run scripts/dev.py ai stop` (stack up starts them in the background), then
   `uv run scripts/dev.py ai serve <service>` for `ai-mode`, `mcp`, `rag` and `multi-agent`.
2. Rehearse first, into a scratch folder under `.propertyscope-runtime/evidence-refresh/`:

   ```text
   uv run python scripts/refresh_release2_evidence.py
   ```

3. At the freeze, once every `student-N.yml` is green on `main` and Students 2–5 have merged
   their evidence:

   ```text
   uv run python scripts/refresh_release2_evidence.py --final --ci-students all
   ```

   The steps are `preflight`, `security`, `ci`, `local`, `ui`, `reviews` and `report`. At `ui` the
   command waits for a person to decide a Feature 1 Readiness review in the UI (current panel,
   template v2) and exports that run to `multi-agent/student-1/<run>-ui/`. `--ui-run-id` exports
   an already-decided run instead; `--only` and `--skip` rerun single steps. The cloud review
   reports `fail` until cloud evidence exists; after the first Azure deployment rerun
   `--final --only reviews`, then `uv run scripts/dev.py ai review decide`.
4. Check `summary.md` in the run folder, review `git diff --stat docs/release-2/evidence`, and
   commit the refreshed evidence.
5. Contribution tables (report Section 12): every student's commits, including the merged Wave 1/2
   PR. Then rebuild the report: `uv run python scripts/build_release2_report.py`.

### Known issues

- Shared packaging touched other slices in two ways only: one
  `COPY ai-services/multi-agent-server/pyproject.toml` line in each `student-{1..5}/Dockerfile`
  (needed for `uv sync --locked`), and per-file Ruff `S` ignores in the root `pyproject.toml`.
- Ruff `S` findings await their owners (Student 2: 8, Student 3: 10, Student 4: 8, Student 5: 59;
  see `evidence/security/pre-commit-report.md`). Each owner fixes the code or adds an inline
  `# noqa: Sxxx - reason`, then deletes their `extend-per-file-ignores` entries.
- pip-audit passes with two reviewed exceptions in `scripts/security/accepted-risks.toml`: Pillow
  11.3.0 (held by `fastembed==0.7.4` in RAG; never decodes untrusted images) and pytest 8.4 (fix
  only in pytest 9). Removing them needs a RAG upgrade with re-ingest and evaluation, and a pytest
  9 change across every suite; neither was attempted before the showcase.
- `f3-backend` has no `MULTI_AGENT_*` environment. `student-3/tests/test_deployment.py` asserts its
  exact environment, so Student 3 adds the variables and updates that test. Until then the Azure
  AI overlay gives the Multi-Agent token only to the Feature 1, 2, 4 and 5 backends.
- `ai review multi-agent` and `ai review testing` report `fail` until Students 2–5 export workflow
  and CI evidence. Coverage by owner shows every Shared and Student 1 check passing.
- The 16 October local capture logged `DependencyUnavailableError` from `f2-backend`'s background
  sales-import reconciliation while Feature 2's health and CRUD checks passed (Student 2).
- On Azure (18 October): a Feature 1 property search that names a suburb ("1 George Street
  Balmain") can exceed the read budget (`503 read_budget_exceeded`), as can the first search after
  `f1-db-api` restarts; Feature 3's `/published/suburbs` answers 503; Feature 2 still shows fixture
  cases; and Data status lists the deliberately disabled AI tier as needing attention. Details:
  [`evidence/cloud/README.md`](evidence/cloud/README.md#observations-made-while-capturing).
- Under heavy load, `test_ui_audit_browser.py::test_configured_named_flows_reach_their_response_state`
  and a Student 3 MCP socket test have each failed once and passed on rerun.

Fixed since 16 October: RAG and MCP log correlated request IDs (the committed 16 October capture
predates this, so its RAG and MCP terminal logs still show none), and the Azure AI overlay now
hands the Multi-Agent token to the Feature 1 backend.
