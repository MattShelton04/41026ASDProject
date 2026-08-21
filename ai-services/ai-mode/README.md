# AI-mode shared agent orchestrator

`ai-mode` owns the HTTP orchestration boundary, workflow-state SQLite database,
versioned prompts, OpenAI Responses API integration, and concurrency-one background worker.
The name follows the assignment's **AI mode** capability; operationally this container
is the shared agent orchestrator. OpenAI owns remote model inference; AI-mode owns all
application orchestration, validation, persistence, and tool policy.

## HTTP surface

| Method and path | Behavior |
|---|---|
| `GET /health/live` | Process liveness; never calls dependencies |
| `GET /health/ready` | Store readiness plus a truthful healthy/degraded provider check |
| `GET /api/v1/model-profiles` | Inspect supported models and bounded logical profiles |
| `GET /api/v1/agent-runs` | Flagged operations index with stable cursor pagination and filters |
| `POST /api/v1/agent-runs` | Validate, persist, enqueue, and return `202` |
| `GET /api/v1/agent-runs/{id}` | Return the safe run, ordered steps, and reviews |
| `GET /api/v1/agent-runs/{id}/events` | Return safe ordered events after a resumable cursor |
| `GET /api/v1/operations/agent-runs/{id}` | Flagged, redacted evidence projection with weak ETag |
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

The adapter calls `POST /v1/responses` with `store: false`, low reasoning effort, bounded
output, a client request ID, and a JSON Schema format. The Plan contract contains dynamic
tool-argument objects, which are incompatible with OpenAI's closed/all-required strict
schema subset, so API strict mode is deliberately disabled. Agent-core still validates the
complete application contract and permits at most one repair turn. Readiness retrieves only
the selected model through `GET /v1/models/{model}`.

