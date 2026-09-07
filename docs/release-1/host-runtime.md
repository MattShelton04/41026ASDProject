# Local AI runtime: Docker and host placement

The launcher supports the same AI-mode, MCP and RAG services in two local placements.
Fresh developer setups default to Docker so all three appear alongside the feature services
in Docker Desktop. Host placement runs them as managed Python processes and satisfies the
supplied Release 1 non-containerisation requirement. The agent loop is AI-mode's worker/library,
not a fourth service. Docker placement is a user-authorised development convenience; it does
not satisfy that rubric clause. See [ADR-044](../architecture/decisions/ADR-044-dual-ai-runtime.md)
and the [implementation plan](dual-ai-runtime-plan.md).

The base, development and generated Compose files retain the host/CI topology. Docker placement
adds the optional `docker-compose.ai.yml`; use the launcher so routing, credentials and exclusive
state ownership are configured together.

## Start and inspect

Install the locked workspace with `uv sync --locked --all-packages --all-groups`. Create
the ignored root `.env` from `.env.example` and configure the approved model provider.
Docker Desktop must be running for the integrated feature application.

```text
uv run scripts/dev.py stack up
uv run scripts/dev.py stack status
uv run scripts/dev.py ai status
uv run scripts/dev.py ai logs
uv run scripts/dev.py ai logs mcp rag
```

`stack up` starts the selected AI placement and containerised features. Selection defaults to
Docker when no placement is recorded, and is persisted in `.propertyscope-runtime/ai-runtime.json`.
Switch with:

```text
uv run scripts/dev.py stack up --ai-runtime host
uv run scripts/dev.py stack up --ai-runtime docker
```

The first command selects the assessment topology; the second returns to Docker. Switching
stops the previous AI owners before starting their replacements and recreates backend/proxy
routing. AI history and RAG state remain in their existing owner directories. `ai start`,
`ai stop`, `ai status` and `ai logs` follow the selected placement. `PROPERTYSCOPE_AI_RUNTIME`
can also explicitly select `docker` or `host`; avoid a stale shell override when switching.

Frontend source edits need a browser refresh. Feature HTTP services reload; AI workers in either
placement require an explicit stop/start after Python source edits. Host status checks process
ownership; Docker status reports the selected containers. Service liveness and
readiness are separate: an unprepared embedding model leaves RAG alive but unavailable
for semantic retrieval. Startup never downloads model assets or acquires feature datasets.

`stack up --offline` starts the direct HTTP AI-mode configuration and feature containers
without a real provider credential. MCP and RAG stay stopped in that mode. To select an
individual demonstration path while keeping the feature containers running:

```text
uv run scripts/dev.py ai start --mode mcp
uv run scripts/dev.py ai start --mode rag
uv run scripts/dev.py ai start --mode combined
uv run scripts/dev.py ai start --mode direct --offline
```

The mode changes AI-mode's tool dispatch/retrieval configuration and starts only the
selected advanced services. `--offline` disables provider readiness requirements; it does
not substitute synthetic embedding quality for real semantic retrieval.

For AI source changes, use `ai stop` then `ai start --mode combined`; after dependencies or
Dockerfile changes use `stack rebuild`. For environment/token changes use `stack up` to keep
backend and proxy configuration aligned. The host-only `ai serve ai-mode`, `ai serve mcp` and
`ai serve rag` commands run a single foreground process using
already configured environment variables. Normal managed startup is preferable because
it generates local catalogue projections, state paths and service tokens consistently.

## Prepare and ingest context

Model preparation and source ingestion are explicit operations:

```text
uv run rag-server prepare-model
uv run scripts/dev.py ai stop
uv run scripts/dev.py ai start --mode combined
```

Preparation runs through the locked host CLI in both placements. The default cache at
`.propertyscope-runtime/host/rag/models` is also mounted into the RAG container. Restarting
the selected RAG service loads the prepared model; startup itself never downloads weights.
Ingestion continues to call the authenticated host-loopback RAG port in either placement.

The managed Docker profile uses the canonical index/cache directories and bundled model registry
and operations assets. Custom `RAG_DATABASE_PATH`, `RAG_MODEL_CACHE_PATH`,
`AI_MODE_MODEL_REGISTRY_PATH` or `AI_MODE_OPERATIONS_ASSETS_PATH` overrides require host placement;
the launcher rejects unsupported overrides before stopping its active host services.

