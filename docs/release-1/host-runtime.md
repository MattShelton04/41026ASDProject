# Local AI runtime: non-containerised host processes

AI-mode, the MCP server and the RAG server run as managed Python processes on the developer's
machine, outside Docker. The agent loop is AI-mode's worker and library, not a fourth service.
Compose defines only the shared edge and the enabled student frontends, backends and databases.
Those containers reach the AI tier through `host.docker.internal`. See
[ADR-043](../architecture/decisions/ADR-043-local-grounded-runtime.md) for the topology and
[ADR-046](../architecture/decisions/ADR-046-non-containerised-ai-tier.md) for why the earlier
optional Docker placement was removed.

## Why the AI tier is not containerised

The Release 1 rubric requires AI-mode, MCP, RAG and the agent loop to run outside containers,
with student backends in `docker-compose.yml` reaching them via `host.docker.internal`. MCP and
RAG must also stay disabled in CI. The reasons:

- **It matches the course labs.** Labs 7 and 8 run the MCP and RAG servers locally and reach them
  from containers through the Docker host gateway, in the same way as a host Ollama instance.
- **It is local developer infrastructure.** MCP and RAG are off in CI and absent from the
  Release 2 cloud deployment. Containerising them would add images and a topology that no
  pipeline or environment uses.
- **Models and secrets stay on the host.** The embedding model cache, RAG index and provider
  credential stay in ignored local directories. They are never baked into an image or mounted
  into several containers.
- **It is easy to demonstrate.** Each server is a separate process that can be started, stopped,
  logged and probed from a terminal, which is how the rubric asks for MCP and RAG to be shown.

`scripts/validate_architecture.py` enforces this in the quality gate. It rejects Dockerfiles under
`ai-services/` and any Compose service that names, builds, runs or uses an image of an AI
component. It also requires every AI-calling backend in `docker-compose.yml` to carry
`AI_MODE_BASE_URL`, `MCP_SERVER_URL` and `RAG_SERVER_URL` through `host.docker.internal`, with
the `host-gateway` mapping.

## Start and inspect

Install the locked workspace with `uv sync --locked --all-packages --all-groups`. Create the
ignored root `.env` from `.env.example` and configure the approved model provider. Docker Desktop
must be running for the feature containers.

```text
uv run scripts/dev.py stack up
uv run scripts/dev.py stack status
uv run scripts/dev.py ai status
uv run scripts/dev.py ai logs
uv run scripts/dev.py ai logs mcp rag
```

`stack up` starts AI-mode, MCP and RAG on the host first, waits for them to become ready, and then
starts the feature containers. `stack status` and `ai status` list each host process with its
local URL. The `--ai-runtime` option has been retired. `--ai-runtime docker` is rejected, and
`--ai-runtime host` is accepted with a note that it is no longer needed.

The first start after upgrading from the old Docker placement stops and removes any
`shared-ai-mode`, `mcp-server` or `rag-server` containers left in the same Compose project. It
also deletes their generated `.propertyscope-runtime/docker-ai/` projection. Run history, the RAG
index and the model cache already live in the host store, so nothing is copied or re-ingested.

`stack up --offline` starts AI-mode in direct HTTP mode, plus the feature containers, without a
real provider credential. MCP and RAG stay stopped in that mode. To choose one demonstration path
while the feature containers keep running:

```text
uv run scripts/dev.py ai start --mode mcp
uv run scripts/dev.py ai start --mode rag
uv run scripts/dev.py ai start --mode combined
uv run scripts/dev.py ai start --mode direct --offline
```

The mode changes how AI-mode dispatches tools and retrieves context, and starts only the servers
that mode needs. `--offline` turns off provider readiness requirements. It does not replace real
semantic retrieval with synthetic embeddings. Isolated integrations such as Student 5 CI run
`ai start --mode direct --offline` on a fresh checkout before starting their own containers. MCP
and RAG stay disabled in CI.

Frontend source edits need a browser refresh. Feature HTTP services reload by themselves. After AI
Python source edits, run `ai stop` and then `ai start --mode combined`, because workers are never
restarted implicitly while they may hold durable work. Run `stack up` after token or environment
changes so container configuration stays in step. `ai serve ai-mode|mcp|rag` runs one process in
the foreground using environment variables you have already set. Managed startup is preferable
because it generates catalogue projections, state paths and service tokens consistently. Liveness
and readiness are separate: without a prepared embedding model, RAG is alive but unavailable for
semantic retrieval. Startup never downloads model assets or feature datasets.

## Prepare and ingest context

