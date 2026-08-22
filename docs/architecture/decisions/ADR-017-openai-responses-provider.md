# ADR-017: Use the OpenAI Responses API as the default model provider

- Status: Accepted and implemented
- Date: 21 August 2026
- Owner: Shared platform
- Supersedes: ADR-011 and the Ollama-specific portions of ADR-015

## Context

The Release 0 baseline isolated Ollama behind `agent-core`'s `LLMProvider` port, but the
integrated runtime still carries a model server, initializer, persistent model volume,
GPU/CPU branching, model downloads, native-host override, and hardware-dependent inference.
The repository owner requested a remote LLM API architecture with OpenAI as the default provider
and GPT-5.6 Luna as the default high-volume model. The owner subsequently requested a bounded,
low-cost implementer/reviewer split rather than a single model or million-token working context.

The deterministic orchestrator, local workflow-state ownership, allowlisted feature HTTP tools,
human authority, structured output validation, and offline test strategy remain valid and must not
move into provider-specific code.

## Decision

Keep the provider-neutral `LLMProvider` port and replace the production Ollama adapter with an
OpenAI adapter using the Responses API.

- `ai-mode` calls `POST /v1/responses` over HTTPS through the stable logical profile
  `remote-standard.v1`. Planner implementation turns route to cost-sensitive `gpt-5.6-luna`;
  adaptation and reviewer turns route to balanced `gpt-5.6-terra`. This uses both models in the
  current loop when adaptation is needed without enabling the later multi-agent service.
- The adapter uses the official OpenAI Python SDK, requests JSON-Schema-guided output, sets
  `store: false`, uses explicit prompt-prefix caching and `low`
  reasoning effort, enforces a 128K operational context profile plus 16K maximum output/deadline limits,
  conservatively rejects oversized context before dispatch, bounds response bytes, and maps
  transport/provider failures into safe `ModelProviderError` values.
- Provider readiness uses bounded, authenticated, short-lived cached `GET /v1/models/{model}` calls for every distinct
  model routed by the selected profile. A missing
  key is a degraded provider state, not a reason for liveness or deterministic CRUD to fail.
- `OPENAI_API_KEY` is accepted only from server-side runtime configuration. It is never stored in
  source, images, logs, workflow state, evidence projections, or client-visible configuration.
- The model registry becomes provider-neutral metadata and is bumped to schema version 2. It
  records provider, API model ID, advertised capacity, operational budgets, reasoning effort, and
  role-to-model routing rather than local download/residency data.
- The Ollama services, initializer, volume, GPU/native-host Compose overlays, and model-pull
  workflow are removed.
- A live remote-provider diagnostic remains explicit and optional; deterministic CI mocks the
  HTTPS boundary and never requires a credential or network access.
- An alternate base URL is supported when it implements Responses create and Models retrieve.
  Cache extensions can be disabled for compatible implementations. Non-loopback HTTP requires an
  explicit development-only opt-in.

The orchestrator continues to execute feature tools itself. OpenAI hosted tools and server-side
conversation state are not enabled by this decision.

## Consequences

The integrated topology is smaller and independent of developer GPU/RAM capacity, model pulls,
and local inference performance. All environments need outbound HTTPS and a funded OpenAI API
project for live AI operation. Usage is metered, provider availability/rate limits become external
dependencies, and prompts/tool inputs leave the local machine under the API project's data
controls.

Operational safeguards therefore include explicit timeouts, bounded retries, response-size bounds,
application schema validation, `store: false`, safe error messages, runtime-only secrets, request
IDs, and graceful degraded readiness. The Plan contract's dynamic tool-argument map is incompatible
with the provider's closed/all-required strict-schema subset, so API strict mode is false and the
existing application validator plus one repair turn remains authoritative. Teams must evaluate
cost, latency, structured-output success, and task quality on representative runs before making
release claims.

## Alternatives considered

- **Keep Ollama as a fallback:** rejected for this baseline because it retains the topology and
  maintenance burden the migration is intended to remove. Another adapter can be added later
  without changing feature services or `agent-core`.
- **Call OpenAI directly from each feature:** rejected because it duplicates credentials, policy,
  prompting, persistence, and error handling and violates the shared-orchestrator boundary.
- **Use Chat Completions:** rejected because OpenAI recommends Responses for reasoning and agentic
  workflows, and Responses provides the target structured-output request shape.
- **Delegate tools/state to the provider:** rejected because the current deterministic runner and
  persisted phase boundaries are the security, audit, idempotency, and recovery authority.
- **Embed a vendor SDK in `agent-core`:** rejected because the core must remain framework and
  provider independent. The SDK exists only inside AI-mode's concrete adapter.
