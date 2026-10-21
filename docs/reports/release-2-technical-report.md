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
backend/API and database slice; Matthew also leads the shared platform. Release 2 keeps the
Release 0–1 AI-mode, agentic loop, MCP and RAG servers, and adds:

- a host Multi-Agent Server (Planner → Worker → Reviewer → human review), called through a
  feature's backend;
- three review modes: multi-agent workflow, testing report and cloud deployment;
- pre-commit security scans, and a `student-N.yml` per student for post-commit endpoint tests;
- Azure deployment with the AI tier disabled by default.

| Student | Feature | Release 2 responsibility |
|---|---|---|
| 1 Matthew Shelton (24763373) | F1 Data platform and property discovery | Shared platform (Multi-Agent Server, review modes, security scans, test kit, Azure); F1 workflow and endpoint tests |
| 2 Burhan Naeem (24764134) | F2 Property sales and market cases | F2 workflow, endpoint tests and evidence |
| 3 James Huang (24970865) | F3 Suburb, crime and liveability analytics | F3 workflow, endpoint tests and evidence |
| 4 Michael White (24846267) | F4 Site, planning and building due diligence | F4 workflow, endpoint tests and evidence |
| 5 Derek Song (24833978) | F5 Buyer journey workspace | F5 workflow, endpoint tests and evidence |

## 2 Final repository structure

| Path | Contents | Release |
|---|---|---|
| `student-1/` … `student-5/` | Feature slices: UI, API, database service, tools, corpus | 0–1 |
| `student-1/config/multi-agent/`, `student-1/tests/endpoints/` | F1 workflow template and endpoint tests | 2 |
| `ai-services/ai-mode/`, `agent-core/` | AI-mode run API and the shared agentic loop | 0 |
| `ai-services/mcp-server/`, `rag-server/` | Tool transport and local retrieval | 1 |
| `ai-services/multi-agent-server/` | Planner, Worker, Reviewer, decisions, JSONL audit, CLI | 2 |
| `scripts/devtools/review/` | Review modes and release decision | 2 |
| `shared/frontend/multi-agent/`, `shared/testkit/` | Shared workflow panel; endpoint client, JUnit summary, `FakeMultiAgentServer` | 2 |
| `.pre-commit-config.yaml`, `scripts/security/` | Security hooks and report | 2 |
| `.github/workflows/` | `student-N.yml`, `integration-ci.yml`; `cloud-deployment.yml` | 0–2 |
| `deployment/azure/`, `docker-compose.azure.yml` | Bicep, VM scripts, TLS edge, systemd AI units | 2 |
| `docs/release-2/evidence/` | Security, CI, multi-agent, review, local and cloud evidence | 2 |

## 3 Release 2 design flow

![Figure 1 Release 2 integrated architecture](assets/release-2/release-2-architecture.png)

CRUD requests pass from the browser through the shared edge to a feature frontend, its backend/API
and its own database service. Assistant turns keep the Release 1 path through AI-mode to the
feature's MCP tools and RAG corpus. A backend with a workflow also proxies the Multi-Agent Server
over HTTP with a service token, and the shared panel shows each stage up to the human decision.
No AI service opens a feature database or runs in Docker.

[[FEATURE_FLOWS]]

![Figure 2 Multi-agent flow, using the Feature 1 readiness review](assets/release-2/multi-agent-sequence.png)

### Student 1

`f1-release-readiness-review` recommends whether a candidate dataset release is ready to publish.
Seven proxy routes under `/api/data-platform/v1/release-reviews` fix the template server-side and
hide other features' runs. The allowlist omits `data.release_publish.v1`, so a review never
publishes.

### Student 2

`f2-market-case-brief` summarises one saved market case's recorded sale observations. Seven
proxy routes under `/api/market-intelligence/v1/market-briefs` fix the template server-side
and hide other features' runs. Both allowlisted tools, `market.cases.inspect.v1` and
`market.sales.summary.v1`, are read-only, so a brief never alters the case it describes.

