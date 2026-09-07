# AI assistant experience

## Product role and entry model

The assistant is a bounded research instrument, not a universal agent floating above the application. The shared `#assistant` route is a full reading workspace; Feature 1 offers feature/context-scoped entry; suburb analytics consumes the shared controller in its own context. Market cases and site reviews retain their domain-specific adapters and saved workflows. Buyer summary is a buyer-owned workflow, not an interchangeable global agent run. These surfaces share hierarchy and visual language without falsely promising identical tools.

A global floating bubble and an always-open drawer were deliberately not added. They would consume map/table/mobile space and imply ambient context or permissions the contracts do not grant. Explicit navigation and scoped actions make the question’s domain legible before submission.

## Trust boundary

A user turn is submitted through the owning feature backend and maps to a durable agent run. AI-mode invokes allowlisted tools through feature APIs. It does not gain direct access to feature databases. The UI renders recorded public state, results and evidence, with a link to complete durable activity. It never exposes or simulates private chain-of-thought.

The Feature 1 capability guide now uses revision `2026-09-07.v4`. Its correction is narrow but important: other enabled research areas are **not connected to this assistant’s tools**, rather than “not implemented.” This is presentation/prompt guidance, not an expansion of the registry or authorization. The app’s availability, backend health, evidence readiness and this assistant’s tool access remain separate.

## Composer contract

Scope and relevant context are visible above the question. A submitted turn snapshots those values; later scope changes cannot relabel an old answer. Scope/context controls are locked while a run requires an unresolved decision. Selecting a scope never bypasses server validation.

The composer autosizes within a bounded height (64–200px in the controller) and preserves a new draft while a run is active. Enter submits; Shift+Enter makes a newline; `isComposing` prevents accidental submission during an input-method composition. A question needs meaningful content, and pending/submitting guards prevent duplicate turns. The busy label reports an actual action, not guessed model activity.

Drafts are **memory-only**, keyed by feature namespace, scope and normalized context. The store is bounded to 12 contexts and 2,000 characters per value. It uses no browser storage, cookies or network and does not survive a page reload. This is local writing convenience, not durable conversation storage. Users are explicitly told not to enter secrets.

The existing bounded conversation history remains at most four exchanges/eight messages with its total text bound. It is not evidence or authorization. Draft scope and the durable run are independent records.

## Response hierarchy

The direct answer appears first when supplied by the runtime. Supporting findings, limitations, recommended next step and verification questions are rendered only when the returned result contains them. The frontend does not fill a template with invented evidence or synthesize a “confidence score.” Source/tool checks and full activity sit one layer deeper. Human-readable labels precede run IDs and raw payloads.

Accepted data is not synonymous with complete evidence. A model’s successful response is not a publication approval. No-evidence output remains a valid answer with a clear limitation; it does not acquire placeholder source cards. Candidate, missing or partial evidence keeps its qualification.

## Status and polling model

| Recorded state | Reading experience | Not implied |
|---|---|---|
| Queued | Request accepted, awaiting work | A model is already answering |
| Planning / acting / recording | Concise public phase and available tool/evidence activity | Private reasoning or an invented progress percentage |
| Preparing answer | Output preparation when the real state/events support it | Fake streaming tokens |
| Succeeded | Completed result with its limitations | Correctness, full coverage or accepted publication |
| Review required | Paused, decision needed; retain context and available review/cancel paths | Success or automatic approval |
| Failed | Visible reason and retained original question | Silent resubmission |
| Cancelled | Confirmed cancelled state; old poll cannot resurrect it | Local button click alone proves cancellation |
| Poll/network warning | Keep last-known run and content, disclose temporary connection trouble | Run failure or lost evidence |

`turnPresentationKey` captures the visible answer/evidence/status inputs. Identical polls keep the existing DOM. Necessary updates retain disclosure state, focus and scroll anchoring. Revision guards reject late requests after cancellation or supersession. A cancellation failure remains a warning, not a fabricated cancelled state.

## Recovery details

If capability guidance is unavailable, a banner says so; the question composer does not falsely report that the entire provider is healthy. Provider rejection or invalid context before a run is created restores the submitted question **only when the current composer is empty**, so a newly typed question is never overwritten. The failed attempt stays visible.

“Prepare question again” copies the question into the composer and focuses it. It does not automatically submit, inherit stale invalid context or create another run. The user can inspect scope, revise the question and deliberately submit. This is used consistently for failed submissions and failed recorded turns. Review-required blocks an accidental second unresolved workflow rather than implying the first one completed.

The browser fixtures cover capability outage, provider rejection, invalid context, no evidence, temporary polling failure, failed run, review-required and cancellation. Those are synthetic public records. No real model credential, provider response or production activity was evaluated here.

## Responsive behavior

Desktop gives the answer a readable measure and keeps the composer convenient after a turn. On mobile the composer returns to normal flow, with safe-area treatment and comfortably sized controls, rather than occupying an unverified keyboard overlay. Scope and context wrap. Evidence metadata and long identifiers are contained or wrapped. The activity counterpart uses a responsive list/detail layout with a visible title, mobile Navigate menu and back-to-list control.

## Full activity counterpart

`shared/frontend/operations/ai-mode/` now uses the same light identity while keeping expert density. Friendly labels cover all enabled features and observed run keys populate filters, but filtering is not authorization. Optional storage is defensive: denied access, corrupt cursor text or failed writes fall back safely instead of crashing. Failure to replace browser history does not prevent reading.

Return destinations remain bounded and validated. Feature 1’s activity URL helper supports the shared assistant and legitimate feature routes in integrated and standalone serving. Unknown/external paths are rejected. Buyer summary IDs are not passed as global run IDs. Audit payloads remain available after the primary result rather than dominating the conversation.

## Maintainer reference

Core files: `shared/frontend/ai-chat/{controller,components,experience,styles,formats}.js/css` as applicable; public imports remain through `index.js`. Feature 1 activity URL construction is in `student-1/frontend/integration/activity.js`; AI-mode context and cursor handling are in its existing frontend modules. The source changelog identifies all touched adapters. New pure tests cover draft/presentation helpers, cursor-storage failure and safe context returns; browser workflows cover the actual composer and degraded-state interactions.
