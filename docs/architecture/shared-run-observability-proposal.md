# Shared agent-run observability and operations interface proposal

## Document control

| Field | Value |
|---|---|
| Status | Release 0 local read-only operations baseline implemented; remote controls remain proposed |
| Date | 2 August 2026 |
| Scope | Shared run discovery, live progress, traceability, audit evidence, and conversation grouping |
| Primary audience | Shared-platform maintainers, feature owners, reviewers, and demonstrators |
| Related design | [Shared platform design](shared-platform-design.md), [agent run state machine](agent-run-state-machine.md), and [ADR-014](decisions/ADR-014-append-only-safe-agent-run-events.md) |

The concrete Release 0 contracts, query/persistence work, UI structure, security gates,
test matrix, and delivery milestones are defined in the
[AI-mode operations interface implementation plan](../release-0/ai-mode-operations-interface-plan.md).

## 1. Executive recommendation

Add a small operations interface as a read-oriented projection over AI-mode's existing
workflow store. AI-mode must remain the only owner of agent-run state. The interface
should first use the existing resumable cursor-polling API, present safe typed phase
artifacts as a conversation and timeline, and keep detailed evidence behind stronger
authorization. It must not introduce a second workflow database, expose application
logs as agent events, or store hidden model reasoning.

The recommended delivery order is:

1. agree on access, retention, and conversation semantics;
2. add structured correlation-aware logging and a bounded run-list read API;
3. add the operations UI using snapshot plus cursor polling;
4. add an optional SSE adapter only if measured polling load or demo usability warrants it;
5. add durable conversations only if the approved product requires cross-turn context.

This supplies useful Release 0 debugging and evidence without prematurely building a
general monitoring platform or Release 2 multi-agent control plane.

## 2. Current implemented capability

The following findings describe the repository on 2 August 2026.

### 2.1 Durable workflow and audit records

- Each `AgentRun` is an independently identified, bounded objective with its feature,
  prompt set, model profile, limits, status, counters, optimistic version, timestamps,
  final result, and safe error.
- Ordered `AgentStep` records persist Plan, Act, Observe, and Adapt inputs and outputs.
  They include typed plans, tool calls/results, observations, adaptations, and concise
  model-invocation metadata such as provider, model, prompt hashes, token counts, and
  durations. Raw provider request bodies, raw model responses, exception traces, and
  hidden chain-of-thought are intentionally not audit records.
- Human reviews are immutable records tied to one run, step, and exact protected tool
  call. Effectful calls have stable call identifiers and idempotency keys.
- SQLite is the single workflow owner. Run, step or review state and the corresponding
  progress event commit in one transaction. Optimistic versions prevent stale workers
  from overwriting newer state.
- Startup and idle reconciliation discover non-terminal, non-review-blocked runs from
  durable state. The in-memory queue is only a wake-up optimization.

This is a strong application audit trail for a semester-scale system. It is not yet a
tamper-evident or compliance-grade audit log: the database owner can alter or delete
rows, no retention rule is enforced, and no signed evidence export exists.

### 2.2 Progress and evidence surfaces

| Surface | Current behavior | Boundary |
|---|---|---|
| `GET /api/v1/agent-runs/{id}` | Returns the current safe run snapshot, ordered steps, and reviews | Requires the caller to already know the run ID |
| `GET /api/v1/agent-runs` | Flagged, filtered stable-cursor page of compact run summaries | Absent unless the local operations feature is enabled |
| `GET /api/v1/agent-runs/{id}/events` | Returns up to 200 ordered events after an exclusive `after` or `Last-Event-ID` cursor | Events deliberately contain state metadata, not arguments, outputs, or logs |
| `GET /api/v1/operations/agent-runs/{id}` | Flagged allowlisted evidence projection with nested redaction and weak ETag | Local trusted use; remote authorization remains undecided |
| `POST .../{id}/cancel` | Records cancellation intent idempotently | There is no operations-oriented permission model yet |
| `POST .../{id}/reviews` | Records an exact approve/reject decision | Production reviewer identity and authentication remain undecided |
| `/development/agent-runs/{id}` | Optional bearer-token HTML view of the persisted detail | Raw JSON presentation; development-only; absent unless configured |
| `/operations/ai-mode/` | Read-only run browser, phase evidence, model/tool metrics, cursor journal, and correlation view | Absent unless `AI_MODE_OPERATIONS_ENABLED=true` |

