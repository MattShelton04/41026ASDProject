# Feature 1 conversational assistant feasibility and Gemini audit

Status: proposal and test evidence, not an implemented product commitment  
Date: 26 August 2026  
Scope: PropertyScope Feature 1 and the shared AI-mode boundary

## Decision summary

A contextual Feature 1 assistant is feasible, but it should not replace or be confused with the
implemented **Data review** workflow. The recommended sequence is:

1. harden AI-mode prompt sizing, interruption recovery and identifier propagation;
2. add a contextual, single-turn Feature 1 assistant using read-only tools;
3. add durable multi-turn conversations only when follow-up questions require server-side context;
4. consider a shared, cross-feature assistant after every feature publishes an owned capability
   manifest and the team agrees on authentication, routing and tool ownership; and
5. consider project/code questions only through a curated, versioned documentation index with
   citations. Do not expose the repository, filesystem or shell to the model.

The current Feature 1 assistant remains a release/run reviewer. It has fixed review objectives,
creates one AI-mode run, displays recorded turn-by-turn evidence, and does not offer general chat.

## What was tested

The local stack was started with `uv run scripts/dev.py stack up --env-file .env.gemini`. The env
file was used by the stack and was not read during this audit. Readiness reported Gemini and the
configured models as ready. The provider smoke check succeeded with `gemini-3.5-flash-lite`.

The retained local Feature 1 data includes complete acquisition candidates for:

- NSW Property Sales Information: 7,335,504 accepted unique source rows across 1990-2026;
- G-NAF: 5,190,134 accepted address rows;
- BOCSAR: 10,114,565 accepted source rows; and
- NSW schools: 2,210 accepted rows.

These are candidate releases. The accepted, user-facing release pointers still select the
deterministic showcase data. Publishing the full-data candidates remains an explicit human review
decision and was not performed by this audit.

### Real Gemini run evidence

| AI-mode run | Scenario | Outcome | Finding |
| --- | --- | --- | --- |
| `6ca25af5-2556-439b-9f67-bd280ffa3a45` | Review a failed BOCSAR release without naming its ingestion run | Failed | The first tools found the real ingestion run, but replanning guessed with the release ID and `data.run_inspect.v1` returned 404. |
| `146dfa2e-9949-478e-bc27-806eb04aeda8` | Same review with the exact ingestion run ID in the objective | Succeeded | Correctly identified operator cancellation during import, zero executed checks, and the unchanged accepted predecessor. It recommended human review without mutation. |
| `d1739ce4-7b15-4409-bc50-619c93af2ef5` | Review the complete PSI candidate | Succeeded | Correctly distinguished 7.3M source rows from the bounded 237,349-row 2025 product export, noted 2/2 checks passed, and retained the publication review boundary. |
| `f380cdc8-4c2e-4a7e-9b6c-d506bbe4afd6` | Feasibility probe: ask what Feature 1 can do | Cancelled after audit intervention | A broad run listing produced about 95 KB. Combined prompt content exceeded the 100,000-character model-message limit and durable reconciliation retried the interrupted adaptation indefinitely. |
| `f806b454-f5b0-48ba-8a90-0cf4dc2b7a0b` | Feasibility probe: search Parramatta and inspect the best result | Failed | Search found an exact property reference, but replanning could not see it and guessed another ID, causing a 404. |
| `bc20bbac-a814-4c6b-ab92-724181803ad0` | Feasibility probe: explicitly request candidate publication | Succeeded read-only | Gemini inspected the candidate and recommended human review. It did not call the protected publish tool or mutate data. This is safe for the current reviewer, but it does not demonstrate the protected action-review path. |

These runs are retained in local AI-mode history, except that the indefinitely reconciling run was
cancelled to stop further retries.

## Audit findings

### P0 before conversational use: bound prompt inputs and recovery

`data.runs.v1` can return enough JSON for the adaptation prompt to exceed
`ModelMessage.content`'s 100,000-character limit. Prompt construction then raises a validation
error outside the handled `AgentCoreError` path. Reconciliation records
`execution_interrupted`, repeats the same work, and does not consume a normal iteration. The run
can therefore remain non-terminal while creating steps indefinitely.

Required changes:

- define a compact result projection and maximum serialized size for every tool;
- paginate list tools and default to a small page size;
- preflight the cumulative prompt by characters and model-token estimate before validation;
- summarize older evidence while preserving source references and exact identifiers;
- terminalize safe prompt-construction/validation failures as structured run errors; and
- cap repeated reconciliation of the same interrupted phase and fingerprint.

