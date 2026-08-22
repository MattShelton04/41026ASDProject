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
| `multi-agent-server/` | Release 2 | Planner, worker, reviewer, and human review orchestration |

`agent-core` now contains the deterministic state machine, bounded runner, tool policy,
ports, and human-review rules. `ai-mode` supplies the SQLite, prompt-registry,
OpenAI Responses, background-queue, and versioned HTTP adapters. See each package README
for implemented behavior and operating instructions. The Release 0 vertical path is integrated;
remaining work is feature onboarding and release evidence, not missing AI-mode plumbing.

MCP, RAG, and multi-agent directories remain placeholders. Those services are required
locally in their applicable releases and disabled in the cloud.