Model preparation and source ingestion are explicit operations:

```text
uv run rag-server prepare-model
uv run scripts/dev.py ai stop rag
uv run scripts/dev.py ai start --mode combined
```

The default cache is `.propertyscope-runtime/host/rag/models`. Restarting RAG loads the prepared
model; startup itself never downloads weights. `RAG_DATABASE_PATH`, `RAG_MODEL_CACHE_PATH`,
`AI_MODE_MODEL_REGISTRY_PATH` and `AI_MODE_OPERATIONS_ASSETS_PATH` may point elsewhere on the
host.

If the launcher generated the default RAG token, load it into the ingestion shell without
printing it. In PowerShell:

```powershell
$env:RAG_SERVICE_TOKEN = (Get-Content -Raw .propertyscope-runtime/host/rag.token).Trim()
uv run rag-server ingest student-1/config/rag/corpus.json
```

In a POSIX shell:

```sh
export RAG_SERVICE_TOKEN="$(cat .propertyscope-runtime/host/rag.token)"
uv run rag-server ingest student-1/config/rag/corpus.json
```

An explicitly configured `RAG_SERVICE_TOKEN` takes precedence over the generated file; reuse that
same value instead. The [corpus recipe](../../student-1/config/rag/README.md) documents licence,
scope and full-replacement semantics. The [evaluation](retrieval-evaluation.md) measures source
recall separately from the quality of model-generated answers. Before claiming idempotent replay,
repeat an ingestion and check that the version and ingestion time are unchanged.

## Networking and credentials

| Service | Host listener | Reached from containers as |
|---|---|---|
| AI-mode | `0.0.0.0:5005` (`AI_MODE_PORT`) | `http://host.docker.internal:5005`, with `X-PropertyScope-AI-Token` |
| MCP | `127.0.0.1:5011/mcp` (`MCP_PORT`) | Not reached from containers; AI-mode calls it on loopback |
| RAG | `127.0.0.1:5012` (`RAG_PORT`) | Not reached from containers; AI-mode calls it on loopback |

Backends still carry `MCP_SERVER_URL` and `RAG_SERVER_URL` (via `host.docker.internal`) so each
feature's host-AI wiring is explicit and checked. The servers themselves bind only to loopback and
require bearer tokens. AI-mode accepts MCP and RAG URLs only in the `local` environment and only
when they are loopback HTTP endpoints; a Compose service name is rejected. MCP keeps SDK Host and
Origin validation limited to loopback. The launcher builds host catalogue copies from the enabled
feature manifests and points their fixed service origins at the published feature ports. Tool
names, schemas, approval classes and owning backend paths are unchanged.

Compose sets `host.docker.internal:host-gateway` for the shared edge and feature backends,
including on Linux Docker Engine. The edge resolves its configured host upstream when nginx
starts. AI-mode requires `X-PropertyScope-AI-Token` on every route except exact `/health/live`.
The launcher generates `.propertyscope-runtime/host/ai-mode.token`, or accepts an explicit
`AI_MODE_SERVICE_TOKEN` of 32–128 URL-safe letters, digits, underscores or hyphens. All five
backend HTTP clients and the shared nginx proxy receive it internally. It is never sent as browser
configuration, HTML or a model argument. Service authentication is not end-user authentication:
the browser application stays in the trusted local demonstration profile, and managed startup
rejects non-local deployment environments.

Provider credentials stay in ignored local files and reach only host AI-mode. MCP and RAG never
receive provider credentials. The launcher creates independent MCP and RAG bearer tokens under
the ignored host directory unless `MCP_SERVICE_TOKEN` and `RAG_SERVICE_TOKEN` are set explicitly.
Never publish token files or runtime logs as assessment evidence without checking and redacting
them.

## Durable state and shutdown

The ignored `.propertyscope-runtime/host/` directory holds all AI state. `ai-mode/` holds the run
database and `rag/` holds the index and model cache. Tokens, catalogue projections and process
records live beside them. On first setup, legacy-history migration can copy the old `ps-dev`
AI-state volume read-only through a helper container that is never started. SQLite's backup API
folds in the copied WAL and verifies the result before installing the host database. Existing
host state is never overwritten and the source volume is kept.

```text
uv run scripts/dev.py ai stop rag
uv run scripts/dev.py ai stop
uv run scripts/dev.py stack down
```

