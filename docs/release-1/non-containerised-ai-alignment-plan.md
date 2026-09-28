# Release 1 alignment: non-containerised AI services

Status: implementation plan, 28 September 2026. Owner: Shared platform (Matthew Shelton).
Supersedes the Docker placement introduced by [the dual runtime plan](dual-ai-runtime-plan.md).

## What the rubric requires

The Assessment 2 brief and Canvas rubric say, in several places, that AI-mode, the MCP server,
the RAG server and the agentic loop **run locally, are not containerised, and must not be defined
as Docker Compose services**. The Release 0 `docker-compose.yml` keeps deploying the containerised
feature microservices, and must configure each backend/API to reach the local MCP and RAG servers
"following the existing connection approach used for the local AI-Mode". Criteria 1, 3, 4, 5 and 7
repeat the non-containerised requirement; criterion 7 is marked on it directly.

### Why the brief asks for this

The brief does not give a reason. The course material makes the intent clear:

- **Labs 7 and 8 use this topology.** The MCP and RAG servers run as local Python processes
  ("RAG server runs locally (NOT containerized) - similar to MCP server in Lab 07") and the
  containerised services reach them through `host.docker.internal`, exactly like the host Ollama
  model. Release 1 asks teams to scale that lab pattern up.
- **The AI tier is local developer infrastructure, not part of the deployable product.** MCP and
  RAG are disabled in CI and must stay disabled in the Release 2 cloud deployment. Keeping them out
  of Compose means the same Compose model deploys to CI and later to Azure without an AI tier.
- **Local models and data stay on the host.** Embedding weights, the vector index, model
  credentials and any local LLM live on the developer machine with direct CPU/GPU and filesystem
  access, instead of being baked into or mounted through images.
- **It is demonstrable and assessable.** Tutors ask for terminal validation of the MCP and RAG
  servers and terminal runs of the loop's validation modes. Separate host processes make the
  container boundary, the host-gateway connection and each server visible on their own.

## Current state

| Rubric item | Repository today | Gap |
|---|---|---|
| Compose defines no AI-mode, MCP, RAG or loop service | Base `docker-compose.yml` complies. `docker-compose.ai.yml` defines `shared-ai-mode`, `mcp-server` and `rag-server` services from `ai-services/Dockerfile`, and fresh setups **default to it** | Non-compliant: the repository defines them as Compose services, and a new clone demonstrates the wrong topology |
| AI services run locally | Host placement exists (`stack up --ai-runtime host`) but is opt-in | Must be the only placement |
| Backends configured for local MCP/RAG like AI-mode | All five backends receive `AI_MODE_*`, `MCP_SERVER_URL`, `RAG_SERVER_URL` on `host.docker.internal` | Compliant, but only a unit test checks it |
| MCP/RAG disabled in CI | All workflows set both flags to `false` | Compliant; `integration-ci.yml` also validates the AI overlay, which must go |
| Shared services accept only local endpoints | AI-mode accepts a `compose` environment with container origins; the MCP executor admits `http://mcp-server:5011/mcp` | Dead exception once Docker placement is retired |
| No AI container image | `ai-services/Dockerfile` (overlay image) and an unreferenced Release 0 `ai-services/ai-mode/Dockerfile` | Both imply a containerised AI tier |
| Documentation and report | README, AGENTS, CONTRIBUTING, ADR-044, host runtime guide, platform design, report Section 4/6.6 and two diagrams describe two placements or `--ai-runtime host` | Must describe one host topology |

## Decision

Host processes are the only AI runtime. Retire the Docker AI placement completely and record that
in ADR-046, which supersedes ADR-044 and restores ADR-043 as the sole topology. Do not keep an
optional overlay: any Compose definition of these services contradicts the rubric wording.

## Implementation