Progress events contain event ID, run ID and version, event type, status, timestamp,
and optional step identity/phase/status. Their database-global monotonically increasing
IDs and exclusive cursor give deterministic reconnect behavior. Version-1 databases
migrate forward but do not receive invented historical events.

The operations projection applies depth/property/item/string bounds, sensitive-key
redaction, and conservative common credential-pattern redaction in free text. The browser
uses `textContent` and a restrictive content-security policy. These are useful safeguards,
not a production data-loss-prevention boundary; feature owners must still decide what data
may be persisted and which fields require stronger feature-specific policy.

### 2.3 Correlation and logging

The current conventions provide a useful structured baseline but remain incomplete:

- AI-mode accepts or creates `X-Request-ID` and returns it on every response.
- Agent API responses include `X-Agent-Run-ID`.
- A valid W3C version-00 `traceparent` supplied when the run is created is persisted on
  the run and forwarded with `X-Request-ID` and `X-Agent-Run-ID` to feature tools.
- Tool calls and persisted steps provide run, step, and call identifiers that can join
  orchestration evidence to feature-owned operation records.
- AI-mode configures one-line JSON stdout logs with a stable allowlisted schema for HTTP
  completion, worker boundaries, model completion, tool completion, and failures.
- Log records carry applicable request, run, step, tool-call, trace, feature, outcome,
  duration, model/token, and safe error-code fields. Prompts, tool arguments/results,
  authorization headers, response bodies, and arbitrary logging extras are excluded.

Feature services do not yet share the JSON logging implementation because their runtime
and language conventions have not been selected. AI-mode also does not create a trace when
none is supplied, create child spans for model/tool calls, configure an OpenTelemetry
exporter, or expose a log query endpoint. Re-forwarding one `traceparent` preserves a
correlation hint but is not the same as constructing a valid distributed span tree.
Consequently, local operators can reliably filter AI-mode stdout by run ID, but they cannot
yet enter a run ID and retrieve every exact application log across all services.

### 2.4 Multiple runs versus conversations

The core supports many persisted runs and can recover them independently. The current
worker deliberately executes one run at a time, so accepted runs may queue while
another model/tool loop is active. This is multiple-run support, not conversation
support.

There is currently no `conversation_id`, thread aggregate, ordered user/assistant
turns, parent-run relation, actor or tenant identity, conversation list, or explicit
selection of prior turns as model context. Each `POST /agent-runs` starts one isolated
objective. The short repair exchange inside one model invocation preserves validation
causality, but it is not a durable end-user conversation.

## 3. Required conceptual separation

The interface should keep three information classes separate even when one page links
them together:

| Class | Purpose | Typical content | Access and retention posture |
|---|---|---|---|
| Safe progress | Reconnectable client status | IDs, status, phase, timestamps, terminal flag | Broadest authorized audience; compact and longer-lived |
| Run evidence | Explain and reproduce an agent decision | Objective, typed plans/actions/results, reviews, model and prompt metadata | Restricted; field-level redaction and bounded retention |
| Operational telemetry | Diagnose service and dependency behavior | Structured logs, traces, spans, exceptions, resource metrics | Operator-only; stored in a telemetry backend, not the workflow API |

An append-only progress event must not become a convenient envelope for raw tool
responses or logs. That would weaken the event contract, duplicate larger evidence,
and expose feature data to every progress consumer.

## 4. Proposed read model and APIs

### 4.1 Ownership

AI-mode should derive every run read model from its owned SQLite state. A shared edge
may proxy authenticated routes and serve the UI, but it must not open the SQLite file.
Feature services may link their domain records or operation-status resources through
safe evidence references; AI-mode must not query their databases.

The first implementation can use indexed snapshot queries. A separately persisted
CQRS projection or event broker is unnecessary at current scale. Introduce one only
after measurements show that read traffic interferes with the single SQLite owner.

### 4.2 Bounded operations API

Add a versioned, authenticated run-summary endpoint, conceptually:

```text
GET /api/v1/agent-runs
    ?status=queued,planning,review_required
    &feature_key=...
    &created_after=...
    &updated_before=...
    &cursor=...
    &limit=50
```

The response should contain opaque pagination cursors and a compact `AgentRunSummary`:
run ID, feature key, safe objective preview, status, model profile, iteration/tool-call
counts, created/updated timestamps, elapsed or terminal duration, review-needed flag,
and error code. Stable sorting should use `(updated_at, id)` or `(created_at, id)`.
Maximum page size and filter combinations must be bounded.

