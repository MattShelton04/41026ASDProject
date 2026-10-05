# Release 2 responsibilities by part

What each part must deliver for Release 2. Each linked file holds that part's implementation plan.
The schedule and the shared design decisions are in [implementation-plan.md](../implementation-plan.md).

| Part | Owner | Must deliver | Plan |
|---|---|---|---|
| Shared / Common | Matthew (group lead) | Multi-Agent Server, the three loop review modes, pre-commit security scans, CI endpoint-test helper, Azure IaC, deploy scripts, `cloud-deployment.yml`, bonus cloud AI and security, evidence tooling, report build | [shared.md](shared.md) |
| Feature 1: Data Platform | Matthew | Common checklist below, plus the data used in the cloud and the shared edge in Azure | [feature-1.md](feature-1.md) |
| Feature 2: Market Intelligence | Burhan | Common checklist below | [feature-2.md](feature-2.md) |
| Feature 3: Suburb Analytics | James | Common checklist below | [feature-3.md](feature-3.md) |
| Feature 4: Due Diligence | Michael | Common checklist below | [feature-4.md](feature-4.md) |
| Feature 5: Buyer Workspaces | Derek | Common checklist below | [feature-5.md](feature-5.md) |

## Common feature checklist

Every feature owner does all of these in their own `student-N/` slice and `student-N.yml`.
Evidence paths are relative to `docs/release-2/`.

| # | Task | Done when | Rubric |
|---|---|---|---|
| F-1 | Keep frontend, backend, database, CRUD and the R1 MCP/RAG integration working | The Release 1 UI flows still pass locally | 1 |
| F-2 | Add a multi-agent workflow manifest at `config/multi-agent/workflow.yaml` (objective, allowed read-only tools, reviewer checks) | `uv run multi-agent-server validate student-N/config/multi-agent/workflow.yaml` passes | 2 |
| F-3 | Add backend proxy routes: start a workflow, read its status, submit the human decision. All three call the Multi-Agent Server over HTTP with the service token | Backend tests use the shared fake server; no `agent_core` import | 2 |
| F-4 | Mount the shared multi-agent panel in the frontend (plan → worker output → reviewer findings → approve / correct / partially accept / reject) | The full workflow completes from the feature UI locally | 2, 10 |
| F-5 | Capture one completed workflow, with its history and audit logs, into `evidence/multi-agent/student-N/` | Files present; they include a human decision | 2, 9 |
| F-6 | Run the pre-commit scans on your slice; fix findings or justify them inline | Your slice has no unexplained findings in the security report | 3 |
| F-7 | Write CI tests for **two endpoint functions** (happy path plus one failure case each) against the running Compose service, in `tests/endpoints/` | `student-N.yml` runs them after `up --wait` and uploads JUnit XML | 4 |
| F-8 | Record a green run (URL, SHA, results) in `evidence/ci/student-N.md` | Linked run is on `main` at or after the final change | 4, 9 |
| F-9 | Make the feature work on Azure: production config, seed data, and a cloud smoke case for one CRUD operation | `cloud-deployment.yml` smoke step passes for your feature | 7 |
| F-10 | With cloud AI on (bonus), check the feature's AI chat and multi-agent panel on Azure | A screenshot or log is in `evidence/bonus/` | B1–B4 |
| F-11 | Provide report inputs: your design flow diagram, contribution log, and video segment | Delivered to the report owner by 21 Oct | 9, 10 |

Each feature owner chooses their two endpoints and their workflow objective. The suggestions in
each feature file are starting points based on existing routes. They are not decisions.
