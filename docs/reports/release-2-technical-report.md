# PropertyScope NSW

**Release 2 / Technical report**

41026 Advanced Software Development — Assessment 3

| Submission | Group 20 |
|---|---|
| Team | Matthew Shelton, Burhan Naeem, James Huang, Michael White, Derek Song |
| Due | 25 October 2026, 11:59 pm Sydney time |
| Repository | [MattShelton04/41026ASDProject](https://github.com/MattShelton04/41026ASDProject) |
| Showcase video | Pending |
| Showcase | 23 October 2026 |
| Commit reference | [[BASELINE]] |

[[TODO: Group | Replace "Pending" with the published showcase video link, and use the same URL in RELEASE2_METADATA and Section 14]]

<!--
Authors: the brief allows 3,000 words. Cover text, captions, tables, generated tables and code
blocks all count; diagram pixels, TODO callouts and these comments do not. Run
`uv run python scripts/build_release2_report.py --status` to see each chapter against its budget
and your outstanding TODOs. Replace each TODO with your content; stay inside your share.
-->

[[PAGEBREAK]]

[[TOC]]

## 1 Project overview

PropertyScope NSW helps buyers research NSW property. Each student owns a containerised frontend,
backend/API and database slice behind a shared home page, and Matthew also leads the shared
platform. Release 1 added host MCP and RAG servers to the Release 0 AI-mode and its
Plan/Act/Observe/Adapt loop. Release 2 keeps all of these and adds:

- a shared host Multi-Agent Server (Planner → Worker → Reviewer → human review) that each feature
  calls through its own backend;
- three agentic-loop review modes: multi-agent workflow, testing report and cloud deployment;
- pre-commit security scans, and post-commit tests of two endpoint functions per student;
- an Azure deployment workflow with the AI tier disabled by default.

| Student | Feature | Release 2 responsibility |
|---|---|---|
| 1 Matthew Shelton (24763373) | F1 Data platform and property discovery | Shared platform: Multi-Agent Server, review modes, security scans, endpoint test kit, Azure. F1 readiness-review workflow and endpoint tests |
| 2 Burhan Naeem (24764134) | F2 Property sales and market cases | F2 workflow, endpoint tests and evidence |
| 3 James Huang (24970865) | F3 Suburb, crime and liveability analytics | F3 workflow, endpoint tests and evidence |
| 4 Michael White (24846267) | F4 Site, planning and building due diligence | F4 workflow, endpoint tests and evidence |
| 5 Derek Song (24833978) | F5 Buyer journey workspace | F5 workflow, endpoint tests and evidence |

## 2 Final repository structure

| Path | Contents | Release |
|---|---|---|
| `student-1/` … `student-5/` | Feature slices: UI, API, database service, tools, corpus; `config/multi-agent/` and `tests/endpoints/` | 0–2 |
| `ai-services/ai-mode/`, `agent-core/` | AI-mode run API and the shared agentic loop | 0 |
| `ai-services/mcp-server/`, `rag-server/` | Tool transport and local retrieval | 1 |
| `ai-services/multi-agent-server/` | Planner, Worker, Reviewer, human decisions, JSONL audit, CLI | 2 |
| `scripts/devtools/review/` | `ai review` modes and the release decision | 2 |
| `shared/frontend/multi-agent/`, `shared/testkit/` | Shared workflow panel; endpoint client, JUnit summary, `FakeMultiAgentServer` | 2 |
| `.pre-commit-config.yaml`, `scripts/security/` | Security hooks and report | 2 |
| `.github/workflows/` | `student-N.yml`, `integration-ci.yml`; `cloud-deployment.yml` | 0–2 |
| `deployment/azure/`, `docker-compose.azure.yml` | Bicep, VM scripts, TLS edge, systemd AI units | 2 |
| `docs/release-2/evidence/` | Security, CI, multi-agent, review, local and cloud evidence | 2 |

## 3 Release 2 design flow

![Figure 1 Release 2 integrated architecture](assets/release-2/release-2-architecture.png)

CRUD requests go from the browser through the shared edge to a feature frontend, its backend/API
and the database service it owns. The Release 1 flows are unchanged: an assistant turn goes from
the backend to AI-mode, which calls that feature's MCP tools and retrieves from its RAG corpus. In
Release 2 each backend also proxies the Multi-Agent Server over HTTP with `MULTI_AGENT_BASE_URL`
and a service token. The Planner plans read-only steps, the Worker gathers evidence through MCP,
the Reviewer checks it, and only a human decision ends the run. The shared panel shows every
stage. No AI service opens a feature database or runs in Docker.

[[FEATURE_FLOWS]]

![Figure 2 Multi-agent flow, using the Feature 1 readiness review](assets/release-2/multi-agent-sequence.png)

### Student 1

The `f1-release-readiness-review` workflow recommends whether a candidate dataset release is ready
to publish. Seven proxy routes under `/api/data-platform/v1/release-reviews` fix the template
server-side and hide other features' runs. Its allowlist omits `data.release_publish.v1`, so a
review never publishes (Figure 2).

### Student 2

[[TODO: Burhan Naeem | Describe F2's multi-agent design flow in about 40 words: template, read-only tools and proxy routes]]

### Student 3

[[TODO: James Huang | Describe F3's multi-agent design flow in about 40 words: template, read-only tools and proxy routes]]

### Student 4

[[TODO: Michael White | Describe F4's multi-agent design flow in about 40 words: template, read-only tools and proxy routes]]

### Student 5

[[TODO: Derek Song | Describe F5's multi-agent design flow in about 40 words: template, read-only tools and proxy routes]]

## 4 Cloud deployment and CI/CD architecture

![Figure 3 Azure reference architecture](assets/release-2/azure-reference-architecture.png)

We chose Azure ([ADR-048](../architecture/decisions/ADR-048-azure-vm-hosting.md)). One Ubuntu VM
runs the unchanged Compose model with a production override, because the AI tier must stay a
host process and container-only services cannot host it.

- **Hosting:** images are built once per commit, pushed to Azure Container Registry tagged with
  the Git SHA and pulled by the VM's managed identity.
- **Endpoints:** a public IP with a DNS label; the NSG admits only 80 and 443. Caddy terminates TLS
  in front of the nginx edge; databases stay on internal networks.
- **Secrets:** Key Vault, read by the managed identity. GitHub signs in with OIDC.
- **AI tier:** AI-mode, MCP, RAG and Multi-Agent are systemd units, off unless
  `PROPERTYSCOPE_CLOUD_AI=true`.

![Figure 4 DevOps flow from commit to Azure](assets/release-2/devops-flow.png)

A commit runs the pre-commit hooks. A push to `main` runs each `student-N.yml` and
`integration-ci.yml`. A successful Integration CI push run triggers `cloud-deployment.yml`, which
runs the reusable [`deploy.sh`](../../deployment/azure/README.md) steps shown.

[[TODO: Matthew Shelton | Azure is prepared but not provisioned. After the first deployment, state the subscription, region and VM size used, and whether cloud deployment should also wait for the five student workflows]]

## 5 Pre-commit security testing

`.pre-commit-config.yaml` runs three security hooks on every `git commit`, beside Ruff, formatting
and mypy: Ruff `S` (flake8-bandit) rules, detect-secrets against the reviewed `.secrets.baseline`,
and pip-audit of `uv.lock`. `integration-ci.yml` repeats them on every push.
`dev.py security report` records results per slice and owner:

[[SECURITY_SUMMARY]]

In the recorded [commit run](../release-2/evidence/security/pre-commit-commit-run.txt),
detect-secrets first blocked a commit. After seven false positives were reviewed into the
baseline, the same commit passed:

```text
security: Ruff flake8-bandit rules (S)..........................Passed
security: detect-secrets against .secrets.baseline..............Passed
security: pip-audit of locked dependencies (uv.lock)............Passed
```

[[TODO: Matthew Shelton | Regenerate the security report on main at the evidence freeze; the committed one scanned a release-2/wrap-up-shared-f1 branch commit]]

[[TODO: Burhan Naeem | Fix or justify F2's pending-owner Ruff S findings, then regenerate the report]]

[[TODO: James Huang | Fix or justify F3's pending-owner Ruff S findings, then regenerate the report]]

[[TODO: Michael White | Fix or justify F4's pending-owner Ruff S findings, then regenerate the report]]

[[TODO: Derek Song | Fix or justify F5's pending-owner Ruff S findings, then regenerate the report]]

## 6 Post-commit CI/CD testing

Each `student-N.yml` starts its feature's Compose stack in GitHub Actions with the AI tier
disabled and runs `pytest -m endpoint` against two endpoint functions of its backend/API. A JUnit
step summary requires at least two passes and the XML is uploaded. `collect_ci_evidence.py`
retains each run's record, reports and log under `evidence/ci/`.

[[CI_EVIDENCE]]

### Student 1

`student-1.yml` loads fixture data with the acquisition pipeline, then runs the tests on the
feature origin (:5200) and through the shared edge (:5100):

1. `GET /api/data-platform/v1/properties/search`: contract-valid ranked matches for an accepted
   address; invalid queries return structured problems.
2. `/api/data-platform/v1/sources`: create, list, read, update and delete a source definition;
   invalid, duplicate and non-JSON bodies are rejected and not persisted.

### Student 2

[[TODO: Burhan Naeem | Name F2's two endpoint functions and what each test checks (about 60 words)]]

### Student 3

[[TODO: James Huang | Name F3's two endpoint functions and what each test checks (about 60 words)]]

### Student 4

[[TODO: Michael White | Name F4's two endpoint functions and what each test checks (about 60 words)]]

### Student 5

[[TODO: Derek Song | Name F5's two endpoint functions and what each test checks (about 60 words)]]

## 7 Testing review

`dev.py ai review testing` collects the security report and each `ci/student-N.md`, builds a
deterministic checklist and reviews it through the shared loop (`review-testing.v2`). The verdict
is the stricter of the model's and the checklist's; each review appends to the validation log.

[[REVIEW_SUMMARY testing]]

[[TODO: Matthew Shelton | Re-run the testing review once all five CI records exist; the committed review predates them]]

## 8 Local deployment evidence

`uv run scripts/dev.py stack up` starts the host AI tier (AI-mode, MCP, RAG and the Multi-Agent
Server) and then the Compose application. Backends reach the host services through
`host.docker.internal`. `scripts/capture_local_deployment.py` checks the running system, including
that each AI service listens from a host process, not a container. Each server logs to its own
terminal.

[[LOCAL_EVIDENCE]]

[[TODO: Matthew Shelton | Recapture the local deployment report on main at the evidence freeze; this capture ran on a branch commit]]

## 9 Cloud deployment report and review

`cloud-deployment.yml` writes the deployment report. `deploy.sh smoke` checks the home page, every
feature route, one create, read and delete case per feature, and that the AI tier is disabled.
`dev.py ai review cloud` reviews this evidence; a named person then records the release decision
with `ai review decide`, which refuses if the evidence changed since the review.

[[CLOUD_SUMMARY]]

[[REVIEW_SUMMARY cloud]]

![Figure 5 Deployed home page on Azure](assets/release-2/screenshots/azure-home.png)

## 10 Multi-agent workflow evidence

The server stores runs in SQLite and appends state transitions to `workflow_history.jsonl` and
handoffs, model and tool calls and decisions, with actor and time, to `coordination_audit.jsonl`.
`multi-agent-server export` copies a run into the evidence folder.

[[MULTI_AGENT_RUNS]]

### Multi-agent workflow review

`dev.py ai review multi-agent` checks every export for all four stages, legal transitions,
attributed human decisions and allowlisted tool calls.

[[REVIEW_SUMMARY multi-agent]]

### Student 1

UI run `18740ca5` reviewed a real 680-record ABS CPI candidate on 10 October with the model
provider. In round 1 the Reviewer recommended approve; the human chose correct, asking for
completeness against the ABS source. In round 2 the Reviewer recommended correct, because the
read-only tools cannot fetch ABS totals, and the human accepted step `release` only. Nothing was
published. Terminal run `c17c66cc` used the same template from the CLI.

[[WORKFLOW_HISTORY multi-agent/student-1/18740ca5-ui]]

![Figure 6 F1 round 1 Reviewer recommendation in the shared panel](../release-2/evidence/multi-agent/student-1/18740ca5-ui/screenshots/04-round1-reviewer.png)

![Figure 7 F1 recorded human decisions](../release-2/evidence/multi-agent/student-1/18740ca5-ui/screenshots/08-final-decisions.png)

### Student 2

[[TODO: Burhan Naeem | Summarise F2's exported run in about 50 words: input, recommendation and human decision]]

### Student 3

[[TODO: James Huang | Summarise F3's exported run in about 50 words: input, recommendation and human decision]]

### Student 4

[[TODO: Michael White | Summarise F4's exported run in about 50 words: input, recommendation and human decision]]

### Student 5

[[TODO: Derek Song | Summarise F5's exported run in about 50 words: input, recommendation and human decision]]

## 11 GitHub commit logs

Commit history:
[https://github.com/MattShelton04/41026ASDProject/commits/main](https://github.com/MattShelton04/41026ASDProject/commits/main).
Section 12 lists each student's commits.

## 12 Contribution logs

### Student 1 Matthew Shelton

| Date | Commit | Release 2 work |
|---|---|---|
| 8 Oct | [36a4c26](https://github.com/MattShelton04/41026ASDProject/commit/36a4c26) | Requirements, implementation plan and per-part responsibilities |
| 9 Oct | [f86f787](https://github.com/MattShelton04/41026ASDProject/commit/f86f787) | Multi-Agent Server, review modes, security scans, endpoint test kit, Azure preparation |
| 10 Oct | [bef57da](https://github.com/MattShelton04/41026ASDProject/commit/bef57da) | Shared multi-agent panel, F1 readiness review, live UI evidence |
| 10 Oct | [06e0ed0](https://github.com/MattShelton04/41026ASDProject/commit/06e0ed0) | Panel redesigned as a live mission relay |
| 15 Oct | [d449a43](https://github.com/MattShelton04/41026ASDProject/commit/d449a43) | CI evidence collection, stack reliability and F1 improvements |

[[TODO: Matthew Shelton | Add the report, local evidence and Azure deployment commits]]

### Student 2 Burhan Naeem

[[TODO: Burhan Naeem | Add a Date / Commit / Release 2 work table of your identifiable commits (about 60 words)]]

### Student 3 James Huang

[[TODO: James Huang | Add a Date / Commit / Release 2 work table of your identifiable commits (about 60 words)]]

### Student 4 Michael White

[[TODO: Michael White | Add a Date / Commit / Release 2 work table of your identifiable commits (about 60 words)]]

### Student 5 Derek Song

[[TODO: Derek Song | Add a Date / Commit / Release 2 work table of your identifiable commits (about 60 words)]]

## 13 Bonus evidence

No bonus is claimed yet. Endpoint (B5) and data (B6) security controls, their validation scripts
and the B1–B4 AI units are prepared in `deployment/azure/`, but none has run on Azure.

[[TODO: Matthew Shelton | For each bonus claimed, link its validation output under evidence/bonus/; otherwise keep "No bonus is claimed"]]

## 14 Showcase video

[[TODO: Group | Link the published showcase video (at most 10 minutes) and record which students participated]]

<!-- RELEASE2_METADATA
schema_version: 1
baseline: '[[BASELINE]]'
repository_url: https://github.com/MattShelton04/41026ASDProject
showcase_url: ''
sections:
  overview: 1 Project overview
  repository: 2 Final repository structure
  design: 3 Release 2 design flow
  architecture: 4 Cloud deployment and CI/CD architecture
  security: 5 Pre-commit security testing
  ci: 6 Post-commit CI/CD testing
  testing_review: 7 Testing review
  local: 8 Local deployment evidence
  cloud: 9 Cloud deployment report and review
  multi_agent: 10 Multi-agent workflow evidence
  commits: 11 GitHub commit logs
  contributions: 12 Contribution logs
  bonus: 13 Bonus evidence
  showcase: 14 Showcase video
evidence:
- kind: security-report
  section: 5 Pre-commit security testing
  path: docs/release-2/evidence/security/pre-commit-report.md
  boundary: Local scans of the recorded commit; pending-owner findings are listed per slice.
- kind: ci
  student: 1
  section: 6 Post-commit CI/CD testing
  path: docs/release-2/evidence/ci/student-1.md
  boundary: Successful student-1.yml push run on main at d449a43; AI tier disabled in CI.
- kind: local-deployment
  section: 8 Local deployment evidence
  path: docs/release-2/evidence/local/local-deployment-report.md
  boundary: Running local ps-dev stack with real published data; host AI services outside Docker.
- kind: testing-review
  section: 7 Testing review
  path: docs/release-2/evidence/reviews/testing-review.md
  boundary: Shared loop review of the committed security and CI evidence.
- kind: multi-agent-review
  section: Multi-agent workflow review
  path: docs/release-2/evidence/reviews/multi-agent-review.md
  boundary: Shared loop review of the exported workflow histories and audits.
- kind: multi-agent
  student: 1
  section: 10 Multi-agent workflow evidence
  path: docs/release-2/evidence/multi-agent/student-1/18740ca5-ui/summary.md
  boundary: Live local stack, model provider, real ABS CPI candidate; nothing published.
contributions:
- student: 1
  section: Student 1 Matthew Shelton
  commits:
  - 36a4c26
  - f86f787
  - bef57da
  - 06e0ed0
  - d449a43
attendance: {}
-->
