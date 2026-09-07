# Information architecture and journeys

## Navigation model

The product has one identity and two task expressions. Global navigation connects research areas, status/history and the assistant. Contextual navigation exposes the current workspace’s actual routes. Data operations is clearly discoverable within Property data rather than being mistaken for the default experience of every researcher. AI activity is the audit counterpart of conversation and bounded review.

```mermaid
flowchart TD
  H[PropertyScope home] --> R[Research areas]
  H --> Q[Property search handoff]
  H --> A[Global assistant]
  R --> P[Property data]
  R --> M[Sales and market]
  R --> S[Suburb context]
  R --> D[Site and planning]
  R --> B[Buyer workspace]
  P --> O[Data operations]
  O --> J[Sources / jobs / runs]
  O --> E[Quality / artifacts / releases]
  H --> T[Data status / sources and history]
  A --> V[Durable AI activity]
  E --> V
```

The arrows describe available navigation or an explicit workflow entry, not an unimplemented shared-property entity model. Feature-specific selected entities remain owned and validated by their services.

## A. Property researcher

Start with an address or reference, open the canonical Property data search, inspect the returned identity and available evidence, then choose the relevant research workspace. Sales cases, suburb comparisons, site reviews and buyer cases have their own saved-state models. Use visible product navigation to move between them; do not imply that creating one automatically creates the others.

```mermaid
flowchart LR
  H[Home address entry] --> P[Property discovery]
  P --> E[Property record and evidence]
  E -. choose workspace .-> M[Recorded sales / market case]
  E -. choose workspace .-> S[Suburb and liveability]
  E -. choose workspace .-> D[Site review]
  M -. record research .-> B[Buyer workspace]
  S -. record research .-> B
  D -. record research .-> B
  E --> A[Ask within an explicit available scope]
  A --> V[Answer / evidence / full activity]
```

Solid arrows represent direct product patterns where supported; dashed arrows are user-led transitions, not automatic context propagation. The researcher’s first question is “What does the evidence actually say?” Date, source, limitations and coverage sit next to the relevant result. Raw lineage and technical IDs are available after that question, not before it.

## B. Data operator

The data overview summarizes updates and published sources. Sources define what may be ingested; jobs provide bounded commands; run detail exposes actual progress and evidence. Quality, artifacts and release views retain their expert density. Candidate review and accepted publication remain different states.

```mermaid
flowchart LR
  O[Data overview] --> S[Source / job]
  S --> P[Preview update]
  P --> C[Explicit confirmation]
  C --> R[Run detail]
  R --> Q[Quality / artifacts / lineage]
  Q --> K[Candidate release]
  K --> A[Optional bounded AI review]
  A --> H[Human review]
  K --> H
  H --> X[Accepted or rejected decision]
```

The UI does not publish because a model produced a positive answer. Review context and comments stay with the actual candidate. Browser testing of the command/confirmation interface used deterministic fixtures only; it is not evidence that a real release was persisted or accepted by the backend.

## C. AI and audit

```mermaid
sequenceDiagram
  actor U as User
  participant UI as Scoped browser UI
  participant F as Owning feature backend
  participant A as AI-mode / durable runner
  participant T as Allowlisted feature tools
  U->>UI: Question with explicit scope/context
  UI->>F: Submit a turn once
  F->>A: Create durable bounded run
  A->>T: Authorized tool request
  T-->>A: Recorded result and evidence
  UI->>F: Poll recorded run state
  F-->>UI: Public phase, result, evidence or failure
  UI-->>U: Answer + limitations + activity link
  U->>UI: Open full activity or prepare another question
```

This is the existing trust model, not a new direct browser-to-model channel. The browser does not gain tools merely by selecting a scope. Conversation history supports continuity, not authorization or evidence. The full activity view exposes recorded activity, not private model reasoning.

## Returning without losing context

The assistant’s submitted context is snapshotted per turn. Feature 1’s activity links are built by a small pure helper that respects integrated and standalone paths. Activity return paths are validated against known internal destinations. A buyer summary is not linked as though its local workflow ID were an agent-run ID. Unknown/external return destinations do not become an open redirect.

Mobile navigation has both a way forward and a way back. The global and feature menus remain distinguishable. Activity list/detail navigation retains a visible title and return control. Native dialog cancellation restores the originating control rather than leaving focus behind an overlay.