1. **Launcher (`scripts/dev.py`, `scripts/devtools/`).**
   - Delete `docker-compose.ai.yml`, `ai-services/Dockerfile`, `ai-services/ai-mode/Dockerfile`,
     `scripts/devtools/ai_runtime.py`, `scripts/devtools/container_entry.py` and their tests.
   - Remove the placement concept: `--ai-runtime`, `PROPERTYSCOPE_AI_RUNTIME`, the
     `ai-container` profile, `AI_PLACEMENTS` and `AI_CONTAINER_SERVICES`. Compose commands only ever
     name Compose services; AI lifecycle belongs to the `ai` command group.
   - `stack up` always starts the host AI services (`combined`, or `direct` with `--offline`).
     `ai start` no longer needs a prior `stack up`; `ai serve` no longer checks placement.
   - One-time retirement of the old placement, run before host services start: stop and remove this
     Compose project's legacy `shared-ai-mode`, `mcp-server` and `rag-server` containers (they hold the
     same SQLite files and host ports), and delete the generated `.propertyscope-runtime/docker-ai/`
     projection (it holds token copies) and `ai-runtime.json`. Durable history and the RAG index are
     already in `.propertyscope-runtime/host/` and are untouched.
   - `stack status`, `stack doctor` and `ai status` say plainly that AI runs as host processes and
     show each service's state and local URL. Doctor reports AI ports as `ai-mode`, `mcp`, `rag`.
2. **AI-mode.** Remove the `compose` environment and fixed container origins from settings and the
   MCP executor; shared MCP/RAG URLs must be loopback. Update tests.
3. **Enforcement (`scripts/validate_architecture.py`).** Fail the quality gate when any Compose file
   (`docker-compose*.yml`, `compose*.yml`, `deployment/*.compose.yml`) defines an AI service by name,
   build context, image or command, when a Dockerfile exists under `ai-services/`, or when a backend
   that calls AI-mode lacks `MCP_SERVER_URL`/`RAG_SERVER_URL` on `host.docker.internal` with the
   host-gateway mapping. Add fixture tests for each rule.
4. **CI.** `integration-ci.yml` validates only the base, generated and development Compose files.
   `student-5.yml` drops `PROPERTYSCOPE_AI_RUNTIME` and the deleted test module (a mechanical
   reference fix, noted in the PR for the owner). Update the workflow consistency test.
5. **Documentation.** New ADR-046; ADR-044 and the dual runtime plan marked superseded. Rewrite the
   runtime guide (`docs/release-1/host-runtime.md`) for one topology, including the rationale above
   and a terminal validation checklist. Update README, AGENTS.md, CONTRIBUTING.md, the
   `live-app-browser` skill, `ai-services/` and `scripts/` READMEs, `docs/README.md`,
   `docs/release-1/README.md` and `shared-platform-design.md`.
6. **Release 1 report.** Section 4 explains the containerisation boundary and why; Section 6.6 and
   Appendix D use `stack up`; Section 8 keeps the host-execution limitation. Update the architecture
   and CI/deployment diagrams (Compose defines no AI service; backends carry the MCP/RAG URLs),
   re-render the figures and manifest, and rebuild the draft PDF.
7. **Verification.** Targeted tests while iterating, then `uv run python scripts/check.py`. Live
   startup is exercised only if it does not disturb a running developer stack; otherwise the
   hand-off says so.

## Out of scope

- Generation stays in AI-mode with the approved OpenAI profile; the RAG server retrieves and
  AI-mode generates the grounded answer. This plan changes where services run, not that design.
- Feature-owned code (other than the mechanical workflow reference) and feature evidence.
- Release 2 cloud hosting, which remains a separate decision.

## Commits

1. `docs(release-1): plan non-containerised AI alignment`
2. `refactor(dev): run AI services only as host processes`
3. `refactor(ai-mode): accept only loopback MCP and RAG endpoints`
4. `feat(architecture): reject containerised AI services`
5. `ci: drop the Docker AI overlay from workflow checks`
6. `docs: describe the single non-containerised AI topology`
7. `docs(report): update Release 1 architecture for host-only AI services`
