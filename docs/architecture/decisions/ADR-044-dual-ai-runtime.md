# ADR-044: Retain reversible Docker and host AI placement

- Status: Accepted for local development at the user's explicit request
- Date: 7 September 2026
- Owner: Shared platform (Matthew Shelton)
- Extends: [ADR-043](ADR-043-local-grounded-runtime.md)
- Plan: [Reversible AI runtime placement](../../release-1/dual-ai-runtime-plan.md)

## Context

The supplied Release 1 rubric requires AI-mode, MCP, RAG and the agent loop outside containers.
ADR-043 established that topology. The user subsequently requested all three services in Docker
for visibility and integrated lifecycle management, retaining the ability to return to host
processes. This authorises a development alternative, not an amendment to the assignment or a
cloud deployment design.

## Decision

Keep the base and CI Compose models free of AI services. Add an optional `docker-compose.ai.yml`
overlay and one locked, non-root image with separate AI-mode, MCP and RAG process entries.
AI-mode owns the loop in either placement. Fresh launcher setups default to Docker;
`stack up --ai-runtime docker|host` explicitly selects and persists placement. Placement is
separate from the `direct|mcp|rag|combined` capability mode. AI lifecycle and inspection commands
follow the selected placement.

Reuse `.propertyscope-runtime/host/ai-mode` and `host/rag` in both modes. Each container receives
only its owning state directory; previous owners stop before switching. There is one history
store and one RAG index/model cache, with no recurring copy or re-ingestion. Preserve the separate
initial migration of legacy Docker-volume history. Recreate backend/proxy routing when switching.

Host mode retains Docker gateway access to authenticated AI-mode and loopback MCP/RAG. Docker
mode uses exact internal service origins and publishes only loopback host ports. MCP retains
Host/Origin protection with its fixed service name explicitly admitted. AI-mode retains its proxy
token; MCP/RAG retain independent bearer tokens and the existing tool, approval, corpus and
grounding boundaries. Only AI-mode receives a provider credential, mounted as a runtime secret
in Docker. No secret enters an image or browser configuration.

Model preparation and ingestion stay explicit. The host preparation CLI writes the cache also
mounted into Docker RAG; ingestion and local validation use published loopback ports. Frontend
source changes need a refresh. AI Python workers require explicit restart to avoid interrupting
durable work; dependency and Dockerfile changes require rebuilds.

## Consequences and verification

Docker placement improves visibility but **does not satisfy the Release 1 non-containerisation
clause**. Select `stack up --ai-runtime host` for assessment demonstrations and capture evidence
there. CI continues to disable MCP/RAG and must not acquire models or contact providers. Cloud
hosting remains separate future work.

The launcher must preserve exclusive database ownership and selection across every lifecycle
operation. Deterministic tests cover network exceptions, authentication, CI guards, selection and
transitions. Live verification must exercise Docker startup, semantic retrieval, grounded chat,
host switching and return to Docker with unchanged history and corpus identity. These are
verification requirements, not claims that a test has already run.

The [local runtime guide](../../release-1/host-runtime.md) owns setup and switching commands.
