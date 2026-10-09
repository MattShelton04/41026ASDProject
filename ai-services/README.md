# Shared AI services

The assignment calls the user-facing capability **AI mode**. In this repository the
names describe distinct runtime responsibilities:

| Name | Kind | Responsibility |
|---|---|---|
| `agent-core` | Python library | Domain-neutral run state machine, policies, and ports |
| `ai-mode` | HTTP service/container | Shared agent orchestrator and owner of workflow state |
| OpenAI | Remote API dependency | Model inference behind AI-mode's provider boundary |

Keeping `ai-mode` preserves traceability to the assignment language; “shared agent
orchestrator” is its technical role. It is not the model server and it does not own
feature data or business rules.

| Directory | Intended release | Purpose |
|---|---|---|
| `agent-core/` | Release 0 | Framework-independent orchestration policies and ports |
| `ai-mode/` | Release 0 | HTTP orchestration, persistence, and OpenAI adapter |
| `mcp-server/` | Release 1 | Model Context Protocol server |
| `rag-server/` | Release 1 | Retrieval-Augmented Generation and grounding |
| `multi-agent-server/` | Release 2 | Planner, Worker, Reviewer and human-decision workflows over feature tools |

`agent-core` now contains the deterministic state machine, bounded runner, tool policy,
ports, and human-review rules. `ai-mode` supplies the SQLite, prompt-registry,
OpenAI Responses, background-queue, and versioned HTTP adapters. See each package README
for implemented behavior and operating instructions. The Release 0 vertical path is integrated;
all five feature slices are manifest-enabled. Their owners retain responsibility for datasets,
feature behavior and remaining release evidence.

MCP and RAG are implemented local Release 1 services. The Release 2
[Multi-Agent Server](multi-agent-server/README.md) runs feature-owned workflow templates
(`student-N/config/multi-agent/workflow.yaml`): a Planner, a Worker restricted to the template's
read-only tools (through MCP), a Reviewer, and one human decision with a single correction round
([ADR-047](../docs/architecture/decisions/ADR-047-multi-agent-server.md)). It reuses agent-core's
provider port and AI-mode's model registry, and has a deterministic provider for offline runs.
Feature backends call its token-protected HTTP API (`MULTI_AGENT_BASE_URL`, port 5013) and test
against `shared_testkit.FakeMultiAgentServer`; they never import it.

AI-mode, MCP, RAG and the Multi-Agent Server run only as non-containerised host processes, as the
Release 1 rubric requires ([ADR-046](../docs/architecture/decisions/ADR-046-non-containerised-ai-tier.md)).
No package here has a Dockerfile and no Compose file defines an AI service; the architecture gate
enforces both. `scripts/dev.py stack up` starts them before the feature containers, which reach
AI-mode and the Multi-Agent Server through `host.docker.internal`. MCP, RAG and the Multi-Agent
Server remain disabled in CI/CD.
See the [runtime guide](../docs/release-1/host-runtime.md) for lifecycle and configuration.