### Student 3

[[TODO: James Huang | Describe F3's multi-agent design flow in about 40 words: template, read-only tools and proxy routes]]

### Student 4

`f4-evidence-readiness-review` decides whether one saved site review has enough planning and
building evidence to hand to a qualified professional, and drafts the questions to ask. Eight
proxy routes under `/api/due-diligence/v1/evidence-reviews` fix the template server-side and hide
other features' runs. Both allowlisted tools, `duediligence.review.inspect.v1` and
`duediligence.evidence.summary.v1`, are read-only, so a review never alters the site review.

### Student 5

[[TODO: Derek Song | Describe F5's multi-agent design flow in about 40 words: template, read-only tools and proxy routes]]

## 4 Cloud deployment and CI/CD architecture

![Figure 3 Azure reference architecture](assets/release-2/azure-reference-architecture.png)

We chose Azure ([ADR-048](../architecture/decisions/ADR-048-azure-vm-hosting.md)): one Ubuntu VM
(`Standard_D4as_v4`, `newzealandnorth`) runs the Compose model with a production override, because
the AI tier must stay a host process. Its managed identity reads Container Registry and Key Vault;
GitHub signs in with OIDC. The NSG admits only 80 and 443, Caddy terminates TLS, and the four AI
systemd units stay off unless `PROPERTYSCOPE_CLOUD_AI=true`.

![Figure 4 DevOps flow from commit to Azure](assets/release-2/devops-flow.png)

A commit runs the pre-commit hooks; a push to `main` runs `integration-ci.yml` and the five
`student-N.yml` workflows, whose endpoint tests are each owner's deliverable. `cloud-deployment.yml`
gates the release: `verify-ci` waits until all six pass for the commit and `build-validate` builds
and validates every image. Only then does `deploy` run these reusable
[scripts](../../deployment/azure/README.md) in the protected `production` environment:

| Script or template | Role |
|---|---|
| `deploy.sh provision`, `secrets` | Resource group, `main.bicep`, missing Key Vault secrets |
| `deploy.sh push`, `deploy` | Images to ACR; VM converged through `az vm run-command` |
| `deploy.sh smoke`, `status`, `logs` | Public smoke test and VM state |
| `deploy.sh ai on`/`off`, `ai-probe` | Bonus AI tier and its B1–B4 probe |
| `deploy.sh validate-endpoint`, `validate-data` | B5 and B6 checks |
| `main.bicep`, `modules/` | Network, registry, Key Vault, VM, RBAC, shutdown, budget |
| `validate-iac.sh` | Offline Bicep, shell, Caddy and nginx checks (CI `iac-lint`) |

![Figure 5 Deployed resources and inbound rules](assets/release-2/screenshots/azure-resources.png)

## 5 Pre-commit security testing

`.pre-commit-config.yaml` runs three security hooks on every `git commit`: Ruff `S`
(flake8-bandit) rules, detect-secrets against the reviewed `.secrets.baseline`,
and pip-audit of `uv.lock`. `integration-ci.yml` repeats them on every push.
`dev.py security report` records results per slice and owner:

[[SECURITY_SUMMARY]]

In the recorded [commit run](../release-2/evidence/security/pre-commit-commit-run.txt),
detect-secrets first blocked the commit; after seven false positives were reviewed into the
baseline, it passed:

```text
security: Ruff flake8-bandit rules (S)..........................Passed
security: detect-secrets against .secrets.baseline..............Passed
security: pip-audit of locked dependencies (uv.lock)............Passed
```

[[TODO: Matthew Shelton | Regenerate the security report on main at the evidence freeze; the committed one scanned a release-2/wrap-up-shared-f1 branch commit]]

[[TODO: James Huang | Fix or justify F3's pending-owner Ruff S findings, then regenerate the report]]

[[TODO: Derek Song | Fix or justify F5's pending-owner Ruff S findings, then regenerate the report]]

## 6 Post-commit CI/CD testing

Each owner's `student-N.yml` should start the feature's Compose stack with AI disabled, run
`pytest -m endpoint` on two endpoint functions and publish the Shared test kit's JUnit summary (at
least two passes). `collect_ci_evidence.py` keeps each run's record, reports and log.

[[CI_EVIDENCE]]

### Student 1

`student-1.yml` loads fixture data, then tests the feature origin (:5200) and the shared edge
(:5100):

1. `GET /api/data-platform/v1/properties/search`: contract-valid ranked matches for an accepted
   address; invalid queries return structured problems.
2. `/api/data-platform/v1/sources`: create, list, read, update and delete a source definition;
   invalid, duplicate and non-JSON bodies are rejected and not persisted.

Suburb-map tests also run; two skip without a suburb-boundaries release.

### Student 2

`student-2.yml` tests two endpoint functions on the feature origin (:5300):

1. `POST /api/market-intelligence/v1/market-cases`: a valid case is persisted at version 1
   and readable at its own URL; a window that ends before it starts is refused `422
   invalid_market_case` and writes nothing.
2. `PUT /api/market-intelligence/v1/market-cases/{id}`: the current version applies the
   change and advances the version; a stale version is refused `409 version_conflict` and
   leaves the first writer's value in place.

Both are answered by Feature 2 alone, so the job stays green when another feature is down.

### Student 3

[[TODO: James Huang | Name F3's two endpoint functions and what each test checks (about 60 words)]]

### Student 4

`student-4.yml` tests two endpoint functions on the feature origin (:5400):

1. `POST /api/due-diligence/v1/site-reviews`: a valid review is persisted as a version 1 draft,
   readable at its own URL and then deleted; five invalid bodies and a non-JSON body are refused
   `422 invalid_site_review` and write nothing.
2. `GET /api/due-diligence/v1/site-reviews/{id}/evidence`: a seeded review returns schema-valid
   constraint and building records for its own property only; an unknown or deleted review
   returns `404 site_review_not_found`.

All ten cases passed in the recorded run.

### Student 5

[[TODO: Derek Song | Name F5's two endpoint functions and what each test checks (about 60 words)]]

## 7 Testing review

`dev.py ai review testing` checks the security report and each `ci/student-N.md` against a
deterministic checklist and reviews them through the shared loop. The stricter verdict wins, and
each review appends to the validation log.

[[REVIEW_SUMMARY testing]]

[[TODO: Matthew Shelton | Re-run the testing review once all five CI records exist; the committed review predates them]]

## 8 Local deployment evidence

`dev.py stack up` starts the four host AI services, then the Compose application; backends reach
them through `host.docker.internal`. `capture_local_deployment.py` checks the running system,
including that each AI service is a host process, not a container. The committed capture recorded
the host services through managed log files; the freeze recapture runs each in its own foreground
terminal.

[[LOCAL_EVIDENCE]]

[[TODO: Matthew Shelton | Recapture the local deployment report on main at the evidence freeze; this capture ran on a branch commit]]

## 9 Cloud deployment report and review

`deploy.sh smoke` checks the home page, every feature route, create, read and delete per feature,
and that AI-mode answers `503 ai_disabled`; all 37 checks passed. `dev.py ai review cloud`
reviews the evidence, then a named person records the release decision with `ai review decide`,
which refuses if the evidence changed.

[[CLOUD_SUMMARY]]

Run 39112162750 job timings: `verify-ci` 15 s, `build-validate` 42 s, `deploy` 10 min 39 s
([run record](../release-2/evidence/cloud/workflow-run.md),
[step logs](../release-2/evidence/cloud/logs/),
[`vm-deploy.log`](../release-2/evidence/cloud/vm-deploy.log)). Run
[39098352903](https://github.com/MattShelton04/41026ASDProject/actions/runs/39098352903) also
ran the Bicep provision step (1 min 29 s).

![Figure 6 Gated cloud deployment run](assets/release-2/screenshots/azure-workflow.png)

![Figure 7 Deployed application with real Feature 1 data](assets/release-2/screenshots/azure-app.png)

[[REVIEW_SUMMARY cloud]]

## 10 Multi-agent workflow evidence

The server keeps runs in SQLite, state transitions in `workflow_history.jsonl`, and handoffs,
model and tool calls and decisions, with actor and time, in `coordination_audit.jsonl`;
`multi-agent-server export` copies a run into the evidence.

[[MULTI_AGENT_RUNS]]

### Multi-agent workflow review

`dev.py ai review multi-agent` checks every export for all four stages, legal transitions,
attributed human decisions and allowlisted tool calls.

[[REVIEW_SUMMARY multi-agent]]

### Student 1

UI run `18740ca5` (10 October, model provider) reviewed a real 680-record ABS CPI candidate.
Round 1: the Reviewer recommended approve; the human chose correct, asking for completeness against
ABS. Round 2: the Reviewer recommended correct, as read-only tools cannot fetch ABS totals; the
human accepted step `release` only, publishing nothing. Terminal run `c17c66cc` used the same
template.

[[WORKFLOW_HISTORY multi-agent/student-1/18740ca5-ui]]

![Figure 8 F1 Reviewer recommendation, round 1](../release-2/evidence/multi-agent/student-1/18740ca5-ui/screenshots/04-round1-reviewer.png)

![Figure 9 F1 recorded human decisions](../release-2/evidence/multi-agent/student-1/18740ca5-ui/screenshots/08-final-decisions.png)

### Student 2

Run `f1c290a2` briefed `Sydney example - full history`. The Reviewer recommended approve on
all eleven checks passing. I sent it back: the checks read the tool results, while the prose
summary reported the figures without the limitations. Round two restated them with the
synthetic-data disclosure, and I approved it, 0 failed and 11 passed.

### Student 3

[[TODO: James Huang | Summarise F3's exported run in about 50 words: input, recommendation and human decision]]

### Student 4

Run `2956e465` reviewed seeded review 1 (11 Example Street, Sydney). The Reviewer recommended
approve on all ten checks passing. I sent it back: the draft referred to the saved question list,
missed two conflicting records and did not plainly disclose seeded data. Round two fixed all three,
and I approved it, noting three questions still to write.

### Student 5

[[TODO: Derek Song | Summarise F5's exported run in about 50 words: input, recommendation and human decision]]

## 11 GitHub commit logs

Commit history:
[https://github.com/MattShelton04/41026ASDProject/commits/main](https://github.com/MattShelton04/41026ASDProject/commits/main).
Matthew's commits:
[https://github.com/MattShelton04/41026ASDProject/commits/main?author=MattShelton04](https://github.com/MattShelton04/41026ASDProject/commits/main?author=MattShelton04);
each student's GitHub username filters the same way, and Section 12 lists their commits.

## 12 Contribution logs

### Student 1 Matthew Shelton

| Date | Commit | Release 2 work |
|---|---|---|
| 8–10 Oct | [36a4c26](https://github.com/MattShelton04/41026ASDProject/commit/36a4c26), [f86f787](https://github.com/MattShelton04/41026ASDProject/commit/f86f787), [bef57da](https://github.com/MattShelton04/41026ASDProject/commit/bef57da), [06e0ed0](https://github.com/MattShelton04/41026ASDProject/commit/06e0ed0) | Multi-Agent Server, review modes, security scans, test kit, panel, F1 review |
| 15–17 Oct | [d449a43](https://github.com/MattShelton04/41026ASDProject/commit/d449a43), [07b1c81](https://github.com/MattShelton04/41026ASDProject/commit/07b1c81), [72f3272](https://github.com/MattShelton04/41026ASDProject/commit/72f3272), [fdc5111](https://github.com/MattShelton04/41026ASDProject/commit/fdc5111), [93d0f53](https://github.com/MattShelton04/41026ASDProject/commit/93d0f53) | CI and local evidence, report builder, release gate |
| 17 Oct | [5e90231](https://github.com/MattShelton04/41026ASDProject/commit/5e90231), [ad2b443](https://github.com/MattShelton04/41026ASDProject/commit/ad2b443), [71764a5](https://github.com/MattShelton04/41026ASDProject/commit/71764a5), [cd8e56d](https://github.com/MattShelton04/41026ASDProject/commit/cd8e56d) | Azure switch-on, site login, security fixes |
| 18 Oct | [b638c86](https://github.com/MattShelton04/41026ASDProject/commit/b638c86), [53a2143](https://github.com/MattShelton04/41026ASDProject/commit/53a2143), [65de8f6](https://github.com/MattShelton04/41026ASDProject/commit/65de8f6), [b71c49c](https://github.com/MattShelton04/41026ASDProject/commit/b71c49c), [3c25c08](https://github.com/MattShelton04/41026ASDProject/commit/3c25c08) | F1 suburb-map API, real data on Azure |
| 18 Oct | [c1dab31](https://github.com/MattShelton04/41026ASDProject/commit/c1dab31), [3ea2932](https://github.com/MattShelton04/41026ASDProject/commit/3ea2932), [817ef77](https://github.com/MattShelton04/41026ASDProject/commit/817ef77), [0cf5e3f](https://github.com/MattShelton04/41026ASDProject/commit/0cf5e3f) | Cloud AI Tier, cloud and bonus evidence, release decision |

### Student 2 Burhan Naeem

| Date | Commit | Release 2 work |
|---|---|---|
| 21 Oct 2026 | [`4162bbd`](https://github.com/MattShelton04/41026ASDProject/commit/4162bbdc2d2614cbf6c5f2dd74d8a6fdb23b0ab2) (#162) | Multi-agent market case brief: workflow manifest, seven proxy routes, the panel and its addressable runs, two endpoint functions in CI, and Feature 2's Ruff security findings cleared to 0 open and 0 pending-owner |
| 21 Oct 2026 | #163 | CI evidence for the green `student-2.yml` run on main, and this chapter's Feature 2 sections |

Commits are the squash merges of each pull request; #163 is assigned its hash on merge.

### Student 3 James Huang

[[TODO: James Huang | Add a Date / Commit / Release 2 work table of your identifiable commits (about 60 words)]]

### Student 4 Michael White

| Date | Commit | Release 2 work |
|---|---|---|
| 21 Oct 2026 | [`58def77`](https://github.com/MattShelton04/41026ASDProject/commit/58def77f180a557253c5fdb590a71a128e5e861c) (#164) | Endpoint tests for site-review creation and review evidence, run in `student-4.yml` with a JUnit summary; Feature 4's Ruff security findings cleared to 0 open and 0 pending-owner |
| 21 Oct 2026 | [`aa9b866`](https://github.com/MattShelton04/41026ASDProject/commit/aa9b8667ffda2429e7db4fc5c8a3b2820bd163bd) (#165) | Evidence readiness review: workflow manifest, eight proxy routes, the review-page panel, and the Release 1 question-extraction carry-over fix |
| 21 Oct 2026 | This PR | CI, security and multi-agent evidence, and this chapter's Feature 4 sections |

Commits are the squash merges of each pull request.

### Student 5 Derek Song

[[TODO: Derek Song | Add a Date / Commit / Release 2 work table of your identifiable commits (about 60 words)]]

## 13 Bonus evidence

We claim B1–B6. B1–B4 ran through the public edge in Cloud AI Tier run
[39119158736](https://github.com/MattShelton04/41026ASDProject/actions/runs/39119158736)
(`817ef779`, 18 October).

| Tier | Result and evidence | Run or source |
|---|---|---|
| B1 AI-mode | [PASS](../release-2/evidence/bonus/cloud-ai-probe.md) | AI-mode run `387591f0` |
| B2 MCP | [PASS](../release-2/evidence/bonus/cloud-ai-probe.md) | `data.releases.v1` over MCP, same run |
| B3 RAG | [PASS](../release-2/evidence/bonus/cloud-ai-probe.md) | Run `56c85266`, 2 citations |
| B4 Multi-Agent | [PASS](../release-2/evidence/bonus/cloud-ai-probe.md) | Run `2058658b`, rejected in the UI |
| B5 Endpoint security | [52 PASS, 0 FAIL](../release-2/evidence/bonus/endpoint-security.txt) | Cloud Deployment run 39112162750 |
| B6 Data security | [43 PASS, 0 FAIL](../release-2/evidence/bonus/data-security.txt) | Laptop, 18 October |

![Figure 10 B1–B4 through the Azure UI](assets/release-2/screenshots/azure-ai-bonus.png)

More [UI captures](../release-2/evidence/bonus/README.md#ui-captures-19-october).

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
  boundary: Successful student-1.yml push run on main at 817ef77; AI tier disabled in CI.
- kind: ci
  student: 2
  section: 6 Post-commit CI/CD testing
  path: docs/release-2/evidence/ci/student-2.md
  boundary: Successful student-2.yml push run on main at 4162bbd; AI tier disabled in CI.
- kind: ci
  student: 4
  section: 6 Post-commit CI/CD testing
  path: docs/release-2/evidence/ci/student-4.md
  boundary: Successful student-4.yml push run on main at aa9b866; AI tier disabled in CI.
- kind: local-deployment
  section: 8 Local deployment evidence
  path: docs/release-2/evidence/local/local-deployment-report.md
  boundary: Running local ps-dev stack with real published data; host AI services outside Docker.
- kind: cloud-deployment
  section: 9 Cloud deployment report and review
  path: docs/release-2/evidence/cloud/cloud-deployment-report.md
  boundary: Azure production VM at 3c25c08 with the AI tier off; real accepted Feature 1 releases.
- kind: cloud-workflow
  section: 9 Cloud deployment report and review
  url: https://github.com/MattShelton04/41026ASDProject/actions/runs/39112162750
  boundary: Manual dispatch on main, gate passed, production environment approved by a person.
- kind: cloud-review
  section: 9 Cloud deployment report and review
  path: docs/release-2/evidence/reviews/cloud-review.md
  boundary: Deterministic shared-loop review of the committed cloud evidence.
- kind: release-decision
  section: 9 Cloud deployment report and review
  path: docs/release-2/evidence/cloud/release-decision.md
  boundary: Named person's decision on review 44929d5d, bound to the hashed evidence bundle.
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
- kind: multi-agent
  student: 2
  section: 10 Multi-agent workflow evidence
  path: docs/release-2/evidence/multi-agent/student-2/f1c290a2-ui/summary.md
  boundary: Live local stack, model provider, seeded market case; read-only tools, nothing written.
- kind: multi-agent
  student: 4
  section: 10 Multi-agent workflow evidence
  path: docs/release-2/evidence/multi-agent/student-4/2956e465-ui/summary.md
  boundary: Live local stack, model provider with a deterministic round-2 Reviewer fallback, seeded site review; read-only tools, nothing written.
contributions:
- student: 2
  section: Student 2 Burhan Naeem
  commits:
  - 4162bbd
- student: 4
  section: Student 4 Michael White
  commits:
  - 58def77
  - aa9b866
- student: 1
  section: Student 1 Matthew Shelton
  commits:
  - 36a4c26
  - f86f787
  - bef57da
  - 06e0ed0
  - d449a43
  - 07b1c81
  - 72f3272
  - fdc5111
  - 93d0f53
  - 5e90231
  - ad2b443
  - 71764a5
  - cd8e56d
  - b638c86
  - 53a2143
  - 65de8f6
  - b71c49c
  - 3c25c08
  - c1dab31
  - 3ea2932
  - 817ef77
  - 0cf5e3f
attendance: {}
-->
