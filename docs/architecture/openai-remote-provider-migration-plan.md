# OpenAI remote provider migration: problem, scope, and plan

## Document control

| Field | Value |
|---|---|
| Status | Implemented; retained as problem statement, scope, and verification record |
| Date | 21 August 2026 |
| Scope | Shared `agent-core` provider contract, `ai-mode`, model registry, local Compose workflow, CI, active documentation, and generated contracts |
| Target provider | OpenAI API |
| Default routing | `gpt-5.6-luna` implementer/planner; `gpt-5.6-terra` adapter/reviewer |
| Decision record | [`decisions/ADR-017-openai-responses-provider.md`](decisions/ADR-017-openai-responses-provider.md) |

## Problem

AI-mode currently has a provider-neutral `LLMProvider` port, but its only production adapter,
configuration vocabulary, model registry, readiness projection, diagnostics, Compose topology,
developer helper, and active runbooks are coupled to a locally hosted Ollama runtime. This adds a
model container, initializer, model volume, GPU/CPU branching, multi-gigabyte downloads, and a
machine-dependent inference path to every integrated environment.

That operational weight is no longer desired. The requested outcome is a remote LLM API boundary,
with OpenAI as the initial/default provider and GPT-5.6 Luna as the default model, while preserving
the deterministic Plan -> Act -> Observe -> Adapt loop, logical profile selection, structured
outputs, policy checks, workflow persistence, feature-owned HTTP tools, and offline deterministic
tests.

## Current usage inventory

| Surface | Current behavior | Migration treatment |
|---|---|---|
| `agent-core` | Provider-neutral synchronous structured-generation and health port | Preserve; add only portable usage fields needed for remote-provider evidence |
| AI-mode adapter | Native Ollama `/api/chat` and `/api/tags`, JSON-schema fallback, local timing fields | Replace with an OpenAI Responses API adapter and remote model-readiness check |
| Model registry | Ollama-only tags, open-family enum, parameter/download metadata, `keep_alive` | Replace with provider/model IDs, reasoning effort, and remote capacity metadata; bump registry schema |
| Configuration | `OLLAMA_*` and `AI_MODE_REQUIRE_OLLAMA_READY` | Replace with `OPENAI_*` and provider-neutral `AI_MODE_REQUIRE_PROVIDER_READY` |
| Default run contract | `local-standard.v1` | Change to stable logical profile `remote-standard.v1` |
| Compose | Ollama service, initializer, model volume, GPU/native-host overlays | Remove; pass the API key at container runtime only |
| Developer CLI | Pulls a model and branches on GPU availability | Start application services directly; retain a provider smoke command |
| CI | Validates local/GPU/native Compose and optionally starts Ollama | Validate the single remote-provider topology; keep live API smoke opt-in and secret-gated |
| Readiness/UI | Dependency key is named `ollama` | Rename to `llm_provider` so consumers remain provider-neutral |
| Active docs | Treat Ollama as the Release 0 canonical runtime | Update to the remote provider architecture and secret-handling workflow |
| Historical review/release evidence | Point-in-time Ollama references | Preserve unless an active link or status would otherwise mislead |

## Verified OpenAI API fit

The implementation is based on the official OpenAI API documentation current on 21 August 2026:

- GPT-5.6 Luna's model ID is `gpt-5.6-luna`. It supports the Responses API and Structured Outputs,
  has a 1,050,000-token context window and a 128,000-token maximum output. It is positioned for
  cost-sensitive, high-volume workloads: <https://developers.openai.com/api/docs/models/gpt-5.6-luna>.
- GPT-5.6 Terra's model ID is `gpt-5.6-terra`. OpenAI positions it as the balance of intelligence
  and cost, so the design reserves it for less-frequent reviewer turns:
  <https://developers.openai.com/api/docs/models/gpt-5.6-terra>.
- OpenAI recommends the Responses API for reasoning and agentic workflows. `POST /v1/responses`
  accepts `model`, `input`, `instructions`, `max_output_tokens`, `reasoning`, and
  `text.format`; a JSON Schema format guides structured output:
  <https://developers.openai.com/api/reference/cli/resources/responses/methods/create>.
- GPT-5.6 supports `none`, `low`, `medium`, `high`, `xhigh`, and `max` reasoning effort. The
  migration starts at explicit `low` for the cost-sensitive planner/adapter workload and leaves
  prompt tuning to measured evaluations:
  <https://developers.openai.com/api/docs/guides/model-guidance?model=gpt-5.6>.
- API keys use HTTP Bearer authentication and must be loaded server-side from an environment
  variable or secret manager, never committed or exposed to a browser:
  <https://platform.openai.com/docs/api-reference/authentication>.
