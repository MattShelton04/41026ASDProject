# Release 2 showcase checklist

This is a one-page tick list for the video (at most 10 minutes) and the 23 October showcase. Each
item maps to a rubric criterion (C1–C10, B1–B6). The [showcase runbook](showcase-runbook.md) has
the commands, timings and fallbacks.

Rules that apply to every segment:

- **Every student speaks** and defends their own work (C10).
- **A feature that is not integrated scores zero** on the working-software criteria.
- **Bonus marks count only if the bonus is demonstrated**, live or on video, through the app.

## Overview: project, repository and Shared (Matthew)

| ✓ | Show | Criterion |
|---|---|---|
| ☐ | Team, the five features, and what Release 2 adds to Release 1 (one architecture figure) | C9, C10 |
| ☐ | Repository layout: `ai-services/multi-agent-server`, `.pre-commit-config.yaml`, `student-N.yml`, `cloud-deployment.yml`, `deployment/azure`, `docs/release-2/evidence` | C9 |
| ☐ | **Local stack:** Compose containers plus **four host terminals** (AI-mode, MCP, RAG, Multi-Agent), all outside Docker | C1 |
| ☐ | **Terminal Multi-Agent run:** Planner → Worker → Reviewer → human decision, then the exported history and audit log | C2 |
| ☐ | **Pre-commit scans firing during `git commit`:** Ruff `S`, detect-secrets, pip-audit | C3 |
| ☐ | **Post-commit CI:** a green `student-1.yml` run with its two endpoint tests and JUnit summary | C4 |
| ☐ | **Deployment scripts and IaC:** Bicep templates and `deploy.sh` (provision, push, deploy, smoke) | C5 |
| ☐ | **`cloud-deployment.yml` run:** `verify-ci` → `build-validate` → `deploy` → smoke, all green | C6 |
| ☐ | **Azure:** the public URL, the home page, all five features reachable, AI shown **disabled by default** | C7 |
| ☐ | **Three review modes:** `ai review multi-agent`, `testing` and `cloud`, each with its report and validation log, then `ai review decide` (the human release decision) | C8 |
| ☐ | Release 1 loop modes still work: `ai validate mcp` and `ai validate rag` (a brief mention) | C8 |
| ☐ | **Bonus AI on Azure, through the UI:** a chat turn (B1), an MCP tool call (B2), a RAG answer with citations (B3), a Planner → Worker → Reviewer run (B4) | B1–B4 |
| ☐ | **Bonus security:** HTTP→HTTPS redirect, 401 without login, 429 rate limit, closed ports (B5); Key Vault, managed identity, encrypted disks (B6) | B5, B6 |
| ☐ | Close: the repository URL, the report and the release decision | C9 |

## Each feature slice (every student, about 1 minute)

Copy this list for your own feature. Feature 1 is the reference example.

| ✓ | Show | Criterion |
|---|---|---|
| ☐ | Your feature opened from the shared home page, **locally** | C1 |
| ☐ | **CRUD** against your own database: create, edit, delete, then show the result in the list | C1 |
| ☐ | Release 1 AI still integrated: an AI-mode chat that uses an MCP tool and a RAG answer with citations | C1 |
| ☐ | **Multi-Agent through your UI:** start → Planner, Worker and Reviewer lanes → a **human decision** (approve, correct, partial or reject) → the response back in your UI | C2 |
| ☐ | Your green `student-N.yml` run: name your **two endpoint functions** and what each test checks | C4 |
| ☐ | Your pre-commit findings fixed or justified (`# noqa` with a reason) | C3 |
| ☐ | **The same feature on Azure:** the page loads and one CRUD operation works, with AI disabled | C7 |
| ☐ | One sentence on your design flow: UI → API → DB, plus UI → API → Multi-Agent → Human Review → UI | C9, C10 |
| ☐ | Be ready for Q&A: why you chose your workflow template and tools, and what the reviewer checks | C10 |

### Feature 1 specifics (Matthew)

- **Multi-Agent:** a Readiness review of a `candidate` release on Published data. The workflow
  only recommends; publishing stays a separate operator action.
- **Endpoint tests:** `GET /properties/search` and source-definition CRUD (`/sources`).
- **CRUD:** create, edit and delete a source definition.
- **Search caveat:** search with `1 George Street` locally and on Azure. A search that adds the
  suburb can return `503` on Azure.

## Before recording

- ☐ Freeze-commit evidence is refreshed (`refresh_release2_evidence.py --final`) and the release
  decision is recorded again.
- ☐ The Azure VM is started, and the smoke test is green on the deployed commit.
- ☐ If the AI bonus is claimed: the *Cloud AI Tier* workflow is on before recording and **off**
  afterwards.
- ☐ No secrets on screen: `.env`, Key Vault, tokens in shell history.
- ☐ Fallback clips are recorded for the Multi-Agent UI run, the terminal run and Azure.
- ☐ The video is at most 10:00 and published. Its URL is in the report cover, the metadata and
  Section 14, together with who took part.