Stopping preserves AI databases, model assets and Docker volumes. Before signalling a process,
the launcher checks its PID creation time, command line and recorded checkout identity, and it
accounts for the Windows virtualenv child interpreter. It never ends an unmanaged process just
because that process holds an expected port. After a failed launch, use `ai logs`. `stack reset`
keeps host state and deletes only the selected stack's Docker data.

## Terminal validation checklist

With the stack running and the approved corpus ingested, these commands produce the Release 1
MCP and RAG evidence from a terminal:

```text
uv run scripts/dev.py ai status
uv run scripts/dev.py ai probe --output .propertyscope-runtime/release-1/probe.json
uv run scripts/dev.py ai validate mcp --output .propertyscope-runtime/release-1/validation-mcp.json
uv run scripts/dev.py ai validate rag --output .propertyscope-runtime/release-1/validation-rag.json
docker compose ps
```

1. `ai status` shows three host processes with their loopback URLs.
2. `ai probe` calls each server directly. It checks that:
   - AI-mode, MCP and RAG each reject an unauthenticated caller;
   - MCP `tools/list` exposes every enabled feature's registered tools;
   - each registered corpus has an ingested version;
   - a passage from the corpus retrieves with citations above the grounding threshold;
   - an off-topic question returns `no_match` (insufficient context).
3. `ai validate mcp` and `ai validate rag` run the production agent loop through Plan, Act,
   Observe and Adapt over each protocol, as described below.
4. `docker compose ps` lists only the edge and feature services; no AI container exists.

`ai probe` never prints tokens, never restarts services and never ingests documents. It exits
nonzero if any check fails, and CI refuses to run it.

## CI boundary and validation

All workflows set `AI_MODE_MCP_ENABLED=false` and `AI_MODE_RAG_ENABLED=false` explicitly. Student
workflows validate shared retrieval contracts, signed MCP invocation metadata, the embedding
lifecycle with test doubles, and static runtime exclusions. They never launch MCP or RAG, download
an embedding model, or contact a model provider. Student 5 keeps its persisted-run degradation
smoke, which uses direct host AI-mode with an unreachable local provider endpoint; both advanced
capabilities stay disabled.

Targeted runtime checks:

```text
uv run pytest scripts/tests/test_host_runtime.py scripts/tests/test_host_ai_lifecycle.py scripts/tests/test_release1_probe.py scripts/tests/test_dev.py scripts/tests/test_validate_architecture.py --no-cov -q
uv run python scripts/check.py architecture
```

These deterministic tests cover:

- rejection of processes whose identity does not match;
- idempotent history migration and wrong-volume-owner rejection;
- host catalogue projection;
- start and stop ordering;
- retirement of old AI containers;
- the probe's pass and fail paths;
- the architecture rule that keeps AI out of Compose.

Real protocol, semantic retrieval, integrated browser and provider evidence must be recorded
separately. Passing unit tests does not establish those results.

## Named agent-loop validation modes

The `ai validate mcp` and `ai validate rag` commands from the checklist run the production
`AgentRunner`, prompt registry and contracts, with a separate temporary SQLite run store, through
Plan, Act, Observe and Adapt.

- **MCP** uses the official protocol adapter. It reads Feature 1's registered
  `platform.capabilities.v1` tool through the running MCP server and Feature 1 backend.
- **RAG** uses the authenticated retrieval adapter and the running semantic index. It copies a
  retrieved passage into a cited finding and validates the current corpus version before
  completing.

Neither command restarts services, prepares model assets, ingests documents or changes the managed
AI-mode run history.

Model decisions are explicitly deterministic (`extractive-validation.v1`). This separates protocol
and orchestration validation from provider variability. It is not evidence of a real model answer
or of semantic relevance. JSON outputs keep the mode, pass/fail, all four phases, correlation IDs,
structured tool results, source citations and the final confidence category. They exclude provider
credentials, rendered prompts and private reasoning traces.

A command exits nonzero when a service is unavailable, a tool fails, or the four phases do not all
complete. RAG separates an answered query from a valid no-match or empty result through
`grounding_status` and `confidence`. Check those fields rather than treating a successful transport
call as proof of relevant context. `--query` supplies an insufficient-context probe. `--corpus`
selects an already registered corpus without granting new access. CI refuses the live command and
runs `scripts/tests/test_release1_validation.py` with injected tool doubles instead.

## Release 2 review modes

`ai review multi-agent`, `ai review testing` and `ai review cloud` extend the same loop to review
Release 2 evidence. They create persisted AI-mode runs (visible in Activity history) with the
`review-*.v1` prompt sets, or run the production loop in-process with `--deterministic`. See
[Release 2 review modes](../release-2/review-modes.md).
