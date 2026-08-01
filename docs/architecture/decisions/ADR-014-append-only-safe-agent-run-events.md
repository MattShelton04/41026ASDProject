# ADR-014: Use append-only safe agent-run progress events

- **Status:** Accepted
- **Date:** 1 August 2026
- **Owners:** Shared platform maintainers
- **Related design:** `docs/architecture/shared-platform-design.md`

## Context

Clients need to reconnect to a running agent workflow without losing or duplicating
semantic progress. Run versions alone identify snapshot changes but do not preserve
every durable phase boundary, and replaying full step records would expose more data
than a progress surface needs.

AI-mode already owns a single SQLite workflow store and atomically persists run, step,
and review changes. Adding a second event service or broker would create unnecessary
operational state for the Release 0 scale.

## Decision

AI-mode schema version 2 adds a small append-only `run_events` table. Every successful
run creation or versioned state transaction appends one bounded `AgentRunEvent` in the
same SQLite transaction. Events contain only identifiers, status, phase, timestamps,
and optimistic run version; they contain no prompt text, tool arguments, outputs,
response bodies, secrets, or hidden reasoning.

`GET /api/v1/agent-runs/{id}/events` returns an ordered bounded JSON page. Clients
resume with the exclusive `after` query cursor or `Last-Event-ID`; `next_cursor` is the
last returned event ID. This is deliberate cursor polling rather than a long-lived SSE
connection. It satisfies reconnect semantics while avoiding a worker-blocking stream
in the initial concurrency-one Flask/SQLite deployment.

## Consequences

- Reconnects are deterministic: event IDs are monotonically increasing and an
  exclusive cursor prevents semantic duplicates.
- Event creation cannot diverge from workflow state because both commit atomically.
- The API remains bounded and disconnects cannot cancel or occupy the worker.
- Existing schema-version-1 runs migrate safely but have no synthetic historical
  events; new changes after migration are captured.
- A later SSE adapter may stream the same records without changing the persistence
  source of truth or public event contract.
- Event retention must be defined alongside run retention before production use.

## Alternatives considered

- **Derive events from current run/step snapshots.** Rejected because overwritten step
  updates and run versions cannot reproduce every durable boundary.
- **Introduce Redis, a broker, or event sourcing.** Rejected as excessive for the
  single-worker semester deployment and as a second source of workflow truth.
- **Hold an in-process SSE stream.** Rejected for Release 0 because it complicates
  shutdown/reconnect behavior without improving durable semantics.
