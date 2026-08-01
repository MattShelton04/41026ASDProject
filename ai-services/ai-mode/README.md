# AI-mode shared agent orchestrator

`ai-mode` owns the HTTP orchestration boundary, workflow-state SQLite database,
versioned prompts, native Ollama integration, and concurrency-one background worker.
The name follows the assignment's **AI mode** capability; operationally this container
is the shared agent orchestrator. The separate `ollama` container owns model inference.

## HTTP surface

| Method and path | Behavior |
|---|---|
| `GET /health/live` | Process liveness; never calls dependencies |
| `GET /health/ready` | Store readiness plus a truthful healthy/degraded Ollama check |
| `GET /api/v1/model-profiles` | Inspect supported models and bounded logical profiles |
| `POST /api/v1/agent-runs` | Validate, persist, enqueue, and return `202` |
| `GET /api/v1/agent-runs/{id}` | Return the safe run, ordered steps, and reviews |
| `GET /api/v1/agent-runs/{id}/events` | Return safe ordered events after a resumable cursor |
| `POST /api/v1/agent-runs/{id}/cancel` | Idempotently record cancellation intent |
| `POST /api/v1/agent-runs/{id}/reviews` | Approve/reject exactly one pending action |

All responses propagate a safe caller-supplied `X-Request-ID`, or a generated UUID when
the supplied value is absent or invalid; agent responses also include
`X-Agent-Run-ID`. Valid W3C `traceparent` values are persisted and forwarded to feature
tools. `POST /agent-runs` supports `Idempotency-Key`, returning the original run for an
exact retry and `409` for key reuse with changed input. Errors use the shared Problem
Details-compatible contract. JSON bodies are rejected before parsing when they exceed
the configured limit.

## Configuration

The adapter calls Ollama's native `/api/chat` endpoint to retain JSON Schema output,
`keep_alive`, token counts, and detailed durations. If the course `/v1` base URL is
supplied, configuration normalizes it to the native API root.

Some valid application schemas exceed llama.cpp's grammar-complexity limit. The adapter
recognizes that specific rejection and retries in Ollama JSON mode; the agent-core
validator and bounded repair turn still enforce the complete application schema. Other
HTTP 400 responses remain terminal request errors.

