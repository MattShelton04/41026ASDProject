# OpenAI API provider operations

## Purpose

AI-mode calls OpenAI through its provider-neutral `LLMProvider` boundary. The default logical
profile, `remote-standard.v1`, routes planner/implementer turns to `gpt-5.6-luna` and
adapter/reviewer turns to `gpt-5.6-terra` through the Responses API. Both use low reasoning; the
application caps the profile at 128K context and 16K maximum output, while individual agent calls
continue to request only the output budget they need. There is
no model server, model download, GPU overlay, or model volume in the repository topology.

The authoritative design and migration rationale are recorded in
[`ADR-017`](../architecture/decisions/ADR-017-openai-responses-provider.md) and the
[`migration plan`](../architecture/openai-remote-provider-migration-plan.md).

## Credential safety

Create an API key in the provider account with the narrowest practical project permissions and
make sure that project can access both routed models. Export the key only in the process environment
that launches AI-mode or Compose:

```text
# macOS/Linux (run in your shell; do not paste the resulting value into logs)
export OPENAI_API_KEY="..."

# PowerShell
$env:OPENAI_API_KEY="..."
```

Never place a real value in `shared/configuration/.env.example`, source code, Compose YAML,
terminal transcripts, screenshots, tickets, or committed `.env` files. Root `.gitignore`
excludes `.env` and `.env.*` except templates, but ignore rules are not a substitute for secret
review. Use the deployment platform's secret manager outside local development, rotate any key
that may have been exposed, and do not print the settings object or authorization headers.
Compose turns the host value into a service-scoped secret mounted at
`/run/secrets/openai_api_key`; it does not interpolate the credential into the container
environment or rendered Compose configuration.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `AI_MODE_LLM_PROVIDER` | Provider implementation selector | `openai` |
| `OPENAI_API_KEY` | Bearer credential; required for generation/readiness | unset |
| `OPENAI_API_KEY_FILE` | Mutually exclusive mounted credential path | unset; Compose supplies it |
| `OPENAI_BASE_URL` | Responses/Models API root | `https://api.openai.com/v1` |
| `OPENAI_TIMEOUT_SECONDS` | Per-generation ceiling before the run deadline is applied | `120` |
| `OPENAI_HEALTH_TIMEOUT_SECONDS` | Model-access readiness timeout | `2` |
| `OPENAI_MAX_RETRIES` | Additional attempts for transient failures | `2` |
| `AI_MODE_DEFAULT_MODEL_PROFILE` | Logical registry profile | `remote-standard.v1` |
| `AI_MODE_REQUIRE_PROVIDER_READY` | Make remote readiness affect `/health/ready` | host `false`; Compose `true` |

The base URL must be HTTPS. Plain HTTP is accepted only for explicit loopback test/development
endpoints, and embedded URL credentials are rejected. API keys are stored in a `repr=False`
settings field, newline-bounded, never logged, and sent only as an authorization header.

## Start and validate

For the complete reloadable stack:

```text
uv run scripts/dev.py up
uv run scripts/dev.py status
uv run scripts/dev.py logs ai-mode
```

For AI-mode on the host:

```text
uv run flask --app ai_mode:create_app run --port 5005
```

Run the live provider diagnostic only when intentional API usage is acceptable:

```text
uv run ai-mode-provider-smoke
```

The diagnostic first retrieves every model routed by the configured profile, then performs one small
JSON-Schema-guided response. It emits provider/model identifiers, validated non-sensitive
content, and token/timing metrics. It never prints the key. Routine unit, component, and CI
tests use mocked/scripted providers and require neither credentials nor internet access.

Useful endpoints after startup:

| URL | Expected result |
|---|---|
| `http://localhost:5005/health/live` | Process liveness without a provider call |
| `http://localhost:5005/health/ready` | Store plus `llm_provider` readiness |
| `http://localhost:5005/api/v1/model-profiles` | Registry v2 and selected provider model |

## Runtime behavior

- Requests use `POST /v1/responses`, `store: false`, bounded output, low reasoning effort, and
  an application-derived JSON Schema format.
- The dynamic `arguments` map in the public Plan contract cannot use OpenAI's strict closed
  schema subset. API strict mode is therefore false; agent-core validates the full Pydantic
  contract and allows at most one bounded repair attempt.
- The adapter retries only network/timeouts and HTTP `408`, `409`, `429`, `500`, `502`, `503`,
  or `504`, at most `OPENAI_MAX_RETRIES` times. It respects a bounded `Retry-After` delay and
  never extends the persisted run deadline.
- A stable `X-Client-Request-Id` is sent across all attempts for one inference. Response bodies,
  prompts, tool data, and authorization values are excluded from operational logs.
- `401`/`403`, missing model access, refusal, incomplete output, oversized output, malformed
  protocol data, and local validation failures map to safe typed provider errors.

## Troubleshooting

| Symptom | Check |
|---|---|
| `model_credentials_missing` | `OPENAI_API_KEY` exists in the launching process/container; do not print it |
| authentication/model access readiness failure | Key project permissions and access to both routed model IDs |
| `model_not_found` | Registry model ID and provider project access |
| `model_overloaded` | Provider rate/capacity limits or transient failure; retry remains bounded automatically |
| `model_timeout` | Run deadline first, then `OPENAI_TIMEOUT_SECONDS` and network path |
| `model_response_incomplete` | Output budget and request complexity |
| AI-mode healthy but provider degraded on host | Expected when `AI_MODE_REQUIRE_PROVIDER_READY=false`; direct CRUD remains available |

Stop the Compose stack without deleting durable application data:

```text
uv run scripts/dev.py down
```

## Primary API references

- [GPT-5.6 luna model](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [GPT-5.6 terra model](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [Responses API create reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [Model retrieval reference](https://developers.openai.com/api/reference/typescript/resources/models/methods/retrieve)
- [API authentication](https://platform.openai.com/docs/api-reference/authentication)