- `GET /v1/models/{model}` verifies that the configured credential can retrieve the selected model
  without spending generation tokens:
  <https://developers.openai.com/api/reference/typescript/resources/models/methods/retrieve>.

The provider sends `store: false`, does not use hosted tools, and reconstructs every planner,
adapter, or reviewer request from the repository's persisted safe state. The operational profile
is capped at 128K context and 16K maximum output; the provider's advertised 1.05M context is provenance
metadata, not an application target or allocation. This preserves the existing local
orchestrator as the workflow and authorization authority rather than outsourcing agent state or
tool execution to the model provider.

## Target architecture

```text
feature backend
  -> AI-mode HTTP API
  -> deterministic agent runner and policy
  -> OpenAIProvider (LLMProvider adapter)
  -> HTTPS POST /v1/responses
  -> JSON-Schema-guided response
  -> application validation and at most one repair turn
  -> allowlisted feature HTTP tool execution
```

The API key exists only in the AI-mode server/container environment. It is excluded from request
payloads, logs, workflow state, health details, evidence views, images, and source-controlled
configuration. The browser and student feature services never receive it.

## Implementation plan

1. **Provider and registry contracts**
   - Make the public model registry describe provider/model IDs rather than Ollama artefacts.
   - Add explicit reasoning effort and preserve logical profile/role/output limits.
   - Set `remote-standard.v1` to route planner/implementer turns to `gpt-5.6-luna` and
     adapter/reviewer turns to `gpt-5.6-terra`, with a deliberately bounded 128K context.
2. **OpenAI adapter**
   - Implement non-streaming `POST /v1/responses` with Bearer auth, JSON Schema guidance,
     `store: false`, bounded response bytes, deadline-aware timeouts, safe error mapping, bounded
     transient retries, request correlation, and token/timing evidence.
   - Implement non-throwing readiness via `GET /v1/models/{model}` and a clear no-key degraded
     state.
3. **Composition and configuration**
   - Replace Ollama settings and factory names with provider-neutral/OpenAI names.
   - Keep application startup possible without a key when strict readiness is disabled; model
     calls fail safely and readiness is degraded. Integrated Compose enables strict readiness.
4. **Runtime simplification**
   - Remove the Ollama service, initializer, model volume, GPU/native-host overlays, pull flags,
     and local acceleration detection.
   - Forward `OPENAI_API_KEY` at runtime from an untracked `.env`/shell/secret store; never bake it
     into an image or provide a sample value that resembles a credential.
5. **Diagnostics and CI**
   - Rename the diagnostic to `ai-mode-provider-smoke` and keep live invocation explicit and
     credential-supplied rather than part of deterministic CI.
   - Replace Ollama-specific contract tests with deterministic mocked OpenAI HTTP tests covering
     request shape, schema handling, auth omission, readiness, deadlines, retries, size bounds,
     refusals/incomplete responses, metrics, and safe errors.
6. **Contracts and documentation**
   - Regenerate JSON Schema/OpenAPI artefacts.
   - Update the root, shared-service, configuration, release, and living-architecture documents.
   - Record the boundary change in ADR-017 and mark ADR-011/ADR-015 superseded without rewriting
     their historical decisions.
7. **Verification**
   - Run focused unit/component tests, generated-contract drift checks, architecture/model-registry
     validators, Compose configuration validation, secret-pattern review, and the canonical quality
     gate. A real API smoke is optional and must run only when the operator supplies a key.

## Acceptance criteria

- No active runtime, Compose service, volume, dependency, or developer command requires Ollama.
- AI-mode uses OpenAI's Responses API and defaults to the Luna-implementer/Terra-reviewer
  `remote-standard.v1` routing profile.
- Missing/invalid credentials are reported without exposing the key or provider response bodies.
- The default Compose model has no model server and passes configuration validation without a
  committed secret.
- Deterministic tests require neither internet nor OpenAI credentials.
- Generated contracts, type checking, formatting, lint, architecture checks, and coverage pass.
- Active documentation contains a complete local/Compose setup and an explicit live smoke path.

## Compatibility and non-goals

- Existing persisted runs remain readable because model profile is stored as a string; new runs
  using removed local profiles are rejected.
- No prompt rewrite is planned: current prompts already express schemas, authorization boundaries,
  success criteria, and stopping rules. Prompt changes require representative evaluation evidence.
- This migration does not enable OpenAI-hosted tools, server-side conversation state, persisted
  reasoning, Pro mode, explicit prompt caching, MCP, RAG, or multi-agent behavior.
- Historical point-in-time reports and review records are not rewritten. Their Ollama references
  remain evidence of the prior architecture.
- Live output quality/cost/latency validation remains operator-owned because it requires a funded
  API project and secret. The repository supplies the safe diagnostic but never fabricates or
  stores credentials.
