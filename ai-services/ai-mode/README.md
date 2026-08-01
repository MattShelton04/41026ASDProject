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
| `POST /api/v1/agent-runs/{id}/cancel` | Idempotently record cancellation intent |
| `POST /api/v1/agent-runs/{id}/reviews` | Approve/reject exactly one pending action |

All responses propagate `X-Request-ID`; agent responses also include
`X-Agent-Run-ID`. Errors use the shared Problem Details-compatible contract.

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
versioning, and optimistic run versions. Run and step changes—and review records where
applicable—are committed atomically. On startup, incomplete runs are reconciled from
their persisted phase boundary: safe work is re-enqueued and uncertain writes return to
human review. The worker performs the same durable discovery while idle, so the bounded
memory queue is a wake-up optimization rather than a source of truth.

## Current integration boundary

The default tool registry is intentionally empty until the approved product features
define their owned, allowlisted backend tools. A run can be accepted and can contact
Ollama, but any invented or unregistered tool fails before dispatch. The next vertical
integration increment must configure feature-owned HTTP tool definitions/execution;
it must not add feature business behavior to this service.

Resumable event streaming, the development run-detail page, and the reference feature
are also remaining Release 0 work.
MCP, RAG, and multi-agent runtime services remain release-gated.
