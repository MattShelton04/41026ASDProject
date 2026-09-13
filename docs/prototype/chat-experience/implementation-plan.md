# Shared + Feature 1 chat implementation plan

Updated 13 September 2026. User selected the Focus/Canvas entry and an embeddable contextual
sidecar, using the existing Fieldbook design system and shared implementation.

## Observed baseline

Each message creates a Feature 1-validated, read-only, durable AI-mode run. The browser polls its
snapshot and cursor events. The shared Plan → Act → Observe → Adapt runner dispatches approved
feature tools through MCP; semantic RAG separately queries the feature's versioned operator
guidance. Only the owning feature service accesses its database. Answers are structured JSON,
not token streams. Four completed visible exchanges provide bounded follow-up context.

The full local Docker development stack was started with `uv run scripts/dev.py stack up`.
AI-mode, MCP, semantic RAG and the provider reported ready. Three actual OpenAI-backed turns:

| Question | Observed completion | Durable run |
|---|---:|---|
| What can PropertyScope help me research? | 10.53 s | 120f2171-e30d-40b7-95c5-ed8910242b33 |
| Registered addresses in Sutherland 2232? | 11.58 s | 95a5a53a-b778-4b72-85e2-2cb1d992bc2d |
| Why can an accepted address have no sale history? | 10.53 s | 920e64a7-b515-4dc2-9077-eebdef325151 |

These are individual local observations with one-second sampling, not latency percentiles.
The first two answers incorrectly labelled current tool information as document guidance. In
particular, the numerical locality answer cited a general discovery passage that contains no
locality count. Reference existence validation does not establish semantic support. That finding
is a priority regression case, not evidence that the entire RAG pipeline is absent.

The UI also misses parallel `tool_calls`/`tool_results` in its old singular-only activity formatter,
uses generic phase labels during waits, requires GUIDs for context input, and displays repeated
technical/safety sections ahead of useful findings. It requests both detail and events every poll;
failure of either currently prevents applying the successful sibling response.

## Implementation sequence

1. **Context without GUID memorisation.** Keep the exact identifier authoritative and carry a
   bounded readable label alongside it. Accept a separate bounded search query, never promoted
   into the identifier ledger. Address queries use accepted search; release/update names use
   bounded inventories with explicit ambiguity/coverage limits. Add selectable lookup results in
   Feature 1's adapter; shared chat owns only the interaction and cancellation lifecycle.
2. **One shared presentation.** Use Focus for the empty state, a compact real activity indicator
   while working, and Canvas for the completed brief. Embed that same controller in a dismissible
   property-page region. Opening/closing it must not navigate away or create a second controller.
   Dispose it on route departure; closing presentation must not pretend to cancel server work.
3. **Recorded progress.** Project persisted single/parallel tool calls into readable activities,
   durations, outcomes and evidence. Update only when the state changes, preserve open disclosures
   and focus, honour reduced motion, and show reconnect/cancel states without fictitious percentage
   completion. Use validated action purposes as concise activity context, not private reasoning.
4. **Evidence and writing.** New immutable grounded prompt version with explicit examples of both
   tool facts and guidance. Provide a compact identity ledger for successful evidence sources.
   Keep tool-only factual findings possible without forcing irrelevant document citations. Retain
   retrieval availability labels and the existing reference/scope/version checks. Lead with the
   direct answer; use plain findings, specific gaps, optional next step and collapsed technical
   material. Tool references should open the actual recorded result within the same interface.
5. **Resilience and maintainability.** Apply successful snapshots even when event polling fails;
   preserve the event cursor and back off. Use scoped DOM IDs for multiple mounted components.
   Keep the same client, renderer and state machine in page/embedded modes. No second frontend
   framework, no per-feature copies of Shared and no separate agent loop.
6. **Verify and review.** Capture matching real-origin before/after images. Exercise successful
   research, follow-up, source inspection, ambiguity, cancellation, unavailable guidance and
   temporary update failure. Test desktop/mobile/reduced motion, run the canonical quality gate
   and required Feature 1 browser checks, then ask a subagent for a final review. Reproduce and fix
   valid findings before pushing and opening the PR.

## Assignment alignment

Reviewed the locally supplied `ASD_2026_Project_Specifications.txt` (sections 4, 6–8) under
`C:/git/Uni/courses/41026-advanced-software-development/files/week-0/`, its planning checklist,
and the current repository architecture/ADR guidance. Retain the approved model/PostGIS
exceptions, the shared four-phase loop, feature ownership, reproducible prompts, MCP and RAG
evidence. The Docker AI placement tested here is development topology; assessment uses
`stack up --ai-runtime host` under the repository's recorded Release 1 rubric interpretation.
Do not claim this increment independently completes all five students' assessment evidence.
Advanced services stay gated off in CI/cloud; deterministic tests use injected doubles.

