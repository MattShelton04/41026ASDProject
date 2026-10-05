# Release 2 requirements

Source: Canvas Assessment 3 brief and rubric (captured 5 October 2026). This file restates what we
must deliver in repository terms. If it disagrees with the brief, the brief wins.

| Item | Value |
|---|---|
| Weight | 30 marks + up to 6 bonus (rubric total 36) |
| Showcase | Friday 23 October 2026, in class. Video of 10 minutes or less plus Q&A; every student takes part |
| Report | One `group-20.pdf`, uploaded by one member, one attempt, due 25 October 2026 23:59 Sydney time |
| Cloud | **Microsoft Azure** (group decision) |
| Integration rule | A feature that is not integrated scores **zero** on the working-software criteria |

## Functional requirements

IDs are ours. **Rubric** gives the marking criterion number from the brief (B = bonus).

### Retained from Release 1

| ID | Requirement | Rubric |
|---|---|---|
| R2-01 | All five features' frontend, backend/API and database services stay integrated and support their CRUD functions, both locally and in the cloud | 1, 7 |
| R2-02 | AI-mode, MCP and RAG stay shared, non-containerised local services. None of them may be added to Docker Compose | 1 |
| R2-03 | The agentic loop keeps its Release 0 behaviour and the Release 1 `mcp`/`rag` validation modes | 8 |

### Multi-Agent Server

| ID | Requirement | Rubric |
|---|---|---|
| R2-10 | One shared, non-containerised local Multi-Agent Server coordinates Planner, Worker and Reviewer agents | 2 |
| R2-11 | The Planner creates the workflow plan, names the evidence it needs and defines the work | 2 |
| R2-12 | The Worker carries out the plan using evidence supplied by the application | 2 |
| R2-13 | The Reviewer checks the Worker's output against the plan and the evidence, flags risks and makes recommendations | 2 |
| R2-14 | A human reviewer records the final decision: approve, correct, partially accept or reject | 2 |
| R2-15 | Workflows can be run from the terminal and from the frontend UI. The UI path is Frontend → Backend/API → Multi-Agent Server → Planner → Worker → Reviewer → Human Review → response | 2 |
| R2-16 | Every run keeps a workflow history and a coordination/audit log that can go into the report | 2, 9 |
| R2-17 | Each student integrates their own feature with the Multi-Agent Server and demonstrates the full workflow | 2, 10 |

### Agentic-loop review modes

| ID | Requirement | Rubric |
|---|---|---|
| R2-20 | **Multi-Agent Workflow Review** mode reviews workflow evidence and produces implementation and review recommendations | 8 |
| R2-21 | **Testing Report Review** mode reviews the pre-commit security results and the post-commit CI endpoint results | 8 |
| R2-22 | **Cloud Deployment Report Review** mode reviews deployment and validation evidence to support the human release decision | 8 |
| R2-23 | Each mode writes a review report and a review/validation log. The loop runs locally and stays non-containerised | 8, 9 |

### Testing

| ID | Requirement | Rubric |
|---|---|---|
| R2-30 | Pre-commit security scans run locally when code is committed: Ruff security rules, detect-secrets and pip-audit (or approved equivalents) | 3 |
| R2-31 | A pre-commit security testing report is produced, and each student records results for their own contribution | 3, 9 |
| R2-32 | Each student's `student-N.yml` runs automated tests for **two endpoint functions** of their backend/API after every push | 4 |
| R2-33 | Each student produces a CI testing report with links to successful workflow runs | 4, 9 |

### Deployment

| ID | Requirement | Rubric |
|---|---|---|
| R2-40 | Local deployment: features run in Docker Compose. AI-mode, MCP, RAG, Multi-Agent and the loop run as host processes and are reached from the UI through each backend | 1 |
| R2-41 | Local deployment report, including logs of multi-server testing across several terminals | 9 |
| R2-42 | Reusable deployment scripts and Infrastructure as Code for Azure | 5 |
| R2-43 | `cloud-deployment.yml` deploys to Azure through GitHub Actions **after** the required CI validation has passed | 6 |
| R2-44 | The cloud frontend, backend/API, database and CRUD functions work. AI-mode, MCP, RAG and Multi-Agent are **disabled by default** | 7 |
| R2-45 | Cloud deployment report showing frontend access and core functions, a Cloud Deployment Review, and the final **human release decision** | 9 |

### Bonus (only marked once R2-44 is working)

| ID | Requirement | Bonus |
|---|---|---|
| R2-B1 | AI-mode enabled in Azure, with a successful interaction through the application | +1 |
| R2-B2 | MCP enabled in Azure, with a successful tool interaction through the application | +1 |
| R2-B3 | RAG enabled in Azure, with a grounded answer that uses retrieved context | +1 |
| R2-B4 | Multi-Agent enabled in Azure, with a successful Planner → Worker → Reviewer workflow | +1 |
| R2-B5 | Endpoint security on the exposed frontend and API, with configuration and validation evidence | +1 |
| R2-B6 | Data security for data, secrets, credentials and storage, with configuration and validation evidence | +1 |

The rubric scores AI bonuses as cumulative tiers (AI-mode → +MCP → +RAG → +Multi-Agent, 0–4) and
security as endpoint, then endpoint plus data (0–2). Enable them in that order. Before relying on
any non-cumulative combination, ask the tutor.

## Report contents (criterion 9)

1. Project overview: team, feature allocation, and what Release 2 adds to Release 1.
2. Final repository structure, covering both the Release 1 and Release 2 artefacts.
3. Release 2 design flow per student: the CRUD flow, the Release 1 AI-mode/MCP/RAG flows and the
   multi-agent flow.
4. Azure reference architecture and DevOps flow: source control → pre-commit scans → GitHub
   Actions → two endpoint tests per student → Docker build/validation → `cloud-deployment.yml` →
   Azure.
5. Pre-commit security testing report.
6. Each student's post-commit CI endpoint testing report.
7. Testing Review output and its validation log.
8. Local deployment report, with multi-terminal logs.
9. Cloud deployment report, Cloud Deployment Review and the human release decision.
10. Multi-agent workflow evidence: history and coordination/audit logs.
11. GitHub commit history URL and each student's contribution log.
12. Bonus evidence for each control or service claimed.
13. Showcase video URL.

## Showcase video must show (criterion 10)

- Multi-agent workflow through the frontend UI, including human review
- The frontend running both locally and on Azure
- Pre-commit security scans running during a commit
- Post-commit CI endpoint tests in GitHub Actions
- All three agentic-loop review modes
- Every student explaining and defending their own Release 2 contribution
- Any bonus services or controls we claim

## Constraints

- AI-mode, MCP, RAG, Multi-Agent and the loop must never be Compose services or have a Dockerfile
  (brief, ADR-046). In Azure they also run as host processes.
- CI and the baseline cloud deployment run with the AI tier disabled. Tests use deterministic
  doubles; no provider key is needed.
- Every student's commits must be identifiable. Each student does their own slice's work.
- Secrets never go into Git. The cloud uses Key Vault and GitHub OIDC, not long-lived credentials.
