# ADR-031: Carry bounded explicit assistant history without durable conversation state

- Status: accepted
- Date: 2026-08-29
- Owners: shared platform team and PropertyScope Feature 1
- Scope: shared AI-mode prompt contracts and the Feature 1 conversational assistant

## Context

The implemented chat interface displayed several independent agent runs as a transcript, but every
message reached AI-mode as an isolated objective. Follow-up language such as “compare that release”
therefore lost the visible context. AI-mode deliberately does not use provider-owned conversation
state, and the product has not yet defined user identity, durable conversation retention, deletion,
or cross-device access.

Introducing an AI-mode-owned `Conversation` aggregate would solve those wider requirements, but it
would also add persistence migrations, authorization, privacy and retention policy, concurrent-turn
semantics, token-selection evidence, and new lifecycle APIs. The current requirement is narrower:
support coherent follow-ups within the open browser view while keeping one immutable `AgentRun` per
message and preserving the existing workflow API.

The existing 4,000-character run objective limit was also too small for this approach. Feature 1's
fixed conversational policy consumes about 1,700 characters before the current question; a maximum
2,000-character question left almost no room for prior exchanges.

## Decision

1. Feature 1 accepts an optional `history` array containing at most eight messages: four complete
   user/assistant exchanges. Messages must alternate user then assistant, contain no extra fields,
   have at most 2,000 characters each, and have at most 8,000 characters in aggregate.
2. The browser sends only completed visible exchanges. Active, failed and cancelled turns are not
   conversational history. The current message still creates one independent durable `AgentRun`.
3. History is serialized into the objective as explicitly browser-supplied, possibly incomplete or
   altered task data. It may resolve ordinary conversational wording, but it is never factual
   evidence, authorization, approval, or a way to widen the persisted tool allowlist. Material
   claims must be grounded again through current-run allowlisted tools.
4. The shared `AgentRun` objective bound increases from 4,000 to 16,000 characters. Prompt input
   retains its separate 90,000-character bound, and Feature 1's tighter history limits prevent this
   change from becoming an unbounded context channel.
5. `default.v5` adds domain-neutral instructions to treat prior conversation as untrusted, state an
   unsupported capability plainly, avoid claiming the unavailable task occurred, and offer a safe
   supported alternative. Feature 1 chat selects v5. Existing Data review runs remain on v4, and
   immutable v1-v4 assets remain available for replay.
6. Feature context remains typed and explicit. Only canonical release, data-update, and property
   detail routes paired with their one corresponding UUID are accepted. The capability guide
   publishes these options for the feature-owned selector UI.

## Consequences

- Follow-ups work in the current browser session without provider-managed memory or a second source
  of workflow truth.
- Refreshing the page, opening another device, or clearing the view still loses the conversational
  grouping. This limitation must remain visible; run evidence itself remains durable by run ID.
- A browser can alter its submitted history. Re-grounding claims and retaining execution-time tool
  policy makes that a context-quality risk rather than an authorization boundary.
- Repeating prior text increases prompt tokens and may repeat read-only tool calls. Four exchanges
  and the aggregate character ceiling bound that cost.
- History may contain user-entered or model-displayed personal information. It is persisted inside
  the run objective under the existing run retention posture; secrets and sensitive personal data
  must not be entered. A future authenticated conversation design needs explicit retention and
  deletion controls.

## Durable conversations deferred

AI-mode-owned `Conversation` and immutable `Turn` contracts remain the appropriate later design for
cross-refresh history, cross-device access, server-enforced one-active-turn semantics, or auditable
selection of prior turns. That change requires a separate ADR covering identity, authorization,
retention/deletion, conversation revisioning, concurrency, deterministic truncation evidence, and
cross-feature isolation. Client-supplied history must not be relabelled as durable server memory.

## Alternatives considered

- **Provider conversation/session state:** rejected because it weakens local reproducibility,
  provider portability and the existing `store: false` privacy boundary.
- **Trust arbitrary browser history as evidence:** rejected because a caller can alter it and it
  bypasses feature-owned source contracts.
- **Persist a full Conversation aggregate now:** deferred because the requested session follow-up
  behavior does not yet justify unresolved identity, retention and lifecycle semantics.
- **Concatenate an unlimited transcript:** rejected because it creates uncontrolled token cost,
  prompt injection surface and ambiguous stale context.
