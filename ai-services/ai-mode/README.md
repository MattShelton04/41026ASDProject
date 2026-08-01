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
| `POST /api/v1/agent-runs` | Validate, persist, enqueue, and return `202` |
| `GET /api/v1/agent-runs/{id}` | Return the safe run, ordered steps, and reviews |
| `GET /api/v1/agent-runs/{id}/events` | Return safe ordered events after a resumable cursor |
| `POST /api/v1/agent-runs/{id}/cancel` | Idempotently record cancellation intent |
| `POST /api/v1/agent-runs/{id}/reviews` | Approve/reject exactly one pending action |

All responses propagate `X-Request-ID`; agent responses also include
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
| `OLLAMA_MODEL` | `qwen2.5:0.5b` |
| `OLLAMA_TIMEOUT_SECONDS` | `120` |
| `OLLAMA_HEALTH_TIMEOUT_SECONDS` | `2` |
| `OLLAMA_KEEP_ALIVE` | `5m` |
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

The SQLite adapter enables foreign keys, WAL mode, a busy timeout, forward schema
versioning, optimistic run versions, create-request idempotency, and safe append-only
progress events. Run and step changes, review records, and their corresponding event
are committed atomically. On startup, incomplete runs are reconciled from
their persisted phase boundary: safe work is re-enqueued and uncertain writes return to
human review. The worker performs the same durable discovery while idle, so the bounded
memory queue is a wake-up optimization rather than a source of truth.

## Feature tool integration

The default registry remains empty, but `AI_MODE_TOOL_CATALOG_PATH` can now point to a
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