If the launcher generated the default RAG token, load it into the ingestion shell without
printing it. For PowerShell:

```powershell
$env:RAG_SERVICE_TOKEN = (Get-Content -Raw .propertyscope-runtime/host/rag.token).Trim()
uv run rag-server ingest student-1/config/rag/corpus.json
```

For a POSIX shell:

```sh
export RAG_SERVICE_TOKEN="$(cat .propertyscope-runtime/host/rag.token)"
uv run rag-server ingest student-1/config/rag/corpus.json
```

An explicitly configured `RAG_SERVICE_TOKEN` takes precedence over that generated file;
reuse the same configured value instead. The [corpus recipe](../../student-1/config/rag/README.md)
documents licence/scope and full-replacement semantics. The [evaluation](retrieval-evaluation.md)
records source recall separately from model-generated answer quality. Repeat ingestion to
verify identical version and ingestion time before claiming idempotent replay.

## Networking and credentials

| Service | Docker placement | Host placement |
|---|---|---|
| AI-mode | `shared-ai-mode:5005`, published on host `127.0.0.1:5005` | Host bind `0.0.0.0:5005`; backends/edge use `host.docker.internal` |
| MCP | `mcp-server:5011/mcp`, published on host `127.0.0.1:5011/mcp` | `127.0.0.1:5011/mcp` |
| RAG | `rag-server:5012`, published on host `127.0.0.1:5012` | `127.0.0.1:5012` |

`AI_MODE_PORT`, `MCP_PORT` and `RAG_PORT` configure host listeners or Docker's published ports;
container-internal ports remain 5005/5011/5012. Feature HTTP ports
come from the existing manifest variables. The launcher derives host catalogue copies
from enabled feature manifests and maps their fixed service origins to the published
feature frontend ports. Tool names, schemas, approval classification and owning backend
paths are preserved. Docker catalogue projections retain the original fixed backend service
origins. Original feature catalogues continue to describe the domain boundary.

Compose sets `host.docker.internal:host-gateway` for the shared edge and feature backends,
including Linux Docker Engine. The edge resolves its configured host upstream at nginx
startup. In host mode MCP/RAG retain loopback binding. In Docker mode all three bind inside
their containers, with MCP Host-header validation allowing only the fixed service name and
loopback. AI-mode permits the fixed MCP/RAG service URLs only in its local Compose environment.
Managed AI-mode requires `X-PropertyScope-AI-Token` on every route except exact `/health/live`.
The launcher generates `.propertyscope-runtime/host/ai-mode.token` or accepts an explicit
`AI_MODE_SERVICE_TOKEN` containing 32–128 URL-safe letters, digits, underscores or hyphens.
All five backend HTTP clients and the shared nginx proxy receive the same service token
internally; it is never delivered as browser configuration, HTML or a model argument.
This protects the managed AI listener, including run history and readiness, in both placements.

Changing the token requires `stack up` to recreate container configuration as well as
the AI process. Ordinary stop/start reuses the persisted token. The standalone Flask
application factory retains its existing loopback development behavior; use managed
startup for the integrated authenticated listener. The managed `ai serve ai-mode` command
requires the token explicitly. Service authentication is not end-user authentication:
the browser application remains the trusted local demonstration profile. Managed startup
rejects non-local deployment environments; production identity is a separate future boundary.

Provider credentials remain in ignored local files. Docker AI-mode alone receives the configured
provider key as a runtime-mounted secret file; host AI-mode loads its configured environment.
Neither MCP nor RAG receives provider credentials. Keys are never baked into the image or
included in process commands or printed configuration. The launcher creates
independent MCP/RAG bearer tokens under the ignored host directory unless explicitly
configured with `MCP_SERVICE_TOKEN` and `RAG_SERVICE_TOKEN`. Source ingestion clients must
use the same RAG token. Do not publish token files or runtime logs as assessment evidence
without checking/redacting their contents.

## Durable state and shutdown

The ignored `.propertyscope-runtime/host/` directory retains its historical name in both
placements. Its `ai-mode/` directory owns the run database; `rag/` owns the index/model cache.
Docker bind-mounts each directory only into its owning service. Host processes open those same
files after the containers stop, so switching requires no recurring migration or duplicate store.
Tokens and host process records remain there; Docker environment/catalogue projections live in
the ignored `.propertyscope-runtime/docker-ai/` directory. Never start both owners manually.

