# Local host AI runtime

Release 1 runs AI-mode, the agent loop, MCP and RAG as host Python processes. Compose
contains the shared edge and feature services. No AI-mode, MCP or RAG service is defined
in the base, development or generated Compose model. This follows the updated Release 1
brief supplied on 6 September 2026; older containerised AI-mode instructions are historical.

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

`stack up` starts the managed host services and containerised features. Source changes
reload in the feature development containers; host Python services require an explicit
stop/start after changes. Host status checks process ownership. Service liveness and
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

For host source changes, use `ai stop` then `ai start --mode combined`. The `ai serve
ai-mode`, `ai serve mcp` and `ai serve rag` commands run a single foreground process using
already configured environment variables. Normal managed startup is preferable because
it generates local catalogue projections, state paths and service tokens consistently.

## Networking and credentials

| Process | Default address | Reachability |
|---|---|---|
| AI-mode | port 5005, host bind `0.0.0.0` | Docker feature backends and shared edge use `host.docker.internal` |
| MCP | `127.0.0.1:5011/mcp` | Authenticated host AI-mode only |
| RAG | `127.0.0.1:5012` | Authenticated host AI-mode and explicit ingestion tooling |

`AI_MODE_PORT`, `MCP_PORT` and `RAG_PORT` configure the host listeners. Feature HTTP ports
come from the existing manifest variables. The launcher derives host catalogue copies
from enabled feature manifests and maps their fixed service origins to the published
feature frontend ports. Tool names, schemas, approval classification and owning backend
paths are preserved. Original feature catalogues continue to describe the domain boundary.

Compose sets `host.docker.internal:host-gateway` for the shared edge and feature backends,
including Linux Docker Engine. The edge resolves its configured host upstream at nginx
startup. MCP/RAG do not need container access and retain loopback binding. AI-mode keeps
the existing trusted local demonstration API boundary; because Docker needs a reachable
host listener, run it only on the trusted development machine/network. Managed startup
rejects non-local deployment environments. A production user-authentication boundary is
outside this host demonstration profile.

Provider credentials remain in an ignored file loaded by the host process, never in a
Compose secret, image, process command or printed environment. The launcher creates
independent MCP/RAG bearer tokens under the ignored host directory unless explicitly
configured with `MCP_SERVICE_TOKEN` and `RAG_SERVICE_TOKEN`. Source ingestion clients must
use the same RAG token. Do not publish token files or runtime logs as assessment evidence
without checking/redacting their contents.

## Durable state and shutdown

The ignored `.propertyscope-runtime/host/` directory owns the AI-mode SQLite store, RAG
index/model cache, generated catalogue copies, tokens, bounded log views and process
identity records. AI-mode alone opens its run database; RAG alone opens its index.
Before first host startup, the launcher finds the old `ps-dev` AI-state volume, stops any
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

Stopping preserves host databases, model assets and Docker volumes. The launcher checks
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
wrong-volume-owner rejection, host catalogue projection and workflow/Compose exclusions.
An isolated Windows host AI-mode start, liveness and stop was exercised during implementation.
Real protocol, semantic retrieval, integrated browser and provider evidence are recorded
separately in the release evidence index; passing unit tests does not establish those results.