## Further measured work

Do not add SSE or raw token streaming simply to animate the page. Persisted events already cover
the useful stages; streaming unvalidated answer fragments would weaken the citation boundary.
Measure payload bytes and update latency before adding long polling/SSE. Likewise, keep the
small semantic index until a frozen retrieval set demonstrates a need for hybrid search or
reranking. Expand positive/negative/adversarial and per-claim attribution cases before claiming
retrieval quality. A semantic entailment check is future evaluation work, not a capability of
the current reference validator. General capability and numeric questions must not manufacture
guidance citations merely because RAG is enabled.

## Prototype review

The five isolated studies are linked by `index.html` and served from the scratch copy at
`Temp/chat-experience/index.html`. They use synthetic data and timing. They are design evidence,
not live provider results. The implementation replaces their sample slogans with direct product
copy and binds progress/answers to the real shared runtime.

## Implemented information layout

| Information | Presentation | Reason |
|---|---|---|
| Direct answer | First paragraph, with a fast word reveal | Answer the question immediately once the server has validated it. |
| Findings | Short attributed statements with source buttons | Keep claim-to-source navigation visible. |
| Relevant missing evidence | In the answer | A material gap must remain visible without opening another panel. |
| Suggested next step | Closed disclosure | Optional advice should not compete with the result or composer. |
| Document passages and current tool facts | One Sources and activity panel | Inspect provenance alongside the conversation on desktop. |
| Scope, linked page context, evidence support and limits | Within the details panel | Preserve transparency without repeating technical sections in every turn. |
| Current activity | Compact phase label, real checks and elapsed time | Convey recorded progress without simulated percentages. |
| Complete activity | Durable history link retaining the return page | Review all parallel checks and model/workflow metadata outside the conversation. |

The panel opens inline on narrow screens and inside the embedded assistant. The shared controller
owns both layouts; Feature 1 supplies its record lookup, tool names and context. Summary reveal
takes 240–1100 ms, honours reduced motion and exposes a complete accessible sentence throughout.
It does not add a provider stream or display unvalidated JSON fragments.

## Live implementation observations

Actual OpenAI-backed runs using adapter v9 now distinguish count/property facts from operator
guidance. The count turn `b0ea19ba-c2f8-4870-9963-597c6d8a451b` reports 8,947 addresses with a
successful locality-tool reference and no manufactured document citation. The property turn
`84ef9b67-afc1-43a5-bdc5-dc031cdc1225` reports an available accepted sale-history dataset with
zero returned records, and separately cites guidance explaining what missing records cannot
establish. Follow-up count runs returned the same current count; some also included a separate
relevant guidance finding. These observations are a smoke test, not a retrieval-quality benchmark.

Two history defects were reproduced and fixed: the Shared edge retained an obsolete AI container
address after recreation, and the operations projection retained only the first parallel tool.
The gateway now re-resolves Docker DNS; projection v3 includes every call and invalidates old
detail ETags. The old property run was reopened through Shared after recreation and both
`context.retrieve.v1` and `property.inspect.v1` were inspected successfully.

The requested final subagent review identified Escape propagation closing both nested panels,
and focus returning to a trigger removed by polling. Both findings were verified, fixed and
covered by browser regressions. The reviewer then stopped at its usage limit before completing
the full diff review; the parent agent continued validation. Do not interpret this as a completed
independent approval of every backend change.

Before/after images and live entry links are in the [comparison index](../../design/chat-experience-evidence/index.html).
The scratch gallery also links the comparison and implementation. Persistent history remains
available after navigation; the conversation itself is local to its current mounted view.

## Follow-up: progressive findings and more space

The user's screenshot review led to a wider dedicated sources column (flexible, minimum 360 px),
larger source typography and a property assistant taking the larger share of its desktop split.
Property summary and map stack in the narrower property column. The embedded sources panel now
replaces the conversation temporarily, with **Back to answer**, so it has the full reading area
and does not introduce a nested scrollbar. Closing/reopening preserves the selected view.

The overview and findings reveal in reading order within 320–1800 ms total. Browser regressions
observe actual partial word frames for both paragraphs and verify complete accessible text during
reveal. Reduced motion renders both immediately. Source buttons remain intact throughout.

A new final subagent review identified loss of the document's reading position when returning
from sources. The issue was reproduced at 390 and 1440 px with a long question: the page moved
1,206 and 230 px respectively. Saving/restoring both the document and assistant-body scroll
positions fixed both regressions. The reviewer found no additional actionable issues in the
scoped polish diff; this review does not replace a full independent backend review of PR #111.

