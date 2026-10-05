# Release 2 implementation plan

This plan delivers [requirements.md](requirements.md). Each part has its own scope and steps:
[Shared](parts/shared.md), [Feature 1](parts/feature-1.md), [Feature 2](parts/feature-2.md),
[Feature 3](parts/feature-3.md), [Feature 4](parts/feature-4.md), [Feature 5](parts/feature-5.md).

## Key decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Host on **Azure**, using **one Ubuntu VM** that runs the existing Compose stack. Images come from Azure Container Registry, and the VM is provisioned with Bicep | The course does not prescribe a hosting shape. A VM is the only Azure target where AI-mode, MCP, RAG and Multi-Agent can run as **non-containerised host processes**, as the brief and ADR-046 require, which the AI bonus needs. It reuses all 20 services, the nginx edge, PostGIS and the SQLite volumes without re-platforming |
| D2 | Run the AI tier on the VM as `systemd` units, with a single flag `PROPERTYSCOPE_CLOUD_AI=false` as the default | Gives an AI-disabled baseline (R2-44) and makes the bonus tiers (R2-B1–B4) a configuration change rather than a second deployment |
| D3 | Build the Multi-Agent Server as a new host package `ai-services/multi-agent-server` on port **5013** (`MULTI_AGENT_PORT`), started by `dev.py ai start` | Matches the existing host-runtime pattern. It may reuse `agent-core`, the provider adapters and MCP; student services reach it over HTTP only |
| D4 | Each feature registers **one workflow template** as a manifest in its own slice (`student-N/config/multi-agent/workflow.yaml`), as RAG corpora already do | Feature rules stay in the owning slice and the server stays domain-neutral |
| D5 | Run the review modes through the existing loop: `dev.py ai review {multi-agent,testing,cloud}` collects evidence files, runs an AI-mode review run, and writes a report and a JSONL log | Adds the modes to the same loop that holds R0/R1 behaviour. The runs also appear in Activity history |
| D6 | Put all evidence under `docs/release-2/evidence/` (layout below) | One place for the report builder and the review modes to read from |
| D7 | `cloud-deployment.yml` runs on `workflow_run` after Integration CI succeeds on `main`, or manually. It uses GitHub OIDC with a federated credential and a protected `production` environment | Satisfies the brief's "after the required CI/CD validation succeeds" with no stored cloud keys. Environment approval records a human in the loop |

ADRs to add: **ADR-047** (Multi-Agent Server boundary) and **ADR-048** (Azure VM hosting and the
cloud AI flag). Also update `shared-platform-design.md` and the root README.

## Target architecture

```text
Local:   Browser → shared edge :5100 → feature frontends/backends (Compose) → owned DBs
                                   backend ──HTTP──▶ AI-mode :5005 ─▶ MCP :5011 / RAG :5012
                                   backend ──HTTP──▶ Multi-Agent :5013 ─▶ Planner → Worker → Reviewer
                                                                   ▲ Worker evidence via MCP tools
                                                                   └ human decision posted back from UI

Azure:   GitHub Actions ─OIDC─▶ ACR (images:sha) + Bicep (RG, VNet/NSG, VM, Key Vault, ACR)
         Internet :443 ─▶ VM [Caddy TLS ─▶ nginx edge ─▶ Compose services, DBs on private network]
                          [systemd: ai-mode, mcp, rag, multi-agent; off unless PROPERTYSCOPE_CLOUD_AI=true]
         VM managed identity ─▶ Key Vault secrets; disks encrypted; no public DB/SSH ports
```

## Workstreams

| WS | Workstream | Lead | Inputs from features |
|---|---|---|---|
| A | Multi-Agent Server, contract, CLI and shared UI panel | Shared | Workflow manifest and backend proxy routes |
| B | Loop review modes and evidence collectors | Shared | Evidence files |
| C | Pre-commit security scans and report | Shared | Fix or justify findings in their own slice |
| D | Endpoint-test helper and CI report collector | Shared | Two endpoint tests in each `student-N.yml` |
| E | Azure IaC, deployment scripts, `cloud-deployment.yml`, cloud smoke test | Shared | Production config and a cloud CRUD smoke case per feature |
| F | Bonus: cloud AI tier, endpoint and data security | Shared | Each feature's AI and multi-agent paths working in the cloud |
| G | Evidence capture, report and video | All | Contribution logs, design flows, video segments |

## Timeline

| Dates | Milestone | Exit check |
|---|---|---|
| 6–8 Oct | C done; the A contract and server skeleton merged; D helper merged; Azure subscription and resource group ready | `git commit` runs all three scans; `multi-agent-server` health check passes; CI helper documented |
| 9–12 Oct | A server works end to end with a deterministic provider; E baseline deploy runs by hand; features add endpoint tests | A terminal workflow reaches `awaiting_human`; the cloud frontend loads; all five `student-N.yml` runs green |
| 13–16 Oct | Features ship workflow manifests and UI panels; `cloud-deployment.yml` automated; B modes implemented | Each feature completes UI → human decision locally; a push to `main` deploys to Azure |
| 17–19 Oct | F bonus tiers in order: B5, B6, B1, B2, B3, B4; all features run cloud CRUD smoke | The bonus validation script passes; the cloud smoke test covers all five features |
| **20 Oct** | **Feature freeze.** Capture final evidence and run all three review modes | Evidence folders complete; human release decision recorded |
| 21–22 Oct | Record the video, with each student's segment | Video of 10 minutes or less covers the showcase list in requirements |
| 23 Oct | Showcase and Q&A | — |
| 24–25 Oct | Build the report, verify it, and have one member submit `group-20.pdf` | Report covers requirements §Report contents |

## Evidence layout

```text
docs/release-2/evidence/
  security/      pre-commit-report.md, ruff-security.json, detect-secrets.json, pip-audit.json
  ci/            student-N.md (endpoint tests, run URL, SHA, JUnit summary)
  multi-agent/   student-N/ workflow_history.jsonl, coordination_audit.jsonl, screenshots
  reviews/       {multi-agent,testing,cloud}-review.md + -validation-log.jsonl
  local/         local-deployment-report.md, multi-terminal logs
  cloud/         cloud-deployment-report.md, workflow run logs, smoke output, release-decision.md
  bonus/         per-control config and validation output
```

## Risks

| Risk | Mitigation |
|---|---|
| VM cost or student credit runs out | Use a mid-size SKU (16 GiB RAM for 20 containers plus RAG embeddings), deallocate when idle, set a budget alert |
| The Multi-Agent Server is late and blocks every feature | Merge the contract and a deterministic provider first, so features build against a stub on day 3 |
| Cloud AI tier exposes a provider key | Store the key only in Key Vault; protect the AI routes with the edge token; enable AI only for the demo |
| CI endpoint tests are flaky against Compose | Use `up --wait`, fixed seed data and per-run project names (the pattern `student-5.yml` already uses) |
| A slice misses the freeze | Integration rule: an unintegrated feature scores zero. Escalate at the 16 Oct check-in, not on 20 Oct |

## Open decisions (owner)

- Which member's Azure subscription and credit to use, and who has deploy rights (Matthew).
- Public DNS label for the VM and the region (default `australiaeast`).
- Cloud data: the seeded baseline only, or a small published real release (Feature 1).
- Whether the tutor accepts non-cumulative bonus combinations.
