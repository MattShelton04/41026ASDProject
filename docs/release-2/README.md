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

## Status (17 October 2026)

| Area | State | Where |
|---|---|---|
| Multi-Agent Server (Shared A1–A7) | Done: contracts, state machine, model and deterministic agents, SQLite and JSONL audit, HTTP API, CLI, `FakeMultiAgentServer` | [README](../../ai-services/multi-agent-server/README.md), [ADR-047](../architecture/decisions/ADR-047-multi-agent-server.md) |
| Shared multi-agent panel (A8) | Done: feature-agnostic "mission relay" panel (live lanes, now line, one-question decision, drawers, replay of recorded runs) with the proxy contract every feature implements, including incremental history cursors | [`shared/frontend/multi-agent/`](../../shared/frontend/multi-agent/README.md) |
| Review modes (B) | Done, with `v2` prompts. Every group-wide check names its owner, a student's checks are `blocked` behind one evidence gate, and each report shows **Coverage by owner** and a **Verdict basis**. Shared and Feature 1 therefore show as complete while the group verdict is `fail` for Students 2–5's missing evidence. The committed testing and multi-agent reviews (16 October, `v1` prompts) predate this and are regenerated at the freeze | [review-modes.md](review-modes.md), [`evidence/reviews/`](evidence/reviews/README.md) |
| Pre-commit security (C), endpoint testing (D) | Done. The committed report (16 October) passes, but it scanned a branch commit **with uncommitted changes** and lists 85 pending-owner Ruff findings for Students 2–5. It is regenerated on clean `main` at the freeze | `.pre-commit-config.yaml`, [`evidence/security/`](evidence/security/pre-commit-report.md), [`shared/testkit`](../../shared/testkit/README.md) |
| Local deployment report (G1) | Done: `scripts/capture_local_deployment.py`, 109 of 109 live checks, six terminal logs and a real-provider terminal Multi-Agent run. `dev.py ai serve SERVICE` runs any host service in its own terminal. RAG and MCP now log one line per request with its request ID (after the 16 October capture) | [`evidence/local/`](evidence/local/README.md) |
| CI release gate (E4) | Done: `cloud-deployment.yml` runs `verify-ci` (Integration CI and Student 1–5 CI green for the deployed commit, `scripts/verify_release_gate.py`) and `build-validate` (every image built and the Azure Compose model validated, `scripts/validate_release_images.py`) before its `deploy` job | [`cloud-deployment.yml`](../../.github/workflows/cloud-deployment.yml), [`evidence/cloud/`](evidence/cloud/README.md) |
| Technical report (G2) | Builder and source done; Shared and Feature 1 content written, 1,943 of 3,000 words. Students 2–5 fill their TODOs | [`docs/reports/`](../reports/README.md), `scripts/build_release2_report.py --status` |
| Azure (E/F) | Prepared and hardened, **not provisioned**. Bicep compiles and lints cleanly (`deployment/azure/validate-iac.sh`, Integration CI job `iac-lint`) | [deployment/azure](../../deployment/azure/README.md) |
| Showcase (G) | Runbook written: segments, timings, commands and fallbacks. Students 2–5 write their own segments | [showcase-runbook.md](showcase-runbook.md) |
| Feature 1 (F-1..F-8, F-11) | Done: workflow manifest (template v2), `/release-reviews` proxy routes with input validation, "Readiness review" UI (disabled with a visible reason where the deployment has no AI tier), demonstration-data notice, endpoint tests, terminal and UI evidence, CI evidence (run #353, 34/34 endpoint tests), report sections. F-9/F-10 wait for Azure | [student-1 README](../../student-1/README.md), [`evidence/ci/student-1.md`](evidence/ci/student-1.md) |

### Remaining work

| Item | Owner | Notes |
|---|---|---|
| Evidence refresh at the freeze | Matthew | The [ordered checklist](#evidence-refresh-at-the-freeze-on-clean-main) below |
| Azure provisioning and deploy (R2-42..45) | Matthew | Follow the switch-on checklist in `deployment/azure/README.md` (subscription, resource group, federated credential `repo:MattShelton04/41026ASDProject:environment:production`, GitHub `production` environment and variables), then `deploy.sh provision` and `secrets`, the workflow, `ai review cloud` and `ai review decide` |
| Cloud gate | Matthew | **Addressed** by the `verify-ci` and `build-validate` jobs (see the status table) |
| Bicep compile | Matthew | **Done**: `deployment/azure/validate-iac.sh` builds and lints every template; Integration CI runs it with `--strict` in the `iac-lint` job |
| Bonus B1–B6 | Matthew | Prepared only. Order B5, B6, B1..B4 (implementation plan §F) |
| Report and video (G) | All | `build_release2_report.py --status` lists each owner's TODOs; the [showcase runbook](showcase-runbook.md) holds each student's video segment |
| Features 2–5 workflows (F-2..F-11) | Students 2–5 | Copy Feature 1: a `config/multi-agent/workflow.yaml`, proxy routes tested with `FakeMultiAgentServer`, and a panel mount (Dockerfile `COPY`, `docker-compose.dev.yml` bind mount, empty `frontend/multi-agent/README.md`). Endpoint test recipe: `shared/testkit/README.md`; then `collect_ci_evidence.py --student N`, and `multi-agent-server export <run> --out docs/release-2/evidence/multi-agent/student-N/<run> --server` |

### Evidence refresh at the freeze (on clean main)

Run these in order on a clean checkout of `main` at the 20 October freeze (`git status --short`
prints nothing), then commit the results together:

1. Security report: `uv run scripts/dev.py security report`. Check that the report no longer says
   "with uncommitted changes".
2. CI evidence, once `student-1.yml` is green on `main`:
   `uv run python scripts/collect_ci_evidence.py --student 1`.
3. Local deployment: `uv run scripts/dev.py stack up`, then `uv run scripts/dev.py ai stop`, then
   `uv run scripts/dev.py ai serve <service>` for `mcp`, `rag`, `ai-mode` and `multi-agent`, each
   in its own foreground terminal ([layout](evidence/local/README.md#several-real-terminals)), then
   `uv run python scripts/capture_local_deployment.py`.
4. A fresh Feature 1 UI Readiness review with the current panel and template v2, decided by a real
   person, then exported with
   `uv run multi-agent-server export <run> --out docs/release-2/evidence/multi-agent/student-1/<run>-ui --server`.
5. `uv run scripts/dev.py ai review cloud` before Azure exists, to prove the mode (its verdict is
   `fail` until cloud evidence exists). After the first deployment, run it again, then
   `uv run scripts/dev.py ai review decide`.
6. `uv run scripts/dev.py ai review testing` and `uv run scripts/dev.py ai review multi-agent`,
   after Students 2–5 have merged their CI and workflow evidence.
7. Contribution tables (report Section 12): every student's commits, including the merged Wave 1/2
   PR.
8. Rebuild the report: `uv run python scripts/build_release2_report.py`.

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
- Under heavy load, `test_ui_audit_browser.py::test_configured_named_flows_reach_their_response_state`
  and a Student 3 MCP socket test have each failed once and passed on rerun.

Fixed since 16 October: RAG and MCP log correlated request IDs (the committed 16 October capture
predates this, so its RAG and MCP terminal logs still show none), and the Azure AI overlay now
hands the Multi-Agent token to the Feature 1 backend.
