# Shared AI services

| Directory | Intended release | Purpose |
|---|---|---|
| `agent-core/` | Release 0 | Framework-independent orchestration policies and ports |
| `ai-mode/` | Release 0 | HTTP orchestration, persistence, and Ollama adapter |
| `mcp-server/` | Release 1 | Model Context Protocol server |
| `rag-server/` | Release 1 | Retrieval-Augmented Generation and grounding |
| `multi-agent-server/` | Release 2 | Planner, worker, reviewer, and human review orchestration |

`agent-core` now contains the deterministic state machine, bounded runner, tool policy,
ports, and human-review rules. `ai-mode` supplies the first SQLite, prompt-registry,
native Ollama, background-queue, and versioned HTTP adapters. See each package README
for implemented behavior and the remaining Release 0 vertical-integration work.

MCP, RAG, and multi-agent directories remain placeholders. Those services are required
locally in their applicable releases and disabled in the cloud.
