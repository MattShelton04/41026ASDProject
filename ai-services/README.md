# Shared AI services

| Directory | Intended release | Purpose |
|---|---|---|
| `agent-core/` | Release 0 | Framework-independent orchestration policies and ports |
| `ai-mode/` | Release 0 | HTTP orchestration, persistence, and Ollama adapter |
| `mcp-server/` | Release 1 | Model Context Protocol server |
| `rag-server/` | Release 1 | Retrieval-Augmented Generation and grounding |
| `multi-agent-server/` | Release 2 | Planner, worker, reviewer, and human review orchestration |

`agent-core` and `ai-mode` are Python workspace projects. AI-mode currently exposes
only deterministic health endpoints; its orchestration API, persistence, and model
adapter are follow-up work. MCP, RAG, and multi-agent directories remain placeholders.
Those services are required locally in their applicable releases and disabled in the
cloud.
