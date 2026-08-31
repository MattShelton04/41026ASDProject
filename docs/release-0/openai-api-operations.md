# OpenAI API provider operations

## Purpose

AI-mode calls OpenAI through its provider-neutral `LLMProvider` boundary. The default logical
profile, `remote-standard.v1`, routes planner/implementer turns to `gpt-5.6-luna` and
adapter/reviewer turns to `gpt-5.6-terra` through the Responses API. Both use low reasoning; the
application caps the profile at 128K context and 16K maximum output, while individual agent calls
continue to request only the output budget they need. There is
no model server, model download, GPU overlay, or model volume in the repository topology.

The production default deliberately uses the Responses protocol. `OPENAI_BASE_URL` may target
OpenAI or another service that implements
the required OpenAI **Responses create** and **Models retrieve** endpoints. Chat Completions
compatibility alone is insufficient. Disable `OPENAI_PROMPT_CACHE_ENABLED` when an otherwise
compatible service does not accept OpenAI's prompt-cache fields. Model IDs and role routing remain
registry configuration, so feature code and `agent-core` do not change.

Local development also supports Gemini through Google's OpenAI-compatible Chat Completions and
Models endpoints. This is an explicit `gemini` provider mode rather than a base-URL-only swap
because Google's compatibility endpoint does not implement Responses create.

The authoritative design and migration rationale are recorded in
[`ADR-017`](../architecture/decisions/ADR-017-openai-responses-provider.md) and the
[`migration plan`](../architecture/openai-remote-provider-migration-plan.md).

## Credential safety

Create an API key in the provider account with the narrowest practical project permissions and
make sure that project can access both routed models. Export the key only in the process environment
that launches AI-mode or place it in the Git-ignored root `.env` used by the development command:

```text
# macOS/Linux (run in your shell; do not paste the resulting value into logs)
export OPENAI_API_KEY="..."

# PowerShell
$env:OPENAI_API_KEY="..."
```

Never place a real value in any `.env.example`, source code, Compose YAML, terminal transcripts,
screenshots, tickets, or committed `.env` files. Root `.gitignore`
excludes `.env` and `.env.*` except templates, but ignore rules are not a substitute for secret
review. Use the deployment platform's secret manager outside local development, rotate any key
that may have been exposed, and do not print the settings object or authorization headers.
`scripts/dev.py` writes the host value atomically to a Git-ignored, mode-restricted runtime file.
Compose mounts that file as `/run/secrets/openai_api_key`; it does not interpolate the credential
into the container environment or rendered Compose configuration.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `AI_MODE_LLM_PROVIDER` | Provider implementation selector | `openai` |
| `OPENAI_API_KEY` | Bearer credential; required for generation/readiness | unset |
| `OPENAI_API_KEY_FILE` | Mutually exclusive mounted credential path | runtime file supplied by `scripts/dev.py` |
| `OPENAI_BASE_URL` | Responses/Models API root | `https://api.openai.com/v1` |
| `GEMINI_API_KEY` | Gemini credential when `AI_MODE_LLM_PROVIDER=gemini` | unset |
| `GEMINI_API_KEY_FILE` | Mutually exclusive mounted Gemini credential path | runtime file supplied by `scripts/dev.py` |
| `GEMINI_BASE_URL` | Gemini Chat Completions/Models root | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `OPENAI_ALLOW_INSECURE_HTTP` | Permit non-loopback HTTP for a trusted local compatible endpoint | `false` |
| `OPENAI_TIMEOUT_SECONDS` | Per-generation ceiling before the run deadline is applied | `120` |
| `OPENAI_HEALTH_TIMEOUT_SECONDS` | Model-access readiness timeout | `2` |
| `OPENAI_HEALTH_CACHE_SECONDS` | Readiness result TTL, limiting remote health traffic | `60` |
| `OPENAI_MAX_RETRIES` | Additional attempts for transient failures | `2` |
| `OPENAI_PROMPT_CACHE_ENABLED` | OpenAI explicit cache key/breakpoint extensions | `true` |
| `AI_MODE_DEFAULT_MODEL_PROFILE` | Logical registry profile | `remote-standard.v1` |
| `AI_MODE_REQUIRE_PROVIDER_READY` | Make remote readiness affect `/health/ready` | host `false`; Compose `true` |

The base URL must be HTTPS. Plain HTTP is accepted for loopback or only after setting
`OPENAI_ALLOW_INSECURE_HTTP=true` for a trusted local development endpoint such as
`http://host.docker.internal:8080/v1`; embedded URL credentials are rejected. API keys are stored in a `repr=False`
settings field, newline-bounded, never logged, and sent only as an authorization header.