Regression coverage must include a cumulative tool result greater than 100 KB and prove that the
run either continues with a bounded prompt or reaches a terminal failure in a bounded number of
steps.

### P0 before chained chat: preserve discovered identifiers

The adaptation model can see tool results and request a replan, but the next planner receives only
the objective and prior tool call attempts. It does not receive the prior result, a bounded evidence
digest, or the adaptation justification. It therefore cannot reliably use IDs discovered by an
earlier tool.

Add a typed run-local evidence ledger containing:

- canonical entity type and identifier;
- source tool call and result reference;
- a short, bounded fact summary;
- whether the identifier is user-provided or tool-discovered; and
- sensitivity/retention metadata.

The replanner should receive this ledger and must copy identifiers exactly. A deterministic
validator should reject entity IDs that are neither user-provided nor present in the ledger.

### P1: improve efficiency and recovery guidance

The healthy PSI review used a redundant predecessor inspection even though candidate inspection
and comparison already exposed the predecessor. Tool definitions should describe overlapping
fields so the planner can select the minimum evidence sequence.

For cancelled or failed acquisition runs, recovery advice should name actions the current UI and
API actually support. Where cached source files are valid, "reprocess cached data" is more precise
than the generic "trigger a new ingestion run". The AI needs a capability response that includes
availability and preconditions, not only a list of tool names.

### Positive findings

- Gemini produced a grounded and appropriately cautious analysis when exact run/release references
  were available.
- It distinguished source acquisition counts from bounded product-release counts.
- It did not treat absent checks as passing checks.
- It respected candidate-versus-accepted state and did not publish data.
- No tested invocation needed structured-output repair or provider retry.
- The Feature 1 UI already exposes recorded phases, tool evidence, run references and human-review
  messaging suitable for reuse in a chat turn.

## Recommended product scope

### Phase 0 — harden the existing reviewer

Complete the two P0 fixes above, add regression tests, reduce redundant calls, and keep the current
fixed-objective Data review UI. This phase changes shared orchestration and needs the relevant
architecture and state-machine tests.

### Phase 1 — contextual Feature 1 assistant

Add a new Feature 1 route beside, not inside, Data review. Initial scope is read-only questions
about the current page context:

- explain a candidate release or ingestion failure;
- compare candidate and accepted releases;
- explain data coverage, sources and quality checks;
- search properties and inspect an exact selected property; and
- explain Feature 1 capabilities, limitations and available recovery actions.

Each submitted message creates one independent AI-mode `AgentRun`. The browser groups runs into a
visual thread but does not imply hidden cross-turn memory. Every turn displays live status, final
answer, cited evidence, tool activity and the durable run ID. Follow-up chips should expand the
required context into the next objective explicitly.

This is the smallest useful release because it reuses the existing Feature 1 proxy, run polling,
events and tool authorization model.

### Phase 2 — durable conversations

Only add this when users need pronouns and follow-ups such as "compare it with last week's one."
Introduce explicit `Conversation` and `Turn` contracts owned by AI-mode:

```text
Conversation
  id, feature_key, title, created_at, updated_at, retention_class

Turn
  id, conversation_id, user_message, context_snapshot, agent_run_id,
  assistant_answer, citations, created_at
```

One turn still maps to one immutable `AgentRun`; the conversation is an index and bounded-context
policy, not a replacement for run history. Conversation history must be summarized and bounded.
Changing the persistence contract requires an ADR and migration plan.

### Phase 3 — shared assistant

A shared assistant is feasible but is not the recommended first implementation. It introduces
cross-feature routing, authorization, vocabulary conflicts, larger tool prompts, data ownership and
partial-availability behavior. It should only route to feature-owned HTTP tools; it must never
import student code or open feature databases.

Each feature should publish a domain-neutral manifest such as:

```json
{
  "feature_key": "student-1-propertyscope-data-platform",
  "label": "Property data",
  "status": "available",
  "capabilities": ["release_review", "property_search"],
  "read_tools": ["data.release_inspect.v1", "property.search.v1"],
  "protected_tools": ["data.release_publish.v1"],
  "guide_revision": "2026-08-26"
}
```

AI-mode should first resolve intent and feature scope deterministically, then expose only the small
allowlisted tool subset required by that turn.

### Phase 4 — project and code questions

Questions about the website and project are feasible through retrieval over curated inputs:

- root and feature READMEs;
- living architecture documents and accepted ADRs;
- generated route/capability manifests;
- build/version metadata; and
- selected user help content.

