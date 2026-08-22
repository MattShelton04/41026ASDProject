# ADR-011: Access Ollama through a provider port and native API adapter

- Status: Superseded by ADR-017 on 21 August 2026
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
it to the native API root. Support native-host development and a pinned Compose-managed
runtime; use the latter for integration and release evidence. Real-model tests remain a
separate explicitly requested CI job rather than part of deterministic CI.

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
unavailable. The Compose model uses a persistent model volume and one-shot initializer,
while an installed provider-level diagnostic provides machine-readable structured
generation evidence without duplicating Compose lifecycle behavior. Provider
construction and logical profile selection have one shared composition function.
Readiness remains degraded-but-serving by default; deployments that require a loaded
model, including the integrated Compose profile, explicitly enable strict readiness.
