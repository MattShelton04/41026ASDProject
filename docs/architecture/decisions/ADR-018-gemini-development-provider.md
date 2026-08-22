# ADR-018: Support Gemini as an opt-in development provider

- Status: Accepted and implemented
- Date: 22 August 2026
- Owner: Shared platform
- Extends: ADR-017 without changing the production default

## Context

The project keeps OpenAI Responses as its Release 0 default, but developers also need a low-cost
remote provider for local Feature 1 AI evaluation. Google exposes Gemini through an OpenAI SDK
compatibility endpoint and a programmatic Models API. The compatibility endpoint supports Chat
Completions, structured outputs, model list and model retrieve, but not Responses create; changing
only `OPENAI_BASE_URL` would therefore make readiness succeed while generation returned HTTP 404.

## Decision

Keep the provider-neutral `LLMProvider` port and the official OpenAI SDK inside AI-mode. Add an
explicit `gemini` composition that uses the compatible Chat Completions request/response shape
while retaining application-owned orchestration, schema validation, repair, deadlines, response
bounds, tool policy, persistence and evidence.

Gemini's structured-output compatibility rejects the Plan contract's intentionally dynamic tool
argument map. Gemini calls therefore use JSON-object mode with the full schema included in the
system instruction; `agent-core` remains the strict validator and permits the same one bounded
repair turn. OpenAI Responses continues to use provider-side JSON Schema guidance.

- `gemini-development.v1` routes planner turns to `gemini-3.5-flash-lite` and adaptation/review to
  `gemini-3.6-flash`.
- `gemini-quality.v1` routes all roles to `gemini-3.7-flash` for intentional evaluation.
- Both profiles keep the application's conservative 128K context and 16K output ceilings.
- Provider/model mismatch is rejected at composition time.
- Gemini uses `GEMINI_API_KEY` or `GEMINI_API_KEY_FILE`; Compose keeps the credential file-mounted
  and service-scoped.
- The development helper accepts an explicit Git-ignored dotenv file and never includes the direct
  credential in rendered Compose configuration or container environment.
- Live generation probes remain manual evidence, not deterministic CI.

## Consequences

Local developers can test the real agent loop with a free-tier-capable provider without changing
feature code. The adapter has two provider-specific wire formats, so deterministic contract tests
cover both. Gemini compatibility remains beta and does not provide all native Gemini features; the
project does not claim grounding, hosted tools, or provider-managed workflow state through this path.

Gemini 3.7 Flash is materially more expensive than 3.5 Flash-Lite on the paid standard tier, so it
is opt-in rather than the development default. Model availability and pricing can change; update
the registry only after programmatic model discovery, a structured generation probe, documentation
review, and representative Feature 1 evaluation.

## Alternatives considered

- **Base URL switch only:** rejected because Gemini does not implement Responses create.
- **Use the native Google GenAI SDK:** deferred because the compatibility path reuses the existing
  SDK boundary and is sufficient for text-only structured development workloads.
- **Make Gemini the production default:** rejected because ADR-017 and release evidence currently
  specify OpenAI Responses; this decision only adds an opt-in development path.