## Start and validate

For the complete reloadable stack:

```text
Copy-Item .env.example .env  # Windows PowerShell; first setup only
# cp .env.example .env       # macOS/Linux; first setup only
# Add OPENAI_API_KEY to .env.
uv run scripts/dev.py stack up
uv run scripts/dev.py stack status
uv run scripts/dev.py stack logs shared-ai-mode
```

Stack commands automatically load the optional root `.env`; shell variables retain precedence, and
`--env-file` selects a different dotenv file instead. The helper copies the selected credential into
`.propertyscope-runtime/`, which is Git-ignored, and passes only that file path to Compose. This
file-backed secret is compatible with the read-only AI-mode container on Compose implementations
that cannot materialise environment-backed secrets there. `down` removes the corresponding runtime
file. Use `up --offline` for deterministic data work without live model readiness.

For Gemini, create a Git-ignored `.env.gemini`:

```dotenv
AI_MODE_LLM_PROVIDER=gemini
GEMINI_API_KEY=<your key>
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
AI_MODE_DEFAULT_MODEL_PROFILE=gemini-development.v1
OPENAI_PROMPT_CACHE_ENABLED=false
```

Start with `uv run scripts/dev.py stack up --env-file .env.gemini`. Use
`gemini-quality.v1` only when intentionally comparing Gemini 3.7 quality and cost.

For AI-mode on the host:

```text
uv run flask --app ai_mode:create_app run --port 5005
```

Run the live provider diagnostic only when intentional API usage is acceptable:

```text
uv run ai-mode-provider-smoke
```

Validate the complete configuration and routing without a credential, network traffic, or spend:

```text
uv run ai-mode-provider-smoke --dry-run
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

- The official OpenAI SDK owns request serialization, authentication, and the OpenAI protocol;
  the adapter owns application deadlines, bounded retries, response-size limits, and safe errors.
- Requests use `POST /v1/responses`, `store: false`, disabled automatic truncation, bounded output,
  low reasoning effort, and an application-derived JSON Schema format. `store: false` disables
  response storage for later retrieval; it is not a promise that provider-side safety or abuse
  retention is zero.
- Stable system prompts are placed before dynamic input with an explicit cache breakpoint and a
  deterministic key. Prompt caching only applies once provider/model minimum prefix requirements
  are met. Read/write token counts are recorded so the benefit can be measured rather than assumed.
  The current compact prompt assets may remain below that threshold, so cache hits are not promised
  and prompts should not be padded merely to force them. Set `OPENAI_PROMPT_CACHE_ENABLED=false`
  for compatible endpoints without these extensions.
- The registry context window is enforced conservatively before network I/O, reserving the output
  budget and a safety margin. The adapter does not make a second paid/remote token-count request.
- The dynamic `arguments` map in the public Plan contract cannot use OpenAI's strict closed
  schema subset. API strict mode is therefore false; agent-core validates the full Pydantic
  contract and allows up to the run's configured two bounded repair attempts. Feature 1 uses two;
  other callers retain the default of one.
- The adapter retries only network/timeouts and HTTP `408`, `409`, `429`, `500`, `502`, `503`,
  or `504`, at most `OPENAI_MAX_RETRIES` times. It respects a bounded `Retry-After` delay and
  never extends the persisted run deadline.
- A stable `X-Client-Request-Id` is sent across all attempts for one inference. Response bodies,
  prompts, tool data, and authorization values are excluded from operational logs.
- `401`/`403`, missing model access, refusal, incomplete output, oversized output, malformed
  protocol data, and local validation failures map to safe typed provider errors.
- Model-access readiness is cached for `OPENAI_HEALTH_CACHE_SECONDS`, preventing container health
  polling from becoming continuous provider API traffic.

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
| compatible endpoint rejects cache fields | Set `OPENAI_PROMPT_CACHE_ENABLED=false` and rerun the live diagnostic |
| local HTTP endpoint rejected | Keep it trusted and set `OPENAI_ALLOW_INSECURE_HTTP=true`; never use this for production internet traffic |

Stop the Compose stack without deleting durable application data:

```text
uv run scripts/dev.py stack down
```

## Primary API references

- [GPT-5.6 luna model](https://developers.openai.com/api/docs/models/gpt-5.6-luna)
- [GPT-5.6 terra model](https://developers.openai.com/api/docs/models/gpt-5.6-terra)
- [Responses API create reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
- [Model retrieval reference](https://developers.openai.com/api/reference/typescript/resources/models/methods/retrieve)
- [API authentication](https://platform.openai.com/docs/api-reference/authentication)