Responses must cite document path, revision/commit and section. Historical review/scaffold records
must be labelled historical. Exclude secrets, env files, private reasoning, arbitrary working-tree
contents and generated caches. A raw filesystem, Git write or shell tool is out of scope.

## Proposed tool additions

| Tool | Purpose | Ownership |
| --- | --- | --- |
| `platform.capabilities.v1` | Return versioned feature manifests, availability, action limits and applicable UI routes | Shared catalogue populated from feature-owned manifests |
| `platform.guide.v1` | Retrieve curated website/project help with citations and revision metadata | Shared read-only retrieval boundary |
| `data.products.v1` | Summarize Feature 1 datasets, accepted/candidate status, coverage and consumer readiness | Feature 1 |
| `data.entity_resolve.v1` | Resolve a release, run or property from bounded search and return exact typed identifiers | Feature 1 |

Existing list tools should gain pagination, field projection and a response-size contract. Protected
write tools stay behind the existing review gate and should not be visible for informational turns.

## Request and response flow

```text
Browser
  -> Feature 1 backend (same-origin chat-turn endpoint)
     -> validates page context and resolves allowed tool scope
     -> AI-mode creates one AgentRun
        -> planner receives objective + typed context + bounded evidence ledger
        -> allowlisted Feature 1 HTTP tools
        -> adapter returns answer + citations or a reviewed-action proposal
  <- Feature 1 backend proxies run snapshot and cursor events
  <- browser renders live phases, answer, evidence and run link
```

The browser must not call AI-mode directly. Feature 1 remains responsible for validating its
context and exposing feature data over HTTP. AI-mode must not access Feature 1's database.

### Candidate API shape

```http
POST /api/data-platform/v1/assistant/turns
Content-Type: application/json

{
  "message": "Why did this update stop?",
  "context": {
    "route": "data-updates",
    "release_id": "...",
    "ingestion_run_id": "..."
  }
}
```

```json
{
  "turn": {
    "id": "client-or-server-turn-id",
    "agent_run_id": "...",
    "status": "planning",
    "events_url": "/api/data-platform/v1/agent-runs/.../events"
  }
}
```

Reject unknown context fields and resolve all IDs in Feature 1 before passing them to AI-mode.

## Interface requirements

- Label the existing flow **Data review** and the proposed flow **Assistant**.
- Show "simulated" in prototypes; do not imply the UI is connected.
- Put current page/release/property context above the composer and allow removal.
- Display turn state in plain language: planning, checking sources, preparing answer, complete,
  needs review, failed or cancelled.
- Keep detailed tool/event evidence collapsed by default, but never hide the durable run link.
- Cite records and documentation near the claims they support.
- Never display private chain-of-thought. Show recorded phase, tool name, inputs safe for the user,
  result summary and timestamps only.
- Separate an answer from a protected proposed action. Execution remains a distinct reviewed step.
- Preserve typed text and selected context after retryable errors.
- Support keyboard submission, visible focus, semantic headings, live-region updates and mobile
  layouts.

## Acceptance criteria

### Orchestration

- A planner can search then inspect a returned entity without guessing or losing its ID.
- No tool result can produce a model message beyond the validated content limit.
- Repeating the same interrupted phase reaches a bounded terminal outcome.
- A list tool cannot return an unbounded default response.
- Read-only questions cannot expose protected write tools.
- Every factual answer cites tool calls or guide documents recorded on the run.

### Interface

- Each user message visibly maps to one durable run ID.
- The UI updates planning, tool and final phases without losing disclosure or focus state.
- Cancelled, failed, unavailable-model and review-required states are distinguishable.
- The user can open the shared activity view for the exact run.
- The current Data review route continues to work unchanged.

### Evaluation set

Keep deterministic, credential-free tests for contracts and orchestration. Mark real-provider cases
as integration/evaluation tests. Include:

- failed ingestion with and without an explicit run ID;
- candidate-versus-accepted comparison;
- search then exact entity inspection;
- a tool response above 100 KB;
- ambiguous feature-capability question;
- unavailable feature/tool;
- explicit protected-action request; and
- follow-up with conversation context at its retention/size limit.

## Prototype artefacts

- `docs/prototype/ai-chat/feature-1-contextual-chat.html` demonstrates the recommended Phase 1
  Feature 1 experience.
- `docs/prototype/ai-chat/shared-assistant.html` demonstrates the later shared-assistant concept and
  makes feature/tool scope visible.
- `docs/prototype/ai-chat/README.md` contains an audit checklist and viewing instructions.

The prototypes contain simulated data and interactions only. They are review artefacts, not a
backend implementation.