| Variable | Default |
|---|---|
| `AI_MODE_DATABASE_PATH` | `instance/agent-state.sqlite3` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` |
| `OLLAMA_TIMEOUT_SECONDS` | `120` |
| `OLLAMA_HEALTH_TIMEOUT_SECONDS` | `2` |
| `OLLAMA_KEEP_ALIVE` | unset (use each registry profile's value) |
| `AI_MODE_DEFAULT_MODEL_PROFILE` | registry default (`local-standard.v1`) |
| `AI_MODE_MODEL_REGISTRY_PATH` | bundled `registry.v1.yaml` |
| `AI_MODE_MAX_MODEL_RESPONSE_BYTES` | `1048576` |
| `AI_MODE_REQUIRE_OLLAMA_READY` | `false` |
| `AI_MODE_MAX_REQUEST_BYTES` | `65536` |
| `AI_MODE_MAX_TOOL_REQUEST_BYTES` | `262144` |
| `AI_MODE_MAX_TOOL_RESPONSE_BYTES` | `1048576` |
| `AI_MODE_TOOL_CATALOG_PATH` | unset (no tools registered) |
| `AI_MODE_EVIDENCE_ACCESS_TOKEN` | unset (view absent) |

Run locally with:

```text
uv run flask --app ai_mode:create_app run --port 5005
```

The assignment-aligned Compose path and the native-host alternative are documented in
[`docs/release-0/ollama-operations.md`](../../docs/release-0/ollama-operations.md).
The `ai-mode-ollama-smoke` console command performs a real provider-level structured
output diagnostic without owning Docker lifecycle or feature behavior. It uses the same
settings parser, logical model profile, and provider factory as the running service.

### Supported models and profiles

The strict registry separates stable client-facing profile names from concrete Ollama
tags. It includes one assignment-approved model from each permitted family:

| Profile | Ollama tag | Advertised maximum | Runtime context | Output maximum | Intended use |
|---|---|---:|---:|---:|---|
| `local-standard.v1` | `qwen2.5:3b` | 32K | 8K | 1K | Default Release 0 demonstration profile |
| `local-small.v1` | `qwen2.5:1.5b` | 32K | 8K | 1K | Constrained-machine planner/adapter evaluation |
| `local-smoke.v1` | `qwen2.5:0.5b` | 32K | 4K | 512 | Provider compatibility smoke only |
| `local-balanced.v1` | `llama3.1:8b` | 128K | 16K | 2K | Representative local planning/review evaluation |
| `local-reasoning.v1` | `deepseek-r1:8b` | 128K | 16K | 4K | Explicit reasoning/reviewer evaluation |

Runtime contexts are intentionally below advertised maxima because context allocation
affects memory. Select a registered profile in `AgentRunRequest.model_profile`; omitting
it uses the service's configured default. For Compose, `OLLAMA_MODEL` controls the model
initializer and must name the concrete tag corresponding to
`AI_MODE_DEFAULT_MODEL_PROFILE`. Pull optional profile models explicitly before use.

The registry YAML is deliberate source configuration and can be replaced as a whole
with `AI_MODE_MODEL_REGISTRY_PATH`. It is validated offline at startup and by:

```text
uv run python scripts/validate_model_registry.py
```

Its public JSON Schema and the endpoint's OpenAPI definition are generated from the
Pydantic contract and drift-checked by `scripts/generate_contracts.py --check` in CI.
For a containerised custom registry, mount the file read-only and set
`AI_MODE_MODEL_REGISTRY_PATH` to its path inside the container; a host path is not
implicitly visible in Docker.

The default `default.v3` prompt set keeps the explicit generic output skeletons and
adds an evidence-completeness policy for ordered multi-action objectives. Immutable
`default.v1` and `default.v2` remain accepted for replaying runs created with the
earlier prompt assets.

Planner and adapter are roles in one persisted orchestrator, not separate long-lived
agents. Each role is a separate stateless Ollama request with its own versioned system
prompt. The planner receives the objective and allowlisted tools; the adapter receives
the active plan's ordered persisted action/results and current observation. Successful
intermediate actions continue by deterministic orchestration policy, avoiding an
unnecessary adapter inference while preserving an auditable ADAPT step.

The SQLite adapter enables foreign keys, WAL mode, a busy timeout, forward schema
versioning, optimistic run versions, create-request idempotency, and safe append-only
progress events. Run and step changes, review records, and their corresponding event
are committed atomically. On startup, incomplete runs are reconciled from
their persisted phase boundary: safe work is re-enqueued and uncertain writes return to
human review. The worker performs the same durable discovery while idle, so the bounded
memory queue is a wake-up optimization rather than a source of truth.

## Feature tool integration

The default tool registry remains empty, but `AI_MODE_TOOL_CATALOG_PATH` can point to a
strict YAML startup catalogue. It binds immutable feature-owned definitions to fixed
service identities, methods, and paths. A run sees only its feature's definitions plus
explicitly approved shared tools. The HTTP adapter does not accept model-provided URLs,
does not follow redirects, bounds both directions, validates media type and output
schema, applies the remaining deadline, propagates correlation/idempotency headers,
and maps failures to safe typed results without response-body leakage.

An optional `/development/agent-runs/{id}` evidence view exists only when a bearer token
of at least 16 characters is configured. It HTML-escapes content and redacts sensitive
field names. The `examples/integration-test-feature` package proves a full deterministic
loop over real HTTP and a separately owned SQLite database without claiming a product
feature. Production feature manifests, endpoints, and Compose topology still require
the approved team domain and feature ownership decisions.
MCP, RAG, and multi-agent runtime services remain release-gated.
