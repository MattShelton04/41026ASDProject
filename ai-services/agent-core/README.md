# agent-core

Framework-independent orchestration policy for the shared Agentic AI harness. This
package performs no Flask, SQLite, filesystem, or network I/O.

## Implemented foundation

- strict Plan, Act, Observe, Adapt and human-review contracts;
- explicit legal run transitions with terminal-state invariants;
- iteration, tool-call, model-repair, and wall-time limits;
- immutable allowlisted tool registry with JSON Schema input/output validation;
- side-effect, approval, external-effect, and idempotency policy;
- provider, prompt, tool, persistence, queue, clock, and ID ports;
- bounded structured-output validation with at most one repair;
- a persisted phase runner that records state before and after model/tool effects; and
- deterministic cancellation and protected-action review policies.

The runner executes one action at a time. It persists `acting` before dispatching a
tool and persists the result before observation. A protected action becomes
`review_required`; approval resumes the original call and idempotency key rather than
constructing a new mutation.

## Boundaries

Feature services do not import this package. They call `ai-mode` over HTTP and own the
business rules behind their tool endpoints. `agent-core` does not know student entities,
URLs, Flask routes, Ollama details, or database implementations.

Release 1 MCP/RAG adapters and Release 2 role separation must reuse these contracts and
the same run model. Their runtime behavior is intentionally not implemented or enabled
here.

## Verification

The deterministic suite covers legal/illegal state transitions, schema repair, unknown
or malformed tools, policy review, idempotent approval, cancellation, tool failure,
complete four-phase success, and loop limits. Run it with:

```text
uv run pytest ai-services/agent-core/tests
```