Keep the current detail and event endpoints as the authoritative per-run surfaces.
If a dedicated evidence endpoint is added, it should return an explicitly allowlisted
and versioned projection rather than serialize internal persistence models by default.
Cancellation and review remain commands over HTTP; they do not belong in SSE or a
WebSocket message protocol.

Do not add an API that returns application log text. Instead, return correlation keys
and, where deployment configuration supplies one, an operator-only link to the log or
trace backend's filtered view.

### 4.3 Snapshot and event consistency

Clients should use this sequence:

1. load a run detail snapshot and record its `run.version`;
2. load events after the last stored event cursor;
3. render events as progress hints and refresh the detail when an event arrives;
4. stop polling only when `terminal` is true and the final detail has been refreshed;
5. retain the cursor and resume after navigation or transient disconnect.

The detail snapshot remains the current source of truth; events signal durable changes
and reconnect position. Clients must tolerate duplicate HTTP responses, an empty page,
and a run version newer than the last rendered event.

## 5. Live transport decision

| Option | Strengths | Costs and risks | Recommendation |
|---|---|---|---|
| Cursor polling | Already implemented; durable reconnect; easy through Flask/Nginx; bounded connections | Small latency and repeated requests | Use first, with 0.5-2 second active polling and slower backoff for idle/review runs |
| Server-Sent Events | Natural server-to-browser stream; `Last-Event-ID` fits the existing cursor | Long-lived worker/proxy connections, heartbeats, shutdown and backpressure work | Optional later adapter over the same stored events; measure before adopting |
| WebSocket | Bidirectional and low latency | New protocol for auth, reconnect, ordering, commands, proxies, and tests | Do not use for Release 0; commands already work safely over HTTP |

If SSE is introduced, it must read the same durable event table, accept the same
exclusive cursor, send only `AgentRunEvent`, emit heartbeats without inventing workflow
events, and fall back to polling. Disconnecting a viewer must never cancel a run.

## 6. Conversation semantics if approved

Do not relabel a run as a conversation. Preserve these definitions:

- **Run:** one bounded, immutable objective attempt with a terminal result or error.
- **Conversation:** an ordered container of user turns and associated runs.
- **Display message:** a UI projection of typed run artifacts; not necessarily a raw
  provider message and never hidden reasoning.
- **Multi-agent role:** a later-release execution role within a run; not a conversation.

If cross-turn product behavior is required, add an explicit AI-mode-owned
`Conversation` aggregate and immutable turns. A new run may reference a conversation
revision and a bounded, explicit set of prior safe turns. It must never silently load
all history. Recommended invariants are one feature key per conversation, at most one
active run per conversation, many conversations across the system, deterministic
context truncation recorded as evidence, and terminal runs remaining immutable.

The team must decide whether conversations are merely UI grouping or whether previous
turns affect model input. The latter changes contracts, privacy, deletion, token
budgeting, evaluation, and persistence, and therefore requires an ADR and migration.
Until that decision, the integration UI may keep several run IDs in browser storage
and present independent chat cards without claiming durable conversations.

The current concurrency-one worker can safely hold multiple queued conversations, but
latency grows with the global queue. Parallel workers require provider-capacity
measurement and stronger SQLite claim/lease semantics; a wider thread pool alone is
not a safe concurrency design.

## 7. Correlation and telemetry design

### 7.1 Identifier responsibilities

| Identifier | Responsibility |
|---|---|
| Request ID | One ingress request and its immediate dependency calls; useful to support users and join HTTP errors |
| Run ID | Stable identity across the complete bounded agent workflow and all feature tool calls |
| Step ID | One durable Plan, Act, Observe, or Adapt attempt |
| Tool call ID | One exact tool operation, reused during effect-aware recovery |
| Conversation ID | Optional future grouping across user turns; must not replace run ID |
| Trace/span IDs | Distributed execution causality created and propagated by telemetry middleware |

Adopt OpenTelemetry API instrumentation behind optional exporters. Middleware should
create a trace when inbound context is absent, create child spans for HTTP requests,
queue delay, model calls, persistence operations, and tool calls, and propagate a new
child context downstream. `X-Request-ID` and `X-Agent-Run-ID` remain stable application
correlation fields and should also be span attributes.

### 7.2 Structured log baseline

