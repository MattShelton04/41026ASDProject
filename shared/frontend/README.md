# Shared frontend

This directory owns domain-neutral browser assets for the eventual unified entry point. It
must not absorb student feature behavior or call feature databases directly.

## AI-mode operations

`operations/ai-mode/` is the read-only Release 0 showcase and debugging interface for durable
AI-mode runs. AI-mode currently serves these assets at `/operations/ai-mode/` only when
`AI_MODE_OPERATIONS_ENABLED=true`; the future shared edge can proxy the same stable paths
without changing the client. The browser calls only the versioned AI-mode HTTP API.

The implementation intentionally uses accessible HTML, CSS, and small JavaScript modules
instead of introducing a second application framework. It renders untrusted values with
`textContent`, uses no inline script/style, stores only a run ID/cursor in session storage,
and never stores objectives or tool evidence in browser storage.

The workspace is viewport-constrained on desktop/laptop and uses a one-pane list/detail drill-in
on mobile. Polling policy lives in `operations/ai-mode/polling.js`; the UI uses request
timeouts, aborts, generation guards, adaptive index cadence, bounded event hydration, and local
elapsed rendering between durable changes. Its dependency-free behavior tests use Node's
built-in test runner, not a second browser automation stack:

```text
node --test shared/frontend/operations/ai-mode/polling.test.mjs
```

Run the deterministic server and contract tests with:

```text
uv run pytest ai-services/ai-mode/tests shared/contracts/tests
```

The repository has not selected its common browser E2E stack. Add dashboard browser tests to
that one shared stack when it is chosen; do not introduce both Playwright and Cypress.
