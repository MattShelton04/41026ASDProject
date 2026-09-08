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
all five feature slices are manifest-enabled. Their owners retain responsibility for datasets,
feature behavior and remaining release evidence.

MCP and RAG are implemented local Release 1 services; multi-agent remains a Release 2 placeholder.
Fresh developer setups run AI services in Docker. Select `stack up --ai-runtime host` for the
Release 1 assessment topology, which requires AI services outside containers. Both placements use
the same exclusive AI history and RAG state directories. MCP/RAG remain disabled in CI/CD and cloud.
See the [runtime guide](../docs/release-1/host-runtime.md) for lifecycle and configuration.