Every service should emit one-line JSON to stdout with a stable schema containing:

```text
timestamp, level, service, environment, event, message,
request_id, run_id, step_id, tool_call_id, trace_id, span_id,
feature_key, outcome, duration_ms, error_code
```

Fields may be null when genuinely unavailable. Use named events such as
`agent.run.accepted`, `agent.phase.completed`, `agent.tool.completed`, and
`agent.run.terminal`; do not parse human message strings as contracts. Logging filters
or context variables should attach correlation metadata consistently to request and
worker threads. Raw prompts, authorization headers, cookies, tool arguments/results,
personal data, and provider response bodies should be denied by default.

Local operators can then filter Compose output by `run_id`. An optional observability
profile may send stdout/OpenTelemetry data to a collector and trace viewer; Azure may
use its managed telemetry backend later. The UI should show a configured deep link,
not couple its data model to a particular vendor.

### 7.3 Caching and multi-turn latency

The current runtime already avoids some repeated work: Ollama `keep_alive` keeps model
weights resident, prompt templates are validated and cached in-process, model and tool
registries load once at startup, and HTTP clients reuse connection pools. These are
runtime optimisations, not durable conversation caching. Every structured generation
still sends its bounded messages, and the platform does not promise reusable provider
KV state across separate `/api/chat` requests.

If durable conversations are approved, optimise only after measuring prompt evaluation,
generation, queue, and tool timings separately. A safe conversation-context cache key
would need at least the conversation revision, selected turn range and truncation
policy, prompt version/hash, model profile and resolved digest, tool-catalog versions,
and any feature-data revision that affects grounded context. Persist the chosen context
revision as evidence so a cache hit does not make a run irreproducible.

Do not add a generic model-response or tool-result cache. Reads require feature-owned
freshness/version rules; writes and approval decisions must never be replayed from a
semantic cache. Provider-side prefix or session reuse may be adopted behind the
provider port only when its invalidation and isolation behavior is a documented,
tested runtime contract. Cache hit rate, saved prompt tokens/time, invalidations, and
staleness failures then belong in telemetry, not in the safe progress event payload.

## 8. Operations UI information architecture

### 8.1 Run index

The landing view should prioritize work that needs attention:

- active count and oldest queued duration;
- review-required runs;
- recently failed and recently completed runs;
- filters for status, feature, model, and time range;
- clear paused/disconnected/stale indicators; and
- links using copyable run, request, and trace identifiers.

An "ongoing" run should mean its persisted status is non-terminal, not merely that a
browser connection exists. A stale warning can compare `updated_at` with a configured
threshold, but must not invent a failed status.

### 8.2 Run detail

Use complementary projections of the same safe contracts:

1. **Conversation:** user objective; assistant plan summary; tool-call cards; observation
   facts; adaptation/final response. Label generated, deterministic, tool, and human
   artifacts distinctly so the page never suggests that all cards are model speech.
2. **Timeline:** durable phase/status sequence with start/end time and duration.
3. **Actions:** tool name/version, side-effect and approval state, bounded safe input
   summary, outcome, duration, retryability, and evidence links.
4. **Run controls:** cancel and exact approve/reject controls shown only when authorized
   and valid for the current state; require explicit confirmation for protected actions.
5. **Evidence:** model/profile, prompt ID/version/hash, input hash, token/timing metrics,
   limits/counters, reviews, and final error/result.
6. **Correlation:** request, run, step, call and trace identifiers, plus configured log
   and trace links.
7. **Raw contract view:** escaped, redacted JSON as a secondary diagnostic—not the
   primary experience.

This conversation projection is appropriate for the integration-test feature and
future shared operations UI. It should render persisted facts only; it must not invent
natural-language explanations or expose private reasoning to make the trace look more
chat-like.

## 9. Retention, redaction, access, and security

Before exposing a run index, agree and test these policies:

- authenticate every operations and evidence route; authorize by operator role and,
  once identity exists, feature/team scope;
- do not accept a caller-supplied reviewer name as sufficient production identity;
- use deny-by-default evidence projections and schema-level sensitivity annotations
  for feature fields; redact before persistence where a value is never needed again;
- bound objectives, summaries, evidence references, events, and exported artifacts;
- define separate retention periods for workflow state, safe events, detailed evidence,
  operational logs/traces, and release snapshots;
- cascade or tombstone deletion consistently across runs, steps, reviews, events,
  conversations, and telemetry indexes;
