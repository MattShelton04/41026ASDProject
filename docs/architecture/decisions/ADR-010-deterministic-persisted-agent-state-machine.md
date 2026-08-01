# ADR-010: Use a deterministic persisted agent state machine

- Status: Proposed for team approval; implemented as the Release 0 baseline
- Date: 1 August 2026
- Owner: Shared platform team
- Supersedes: None

## Context

The assignment requires a visible Plan -> Act -> Observe -> Adapt loop in every release.
Model output is probabilistic, feature tools may cause effects, runs have hard limits,
and Release 2 must add roles without creating an incompatible workflow model.

## Decision

Keep legal state transitions, limits, cancellation, tool schemas, effect authorization,
idempotency, and human approval in framework-independent deterministic code. Persist a
run transition before and after each model or tool effect. Store validated plans,
actions, results, concise observations/adaptations, invocation metadata, and reviews;
do not request or persist hidden reasoning.

Use optimistic run versions. Commit each run change and its associated step/review in
one transaction. A model-format error receives at most one schema-informed repair.

## Alternatives considered

- A prompt-only loop was rejected because prompts cannot enforce authorization,
  idempotency, or bounded execution.
- An in-memory loop was rejected because it cannot provide restart safety or credible
  assessment evidence.
- Event sourcing was rejected as disproportionate for the semester scope.

## Consequences

The core is deterministic and testable without Ollama, and later adapters can reuse the
same records. Persistence and recovery code is more explicit. Startup reconciliation
and uncertain in-flight action handling remain required before Release 0 completion.