Validation for the polish update: `uv run python scripts/check.py` passed (2,015 Python and
221 Node tests; 41 existing optional/platform skips). The final Feature 1 browser suite passed
all 48 tests, and the final type check passed. Live desktop views were inspected at 1280/1440 px;
the embedded sources view at 390 px had a 309 px panel and 375 px document width without horizontal
overflow. Updated captures are at the top of the comparison index. No backend behavior or
provider/retrieval policy changed in this follow-up.

## Final validation

- `uv run python scripts/check.py`: passed, exit 0; 2,015 Python tests and 221 Node tests
  passed. Formatting, lint, style, architecture, generated contracts/deployment, syntax,
  type checks and configured coverage gates passed. Forty-one tests were skipped: two
  Windows symlink privilege checks and 39 opt-in PostgreSQL integration/scale checks.
- `uv run pytest student-1/tests/e2e/test_form_behaviour_playwright.py --no-cov -q`:
  47 passed, including normal/reduced motion, successful snapshots with failed event requests,
  embedded context/drafts/cancel, and the two nested-panel keyboard regressions.
- Shared quick UI audit: zero findings. Feature 1 property-discovery quick audit: zero errors,
  seven informational findings for intentionally scrollable tables. These are bounded quick
  audits, not a full-site accessibility certification.
- Actual local OpenAI/MCP/RAG chat probes and historical parallel-tool inspection passed;
  the Shared gateway remained reachable after AI container recreation. Mobile inspection
  at a 390 px viewport had 375 px document content width and no horizontal overflow.
- `git diff --check`: passed. No exhaustive provider eval, RAG relevance benchmark, cloud
  deployment, host-model assessment rehearsal or optional database scale suite was run.

Only documentation and captured review artifacts were added after the final code quality gate.

## Implemented information layout

| Information | Presentation | Reason |
|---|---|---|
| Direct answer | First paragraph, with a fast word reveal | Answer the question immediately once the server has validated it. |
| Findings | Short attributed statements with source buttons | Keep claim-to-source navigation visible. |
| Relevant missing evidence | In the answer | A material gap must remain visible without opening another panel. |
| Suggested next step | Closed disclosure | Optional advice should not compete with the result or composer. |
| Document passages and current tool facts | One Sources and activity panel | Inspect provenance alongside the conversation on desktop. |
| Scope, linked page context, evidence support and limits | Within the details panel | Preserve transparency without repeating technical sections in every turn. |
| Current activity | Compact phase label, real checks and elapsed time | Convey recorded progress without simulated percentages. |
| Complete activity | Durable history link retaining the return page | Review all parallel checks and model/workflow metadata outside the conversation. |

The panel opens inline on narrow screens and inside the embedded assistant. The shared controller
owns both layouts; Feature 1 supplies its record lookup, tool names and context. Summary reveal
takes 240–1100 ms, honours reduced motion and exposes a complete accessible sentence throughout.
It does not add a provider stream or display unvalidated JSON fragments.

## Live implementation observations

Actual OpenAI-backed runs using adapter v9 now distinguish count/property facts from operator
guidance. The count turn `b0ea19ba-c2f8-4870-9963-597c6d8a451b` reports 8,947 addresses with a
successful locality-tool reference and no manufactured document citation. The property turn
`84ef9b67-afc1-43a5-bdc5-dc031cdc1225` reports an available accepted sale-history dataset with
zero returned records, and separately cites guidance explaining what missing records cannot
establish. Follow-up count runs returned the same current count; some also included a separate
relevant guidance finding. These observations are a smoke test, not a retrieval-quality benchmark.

Two history defects were reproduced and fixed: the Shared edge retained an obsolete AI container
address after recreation, and the operations projection retained only the first parallel tool.
The gateway now re-resolves Docker DNS; projection v3 includes every call and invalidates old
detail ETags. The old property run was reopened through Shared after recreation and both
`context.retrieve.v1` and `property.inspect.v1` were inspected successfully.

The requested final subagent review identified Escape propagation closing both nested panels,
and focus returning to a trigger removed by polling. Both findings were verified, fixed and
covered by browser regressions. The reviewer then stopped at its usage limit before completing
the full diff review; the parent agent continued validation. Do not interpret this as a completed
independent approval of every backend change.

Before/after images and live entry links are in the [comparison index](../../design/chat-experience-evidence/index.html).
The scratch gallery also links the comparison and implementation. Persistent history remains
available after navigation; the conversation itself is local to its current mounted view.
