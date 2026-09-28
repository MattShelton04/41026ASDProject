# ADR-046: Run AI-mode, MCP and RAG only as non-containerised host processes

- Status: Accepted
- Date: 28 September 2026
- Owner: Shared platform (Matthew Shelton)
- Supersedes: [ADR-044](ADR-044-dual-ai-runtime.md)
- Reaffirms: [ADR-043](ADR-043-local-grounded-runtime.md)
- Plan: [Non-containerised AI alignment](../../release-1/non-containerised-ai-alignment-plan.md)

## Context

The Release 1 rubric requires AI-mode, the MCP server, the RAG server and the agent loop to run
outside containers. It also requires student backends in `docker-compose.yml` to reach them
through `host.docker.internal`, and it requires MCP and RAG to be disabled in CI. ADR-043 set out
that topology. ADR-044 then added an optional Docker placement and made it the default for fresh
setups. ADR-044 recorded that the Docker placement does not meet the rubric. In practice the
repository shipped a non-compliant default, and assessment evidence depended on every operator
remembering `--ai-runtime host`.

The rubric's constraint follows the course labs, which run these servers locally and reach them
from containers through the Docker host gateway, in the same way as a host Ollama instance. The
AI tier is local developer infrastructure. It is off in CI and in the Release 2 cloud deployment.
Model weights, the embedding cache and provider credentials stay on the developer's machine
instead of in images. Separate host processes can be started, stopped, logged and probed directly
from a terminal, which is how the rubric asks for MCP and RAG to be demonstrated.

## Decision

Only one topology exists: the one in ADR-043.

- `scripts/dev.py stack up` always starts AI-mode, MCP and RAG as host processes before the
  Compose services. `ai start|stop|status|logs|serve|validate|probe` act only on those processes.
- No Compose file defines an AI service, and nothing under `ai-services/` has a Dockerfile.
  `docker-compose.ai.yml`, the AI image, the container entrypoint and the placement state were
  removed.
- `scripts/validate_architecture.py` enforces this in the quality gate. It rejects AI Dockerfiles
  and any Compose service that names, builds, runs or uses an image of an AI component. It also
  requires every backend in `docker-compose.yml` that calls AI-mode to carry `MCP_SERVER_URL` and
  `RAG_SERVER_URL` through `host.docker.internal`, with the host-gateway mapping.
- AI-mode accepts only loopback MCP and RAG endpoints, and only in the `local` environment. The
  Compose service-name exception is removed, so a containerised MCP or RAG cannot be wired in.
- `--ai-runtime` stays as a hidden `stack up` option so older instructions fail clearly. The
  value `docker` is rejected before any side effect, and `host` is accepted with a note that the
  option is no longer needed.
- On first start after upgrade, the launcher stops and removes any old AI containers that belong
  to the same Compose project. It deletes their generated projection files but keeps run history,
  the RAG index and the model cache, because those already live in the host store.

## Consequences

- Assessment evidence no longer depends on choosing a flag. The quality gate catches any
  regression.
- Developers lose the optional Docker placement. Host process state stays visible through
  `stack status`, `ai status`, `ai logs` and `ai probe`.
- CI behaviour does not change. MCP and RAG stay disabled, and no job downloads models or
  contacts a provider.
- Release 2 cloud hosting of AI-mode is still future work. It needs its own decision and must
  not reintroduce MCP or RAG into CI or the cloud topology without one.

The [local runtime guide](../../release-1/host-runtime.md) owns setup and validation commands.