| Variable | Default |
|---|---|
| `AI_MODE_DATABASE_PATH` | `instance/agent-state.sqlite3` |
| `AI_MODE_LLM_PROVIDER` | `openai` |
| `OPENAI_API_KEY` | unset; direct host-process credential |
| `OPENAI_API_KEY_FILE` | unset; mutually exclusive file-mounted credential used by Compose |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` |
| `OPENAI_TIMEOUT_SECONDS` | `120` |
| `OPENAI_HEALTH_TIMEOUT_SECONDS` | `2` |
| `OPENAI_MAX_RETRIES` | `2` |
| `AI_MODE_DEFAULT_MODEL_PROFILE` | registry default (`remote-standard.v1`) |
| `AI_MODE_MODEL_REGISTRY_PATH` | bundled `registry.v2.yaml` |
| `AI_MODE_MAX_MODEL_RESPONSE_BYTES` | `1048576` |
| `AI_MODE_REQUIRE_PROVIDER_READY` | `false` |
| `AI_MODE_MAX_REQUEST_BYTES` | `65536` |
| `AI_MODE_MAX_TOOL_REQUEST_BYTES` | `262144` |
| `AI_MODE_MAX_TOOL_RESPONSE_BYTES` | `1048576` |
| `AI_MODE_QUEUE_CAPACITY` | `100` |
| `AI_MODE_QUEUE_RECONCILE_INTERVAL_SECONDS` | `1` |
| `AI_MODE_ENVIRONMENT` | `local` |
| `AI_MODE_LOG_LEVEL` | `INFO` |
| `AI_MODE_TOOL_CATALOG_PATH` | unset; legacy single-catalog path |
| `AI_MODE_TOOL_CATALOG_PATHS` | unset; ordered comma-separated catalog paths |
| `AI_MODE_EVIDENCE_ACCESS_TOKEN` | unset (view absent) |
| `AI_MODE_OPERATIONS_ENABLED` | `false` (dashboard and operations API absent) |
| `AI_MODE_OPERATIONS_ASSETS_PATH` | repository `shared/frontend/operations/ai-mode` path |

### Operations dashboard

The domain-neutral, read-only operations dashboard lists durable runs and follows a selected
run's safe cursor events at `/operations/ai-mode/`. It displays policy-projected evidence,
model/tool timings, limits, and correlation identifiers; it never reads SQLite or calls OpenAI from
the browser. Enable it only for trusted local development or demonstrations:

```text
AI_MODE_OPERATIONS_ENABLED=true uv run flask --app ai_mode:create_app run --port 5005
```

On PowerShell, set `$env:AI_MODE_OPERATIONS_ENABLED='true'` before the Flask command. The
dashboard and its list/evidence endpoints are not registered when the flag is false. Remote
deployment remains disabled until the team defines authenticated operator and feature scopes.

The run index refreshes every two seconds while active work is loaded and every ten seconds
when the page is terminal; hidden tabs back off further. Selected active runs keep the measured
800 ms durable-event cadence. All client requests time out after eight seconds, obsolete work
is aborted/version-checked, and list refreshes never overlap. The interface derives elapsed run
and running-step time locally from persisted timestamps and labels planner, adapter, and tool
waiting honestly without inventing progress. Revisited runs rehydrate a bounded, de-duplicated
event journal before resuming their saved cursor.

Application logs remain stdout-only. The dashboard prioritizes persisted evidence and copyable
correlation identifiers; a future authenticated deployment should deep-link to a proper
collector-backed telemetry service rather than expose arbitrary or recursively polled log text
from AI-mode.

Run locally with:

```text
uv run flask --app ai_mode:create_app run --port 5005
```

The provider setup is documented in
[`docs/release-0/openai-api-operations.md`](../../docs/release-0/openai-api-operations.md).
The `ai-mode-provider-smoke` console command performs a real provider-level structured
output diagnostic without owning Docker lifecycle or feature behavior. It uses the same
settings parser, logical model profile, and provider factory as the running service, and
selects a role explicitly declared by that profile so role enforcement is exercised too.

### Supported models and profiles

The strict registry separates the stable client-facing profile name from concrete,
role-routed provider model IDs:

| Profile | Implementer (planner) | Reviewer (adapter/reviewer) | Runtime context | Output maximum | Reasoning |
|---|---|---|---:|---:|---|
| `remote-standard.v1` | `gpt-5.6-luna` | `gpt-5.6-terra` | 128K | 16K | low |

The provider advertises a much larger context for both models, but this application deliberately
caps the profile at 128K and does not target the 1.05M window. Individual agent requests retain
their smaller explicit output limits, so the 16K profile maximum is not a default spend. Luna handles frequent
implementation-planning turns at the lowest current GPT-5.6 price tier; Terra is reserved for
adaptation/review where additional quality is worth its higher per-token cost. Agent-core calls
the adapter only when deterministic observation cannot settle the run, limiting that expense.
Select a registered profile in `AgentRunRequest.model_profile`; omitting
it uses the service's configured default. Intended roles are enforced rather than being
descriptive metadata: Release 0 runs require planner and adapter support, and every
provider call rejects a mismatched role before network I/O. Readiness verifies access to every
distinct model routed by the selected profile.

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
agents. Each role is a separate stateless OpenAI request with its own versioned system
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

AI-mode emits one-line JSON operational events to stdout for HTTP completion, worker
boundaries, model invocations, and feature tool calls. The schema includes stable nullable
correlation fields and deliberately excludes prompts, tool arguments/results, authorization
headers, and response bodies. An inbound valid `traceparent` contributes its trace ID for
correlation; this baseline does not claim to create OpenTelemetry child spans.

## Feature tool integration

The default tool registry remains empty. `AI_MODE_TOOL_CATALOG_PATH` can point to one
catalogue for compatibility, while `AI_MODE_TOOL_CATALOG_PATHS` composes an ordered,
comma-separated set of feature catalogues. Configure only one variable. Cross-file duplicate
service identities or tool bindings fail startup. Each file is a strict YAML startup
catalogue. It binds immutable feature-owned definitions to fixed
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
