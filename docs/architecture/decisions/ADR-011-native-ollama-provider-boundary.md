# ADR-011: Access Ollama through a provider port and native API adapter

- Status: Proposed for team approval; implemented as the Release 0 baseline
- Date: 1 August 2026
- Owner: Shared platform team
- Supersedes: None

## Context

The course guide supplies an OpenAI-compatible `/v1` URL, while the platform design
requires JSON Schema output, tool-call evolution, model residency, and Ollama's detailed
load/prompt/generation timings. Feature code must not depend directly on Ollama.

## Decision

Define a provider-neutral structured-generation/health port in `agent-core`. Implement
it in `ai-mode` using Ollama's native `/api/chat` and `/api/tags` endpoints. Select a
logical model profile rather than a model name in feature code. Use bounded HTTP
timeouts and response sizes, non-streaming schema-constrained JSON, `keep_alive`, typed
transport failures, and non-throwing health results.

Accept a configured `/v1` suffix for compatibility with the course guide, but normalize
it to the native API root. Real-model tests remain separate from deterministic CI.

## Alternatives considered

- Direct feature-to-Ollama calls were rejected because they duplicate policy and make
  provider changes invasive.
- The OpenAI-compatible API was not used inside AI-mode because it does not expose all
  Ollama-specific metrics and controls required by the design.
- A provider SDK in `agent-core` was rejected to keep the core framework-independent.

## Consequences

Ollama behavior is isolated and mockable, with richer evidence metadata. The native API
adapter requires explicit compatibility tests when Ollama changes. Model availability is
reported as degraded readiness rather than making deterministic application behavior
unavailable.
