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

Evidence collected for the report goes in `evidence/`, as described in the implementation plan.

## Status (16 October 2026)

| Area | State | Where |
|---|---|---|
| Multi-Agent Server (Shared A1–A7) | Done: contracts, state machine, model and deterministic agents, SQLite and JSONL audit, HTTP API, CLI, `FakeMultiAgentServer` | [README](../../ai-services/multi-agent-server/README.md), [ADR-047](../architecture/decisions/ADR-047-multi-agent-server.md) |
| Shared multi-agent panel (A8) | Done: feature-agnostic "mission relay" panel (live lanes, now line, one-question decision, drawers, replay of recorded runs) with the proxy contract every feature implements, including incremental history cursors | [`shared/frontend/multi-agent/`](../../shared/frontend/multi-agent/README.md) |
| Review modes (B) | Done. The testing review reads the security report's own JSON and flags pending-owner Ruff findings (advisory). Testing and multi-agent reviews regenerated through AI-mode on 16 October; both `fail` only for Students 2–5's missing evidence | [review-modes.md](review-modes.md), [`evidence/reviews/`](evidence/reviews/README.md) |
| Pre-commit security (C), endpoint testing (D) | Done. Report regenerated on a clean branch commit: PASS, no open finding | `.pre-commit-config.yaml`, [`evidence/security/`](evidence/security/pre-commit-report.md), [`shared/testkit`](../../shared/testkit/README.md) |
| Local deployment report (G1) | Done: `scripts/capture_local_deployment.py`, 109 of 109 live checks, six terminal logs and a real-provider terminal Multi-Agent run. `dev.py ai serve SERVICE` runs any host service in its own terminal | [`evidence/local/`](evidence/local/README.md) |
| Technical report (G2) | Builder and source done; Shared and Feature 1 content written, 1,865 of 3,000 words. Students 2–5 fill their TODOs | [`docs/reports/`](../reports/README.md), `scripts/build_release2_report.py --status` |
| Azure (E/F) | Prepared, **not provisioned** | [deployment/azure](../../deployment/azure/README.md) |
| Feature 1 (F-1..F-8, F-11) | Done: workflow manifest, `/release-reviews` proxy routes, "Readiness review" UI, endpoint tests, terminal and UI evidence, CI evidence (run #353, 34/34 endpoint tests), report sections. F-9/F-10 wait for Azure | [student-1 README](../../student-1/README.md), [`evidence/ci/student-1.md`](evidence/ci/student-1.md) |

### Remaining work

| Item | Owner | Notes |
|---|---|---|
| Evidence refresh after merge | Matthew | On `main`, re-run `collect_ci_evidence.py --student 1` (once `student-1.yml` is green there), `security report`, `capture_local_deployment.py`, then `ai review testing` and `ai review multi-agent`; rebuild the report |
| Azure provisioning and deploy (R2-42..45) | Matthew | Follow the checklist in `deployment/azure/README.md` (subscription, resource group, federated credential `repo:MattShelton04/41026ASDProject:environment:production`, GitHub `production` environment and variables), then `deploy.sh provision` and `secrets`, the workflow, `ai review cloud` and `ai review decide` |
| Cloud gate | Matthew | `cloud-deployment.yml` waits for Integration CI only, not the five `student-N.yml` endpoint workflows that the brief's DevOps flow puts first. Decide with the Azure work |
| Bicep compile | Matthew | Not yet compiled locally. Run `az bicep build --file deployment/azure/main.bicep`; a BCP318 warning on the conditional module output is possible |
| Bonus B1–B6 | Matthew | Prepared only. Order B5, B6, B1..B4 (implementation plan §F) |
| Report and video (G) | All | `build_release2_report.py --status` lists each owner's TODOs; regenerate `evidence/reviews/` at the 20 October freeze |
| Features 2–5 workflows (F-2..F-11) | Students 2–5 | Copy Feature 1: a `config/multi-agent/workflow.yaml`, proxy routes tested with `FakeMultiAgentServer`, and a panel mount (Dockerfile `COPY`, `docker-compose.dev.yml` bind mount, empty `frontend/multi-agent/README.md`). Endpoint test recipe: `shared/testkit/README.md`; then `collect_ci_evidence.py --student N` and a multi-agent export into `evidence/multi-agent/student-N/` |

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
  exact environment, so Student 3 adds the variables and updates that test.
- `ai review multi-agent` and `ai review testing` report `fail` until Students 2–5 export workflow
  and CI evidence. Every Shared and Student 1 check passes.
- The 16 October local capture logged `DependencyUnavailableError` from `f2-backend`'s background
  sales-import reconciliation while Feature 2's health and CRUD checks passed (Student 2).
- RAG writes nothing to its host log during requests, and MCP log lines carry no request IDs, so
  their terminal logs show traffic but no correlated IDs.
- Under heavy load, `test_ui_audit_browser.py::test_configured_named_flows_reach_their_response_state`
  and a Student 3 MCP socket test have each failed once and passed on rerun.
