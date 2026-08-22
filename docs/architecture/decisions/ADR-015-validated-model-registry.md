# ADR-015: Select local models through a validated logical-profile registry

- Status: Superseded in part by ADR-017 on 21 August 2026; logical profiles remain accepted
- Date: 1 August 2026
- Owner: Shared platform
- Supersedes: none

## Context

The assignment permits any supported Qwen, Llama, or DeepSeek version through Ollama.
The original AI-mode composition mapped only `local-small.v1` to one environment-supplied
tag. That allowed arbitrary tags, did not convey model capacity, ignored the run's
profile for all but one mapping, and left context allocation implicit.

Concrete model names and advertised context windows can change independently from the
stable names used by feature clients. Loading every supported model for readiness would
also make the low-resource Release 0 path unnecessarily expensive.

## Decision

Use a strict, versioned registry as the source of truth for supported concrete models
and logical runtime profiles.

- The registry accepts only the assignment-approved Qwen, Llama, and DeepSeek families.
- Model entries record the exact Ollama tag, parameter/download size, advertised maximum
  context, and an official source URL.
- Profiles bind a stable key to one model plus bounded `num_ctx`, output-token, role, and
  keep-alive settings.
- AI-mode rejects unregistered profile requests before persisting a run.
- Ollama readiness requires only the configured default profile. Other registered
  profiles are available on demand after their model is pulled.
- The bundled registry is validated in the canonical check. A replacement is selected
  with `AI_MODE_MODEL_REGISTRY_PATH`; the default profile is selected with
  `AI_MODE_DEFAULT_MODEL_PROFILE`.
- The initial task-demonstration default is Qwen 2.5 3B. Smaller Qwen profiles remain
  available for smoke checks or constrained machines without being represented as
  equally reliable planners.
- Advertised model maxima are evidence, not runtime defaults. Operational contexts stay
  conservative until representative team hardware benchmarks justify changing them.

## Consequences

Configuration becomes reviewable, deterministic, and discoverable through
`GET /api/v1/model-profiles`. Logical client contracts no longer depend on a model tag.
Adding a supported version requires one validated registry change rather than code
changes.

Compose still needs to pull the concrete tag corresponding to the selected default
profile. Optional profiles consume disk and memory only when a developer explicitly
pulls and selects them. A custom registry is intentionally manual source configuration,
whereas its JSON Schema and the AI-mode OpenAPI document remain generated artefacts.

## Alternatives considered

- **Arbitrary `OLLAMA_MODEL` override:** simple, but bypasses assignment-family and
  capacity validation.
- **Hard-coded Python mappings:** type-safe but makes operational configuration require
  a code release.
- **Require all registered models at readiness:** reproducible but unsuitable for
  resource-constrained student machines.
