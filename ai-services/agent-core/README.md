# agent-core

Framework-independent orchestration policy for the shared Agentic AI harness. This
package performs no Flask, SQLite, filesystem, or network I/O.

## Implemented foundation

- strict Plan, Act, Observe, Adapt and human-review contracts;
- explicit legal run transitions with terminal-state invariants;
- iteration, tool-call, model-repair, and wall-time limits;
- immutable, version-encoded, feature-scoped tool registry with JSON Schema
  input/output validation and explicitly approved shared tools;
- an explicit persisted trusted-identifier ledger, with feature-owned JSON Schema
  metadata for identifiers discovered through tool results;
- side-effect, approval, external-effect, and idempotency policy;
- provider, prompt, tool, persistence, queue, clock, and ID ports;
- bounded structured-output validation with at most one repair;
- a persisted phase runner that records state before and after model/tool effects; and
- deterministic cancellation and protected-action review policies; and
- effect-aware restart recovery for model, read-only batches, and uncertain mutation work.

The runner executes each plan stage in deterministic order. Independent `read_only`
actions sharing a sequence are dispatched concurrently up to `max_parallel_tools`; mutations
remain single-action stages. It persists `acting` and every ordered call before dispatching the
stage, then persists every ordered result before observation. A protected action becomes
`review_required`; approval resumes the original call and idempotency key rather than
constructing a new mutation.

See [`docs/architecture/agent-run-state-machine.md`](../../docs/architecture/agent-run-state-machine.md)
for the normative transitions, durable checkpoints, recovery matrix, and feature-tool
idempotency obligations.

## Boundaries

Feature services do not import this package. They call `ai-mode` over HTTP and own the
business rules behind their tool endpoints. `agent-core` does not know student entities,
URLs, Flask routes, provider-specific details, or database implementations.

Objective prose is untrusted intent and is never an identifier-provenance source. A feature
backend supplies already validated identifiers through `trusted_identifiers`; later identifiers
come from successful tool output. Feature-owned schemas may declare `x-identifier-kind` to map
aliases or bare `id` fields to a domain-neutral kind. Exact `_id` and `_ref` field names are the
fallback; an unannotated bare `id` is deliberately ambiguous and cannot authorize a later call.
The `x-*` annotation is orchestration metadata only: it does not change JSON Schema validation or
the feature tool's HTTP payload contract, so adding or correcting it does not require a tool API
version bump. Enforcement and bounded prompt projection share one domain-neutral schema traversal
so their interpretation cannot drift; feature-specific identifier kinds remain in feature-owned
tool schemas.

Release 1 MCP/RAG adapters and Release 2 role separation must reuse these contracts and
the same run model. Their runtime behavior is intentionally not implemented or enabled
here.

## Verification

The deterministic suite covers legal/illegal state transitions, schema repair, unknown
or malformed tools, policy review, idempotent approval, cancellation, tool failure,
executor exceptions, phase interruptions, complete four-phase success, atomic rollback,
and loop limits. Run it with:

```text
uv run pytest ai-services/agent-core/tests
```
