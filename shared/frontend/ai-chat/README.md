# Shared AI chat

Import from `index.js`. This package owns presentation, drafts, polling, cancellation and
accessible interactions. The feature owns vocabulary, API routes, allowed tools and record lookup.
Load `styles.css` after the Shared design-system styles.

`createAiChat({root, client, ...options})` mounts the full-page experience. Use
`createAssistantSidecar({root, trigger, client, ...options})` to embed the same controller in a
page. It exposes `show()`, `hide()` and `destroy()`. Pass a separate client per mounted instance;
route disposal must call `destroy()`. Hiding the sidecar preserves its conversation and draft.
Destroying it aborts local requests; only the explicit Stop control cancels the durable run.

Feature adapters can inject `scopes`, `suggestions`, `context`, `contextOptions`, `toolLabels`,
`activityHref(runId)` and `searchContext(kind, query, {signal})`. A lookup returns
`{items: [{label, context}], note}`. The user selects a match; the controller never chooses the
first result. A context parameter may declare `searchParameter` alongside its canonical-ID
`pattern`. Readable input stays a query until the feature resolves it to an identifier.
Feature 1's `frontend/integration/assistant.js` demonstrates both entry points and public lookup.

Use `announce(message)` to integrate an existing page announcer. Omit it to use the component's
own polite live region. Each instance has distinct input IDs. Call `setDraft(message)` and
`focusComposer()` for page-local actions; these do not submit a turn.

The reading surface contains the answer, attributed findings and relevant evidence gaps.
Suggested next steps are collapsed. Sources, context, scope, evidence support and recorded steps
share one inspection panel, displayed alongside the answer on wide screens and within the flow
on small screens. Embedded chat switches to a full-width sources view with **Back to answer**;
its one scrolling body retains the conversation and reading position. Full activity links retain
the feature and return-page context.

Progress is derived from durable snapshots and events, including parallel tools matched by call
ID. A failed events request does not discard a successful snapshot. The elapsed timer never
invents progress. The 320–1800 ms word reveal decorates an already validated overview and findings
in reading order; it is not provider streaming. Reduced motion shows the full answer immediately,
and assistive technology receives the complete text instead of repeated word announcements.

Pure projections are covered by Node tests; Feature 1's browser suite covers success, event
failure, normal/reduced motion, embedded drafts, cancellation and nested-panel keyboard focus.
