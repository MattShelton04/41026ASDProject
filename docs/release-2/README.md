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

## Status (10 October 2026)

| Area | State | Where |
|---|---|---|
| Multi-Agent Server (Shared A1–A7) | Done: contracts, state machine, model and deterministic agents, SQLite and JSONL audit, HTTP API, CLI, `FakeMultiAgentServer` | [README](../../ai-services/multi-agent-server/README.md), [ADR-047](../architecture/decisions/ADR-047-multi-agent-server.md) |
| Shared multi-agent panel (A8) | Done: feature-agnostic panel with the proxy contract every feature implements | [`shared/frontend/multi-agent/`](../../shared/frontend/multi-agent/README.md) |
| Review modes (B) | Done. The review prompts now treat failed checks as findings, not a run failure | [review-modes.md](review-modes.md) |
| Pre-commit security (C), endpoint testing (D) | Done | `.pre-commit-config.yaml`, [`shared/testkit`](../../shared/testkit/README.md) |
| Azure (E/F) | Prepared, **not provisioned** | [deployment/azure](../../deployment/azure/README.md) |
| Feature 1 workflow (F-2..F-5, F-7) | Done: manifest, `/release-reviews` proxy routes, "Readiness review" on the release review page, endpoint tests, and terminal plus UI evidence | [student-1 README](../../student-1/README.md), [`evidence/multi-agent/student-1/`](evidence/multi-agent/student-1/18740ca5-ui/README.md) |

### Remaining work

| Item | Owner | Notes |
|---|---|---|
| F-8 CI evidence | Matthew, after merge | Once `student-1.yml` is green on `main`, run `uv run python scripts/collect_ci_evidence.py --student 1`, then `ai review testing` |
| Azure provisioning and deploy (R2-42..45) | Matthew | Follow the checklist in `deployment/azure/README.md` (subscription, resource group, federated credential `repo:MattShelton04/41026ASDProject:environment:production`, GitHub `production` environment and variables), then `deploy.sh provision` and `secrets`, the workflow, `ai review cloud` and `ai review decide` |
| Bicep compile | Matthew | Not yet compiled locally. Run `az bicep build --file deployment/azure/main.bicep`; a BCP318 warning on the conditional module output is possible |
| Bonus B1–B6 | Matthew | Prepared only. Order B5, B6, B1..B4 (implementation plan §F) |
| Evidence and report (G) | All | Local deployment report with multi-terminal logs, then `release-2-technical-report.md` and its builder. Regenerate `evidence/reviews/` at the 20 October freeze; the committed reviews are interim |
| Features 2–5 workflows (F-2..F-11) | Students 2–5 | Copy Feature 1: a `config/multi-agent/workflow.yaml`, proxy routes tested with `FakeMultiAgentServer`, and a panel mount (Dockerfile `COPY`, `docker-compose.dev.yml` bind mount, empty `frontend/multi-agent/README.md`). Endpoint test recipe: `shared/testkit/README.md` |

### Known issues

- Shared packaging touched other slices in two ways only: one
  `COPY ai-services/multi-agent-server/pyproject.toml` line in each `student-{1..5}/Dockerfile`
  (needed for `uv sync --locked`), and per-file Ruff `S` ignores in the root `pyproject.toml`.
- Ruff `S` findings await their owners (Student 2: 8, Student 3: 10, Student 4: 8, Student 5: 59;
  see `evidence/security/pre-commit-report.md`). Each owner fixes the code or adds an inline
  `# noqa: Sxxx - reason`, then deletes their `extend-per-file-ignores` entries.
- `f3-backend` has no `MULTI_AGENT_*` environment. `student-3/tests/test_deployment.py` asserts its
  exact environment, so Student 3 adds the variables and updates that test.
- `ai review multi-agent` reports `fail` until Students 2–5 export workflow evidence. Every
  Student 1 check passes.
- The F1 search endpoint test's default query (`11 Example Street`) exists only in a fresh seeded
  database. Set `PROPERTYSCOPE_F1_ENDPOINT_SEARCH_QUERY` against a database holding real G-NAF data.
- Under heavy load, `test_ui_audit_browser.py::test_configured_named_flows_reach_their_response_state`
  and a Student 3 MCP socket test have each failed once and passed on rerun. Host RAG can exceed
  the 30 s readiness wait in `scripts/devtools/host_runtime.py`; rerun `stack up`.
- The package is named `multi-agent-server`, like its siblings, not
  `propertyscope-multi-agent-server` as `parts/shared.md` says.