- record authorized view/export/cancel/review actions without logging secrets;
- prevent objectives or tool output from becoming unescaped HTML, log templates,
  metric labels, or trace attribute explosions;
- apply rate limits and maximum page windows to listing, polling, evidence export, and
  telemetry links; and
- keep the development bearer-token page disabled in production rather than treating
  one shared token as operator identity.

For assessment evidence, generate a redacted manifest tied to a commit, scenario,
model/profile, prompt hashes, run IDs, and artifact checksums. Do not copy the live
SQLite database or unrestricted logs into a report bundle.

## 10. Phased delivery

### Phase 0: decisions and acceptance scenarios

- Decide identity/authorization, retention, redaction ownership, and whether durable
  cross-turn conversations are a product requirement.
- Define representative success, failure, cancellation, review, restart, and long-run
  scenarios using the non-product integration feature.

### Phase 1: trustworthy query and telemetry foundation

- Add the bounded run-summary contract, indexed list query, and authenticated API.
- Introduce stable structured stdout logs and correlation context in AI-mode and the
  integration feature; instrument request, queue, model, and tool boundaries.
- Return or expose a generated trace context while preserving the existing request/run
  headers. Add optional exporters only after the no-exporter baseline works.
- Replace name-only display redaction with an allowlisted evidence projection.

### Phase 2: polling operations interface

- Build the run index and conversation/timeline detail over snapshots and existing
  cursor events.
- Add reconnect, terminal stop, stale-state, cancellation, and review UX.
- Keep raw JSON as an opt-in diagnostic panel and add configured telemetry deep links.

### Phase 3: evaluation and evidence automation

- Exercise multi-action and replan scenarios, protected writes, dependency failures,
  cancellation, queueing, and restart recovery.
- Produce redacted, checksummed release evidence and measure polling load, queue delay,
  end-to-end latency, token use, and event volume.
- Add SSE only if measurements justify it.

### Phase 4: optional durable conversations and scale

- If approved, version contracts and migrate to explicit conversations and immutable
  turns with bounded context selection.
- Benchmark model capacity before changing global execution concurrency. Add durable
  work claiming/leasing before running multiple workers.

## 11. Verification strategy

| Test layer | Required cases |
|---|---|
| Contract | Bounded run summaries, opaque cursors, status filters, safe event compatibility, unauthorized fields absent |
| Persistence | Stable pagination under inserts, atomic event/state commits, migration, retention deletion, startup reconciliation |
| Redaction/security | Nested and free-text secret fixtures, HTML escaping, authorization matrix, identifier enumeration, rate and size limits |
| Logging/tracing | Captured JSON schema, correlation on request/worker/model/tool logs, child context propagation, secrets absent |
| UI/component | Event-to-card projection, duplicate/empty pages, reconnect cursor, stale warning, terminal refresh, review/cancel races |
| Integration | Several queued independent runs, long multi-action run, failure, review, cancellation, service restart, tool idempotency |
| Conversation, if enabled | Turn ordering, one-active-run invariant, explicit context revision, truncation evidence, delete/export behavior |
| Performance | Polling request rate, list-query latency, SQLite contention, event growth, queue delay, optional SSE connection budget |

Deterministic tests should use the scripted model and injected clock. Real Ollama cases
remain tagged evaluation tests and must report the model digest/profile and prompt
hashes because output is probabilistic.

## 12. Decisions requiring team input

1. Is chat history a display convenience, or must prior turns alter future model input?
2. Who may list all runs, view detailed evidence, cancel runs, and approve protected
   actions? Is scope per user, team, feature, or environment?
3. Which eventual feature fields may contain personal, confidential, or regulated data,
   and who owns their schema-level redaction annotations?
4. What retention periods apply to safe progress, detailed workflow state, reviews,
   operational telemetry, and release evidence?
5. Is a local collector/trace viewer acceptable within the team's laptop resource
   budget, and which Azure telemetry backend and cost limit apply later?
6. Does Release 0 require live streaming, or is resumable polling sufficient after UX
   testing?
7. What latency and parallel-run targets justify moving beyond the serial worker?
8. Must exported evidence be tamper-evident, and who is authorized to generate it?

Until these decisions are made, the safe next step is to improve the integration
feature's run projection and exercise longer persisted runs using the existing snapshot
and polling contracts. That work demonstrates current behavior without committing the
platform to durable conversation history, production operator authorization, or a
second observability stack.
