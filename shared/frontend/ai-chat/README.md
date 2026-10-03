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

Use `initialTurns: [{run, message, context, canCancel}]` to reopen recorded work in the same
transcript. The feature projects its durable envelope, original question and validated identifiers;
Shared renders the answer, fetches events and polls active runs through the injected client.
Set `canCancel: false` when that historical run cannot use the client's cancel endpoint; its
activity link remains available. Reopening does not create or replay a run. Completed answers
participate in the bounded history sent with an explicit follow-up.

Suggestions appear above the composer in visual and keyboard order. An odd final suggestion
is centred at the same width as its neighbours; narrow and embedded layouts use full-width rows.
Context-specific saved drafts take precedence over an initial suggested message.

The reading surface contains the answer, attributed findings and relevant evidence gaps.
Suggested next steps are collapsed. Sources, context, scope, evidence support and recorded steps
share one inspection panel, displayed alongside the answer when its mounting surface is at least
1100 px wide and within the flow in narrower containers. The composer stays in normal flow in
narrow containers so it cannot cover source excerpts. The controller adds a named CSS container
to its root; narrow feature columns therefore retain readable controls even on a wide monitor.
Embedded chat switches to a full-width sources view with **Back to answer**;
its one scrolling body retains the conversation and reading position. Full activity links retain
the feature and return-page context.

Progress is derived from durable snapshots and events, including parallel tools matched by call
ID. A failed events request does not discard a successful snapshot. The elapsed timer never
invents progress. The 320–1800 ms word reveal decorates an already validated overview and findings
in reading order; it is not provider streaming. Reduced motion shows the full answer immediately,
and assistive technology receives the complete text instead of repeated word announcements.

Pure projections are covered by Node tests; Feature 1's browser suite covers success, event
failure, normal/reduced motion, embedded drafts, cancellation and nested-panel keyboard focus.