On initial setup, the legacy-history migration can find the old `ps-dev` AI-state volume, stop any
owning historical container, and copies the volume read-only through a helper container
that is never started. SQLite's backup API incorporates the copied WAL and verifies the
result before installing the host database. Existing host state is never overwritten and
the source volume is retained. An ambiguous owner, missing helper image or corrupt source
fails explicitly instead of silently discarding history.

```text
uv run scripts/dev.py ai stop rag
uv run scripts/dev.py ai stop
uv run scripts/dev.py stack down
```

Stopping preserves AI databases, model assets and Docker volumes. For host services the launcher checks
PID creation time, command and recorded checkout identity before signalling a process,
and accounts for the Windows virtualenv child interpreter. It never terminates an
unmanaged process just because that process occupies an expected port. Use `ai logs`
after a failed launch. `stack reset` retains host state and deletes the selected stack's
Docker data as its existing explicit destructive operation.

## CI boundary and validation

All workflows explicitly set `AI_MODE_MCP_ENABLED=false` and `AI_MODE_RAG_ENABLED=false`.
Student workflows validate shared retrieval contracts, signed MCP invocation metadata,
embedding lifecycle with doubles, and static runtime exclusions. They do not launch MCP
or RAG, download an embedding model, or contact a model provider. Student 5 retains its
existing persisted-run degradation smoke using direct host AI-mode with an unreachable
local provider endpoint; both advanced capabilities remain disabled.

Targeted runtime checks:

```text
uv run pytest scripts/tests/test_host_runtime.py scripts/tests/test_dev.py scripts/tests/test_generate_deployment.py scripts/tests/test_compose_naming.py --no-cov -q
uv run python scripts/generate_deployment.py --check
```

These deterministic tests cover process identity rejection, idempotent history migration,
wrong-volume-owner rejection, host catalogue projection and workflow/Compose exclusions. The
Docker placement adds selection/transition and container-entry checks in
`scripts/tests/test_ai_runtime.py` and `scripts/tests/test_container_entry.py`. Existing Release 1
host evidence remains separate from the new placement's validation. Real protocol, semantic
retrieval, integrated browser, placement-switch and provider evidence must be recorded separately;
passing unit tests does not establish those results.

## Named agent-loop validation modes

After starting the local stack and preparing/ingesting the approved guidance corpus, run:

```text
uv run scripts/dev.py ai validate mcp --output .propertyscope-runtime/release-1/validation-mcp.json
uv run scripts/dev.py ai validate rag --output .propertyscope-runtime/release-1/validation-rag.json
```

Both commands execute the production `AgentRunner`, prompt registry, contracts and a separate
temporary SQLite run store through Plan, Act, Observe and Adapt. MCP uses the official protocol
adapter and reads Feature 1's registered `platform.capabilities.v1` tool through the running
MCP server and Feature 1 backend. RAG uses the authenticated retrieval adapter and the running
semantic index; it copies a retrieved passage into a cited finding and validates the current
corpus version before completion. The commands do not restart services, prepare model assets,
ingest documents or modify the managed AI-mode run history.

Model decisions are explicitly deterministic (`extractive-validation.v1`). This isolates protocol
and orchestration validation from provider variability; it is not evidence of an actual model
answer or a semantic relevance evaluation. JSON outputs retain mode, pass/fail, all four phases,
correlation IDs, structured tool results, source citations and the final confidence category.
They exclude provider credentials, rendered model prompts and private reasoning traces.

The command exits nonzero when a service is unavailable, a tool fails or all four phases do not
complete. RAG distinguishes an answered query from a valid no-match/empty result using
`grounding_status` and `confidence`; inspect these fields rather than treating a successful
transport check as proof of relevant context. Use `--query` to supply an insufficient-context
probe and inspect its result. `--corpus` selects an already registered corpus without granting
new access. Real model/browser demonstration and the independent retrieval evaluation complement
these repeatable named modes.

CI refuses the live validation command and instead runs `scripts/tests/test_release1_validation.py`
with injected tool doubles. It does not start advanced services or silently fall back to test
data when a local service fails.
