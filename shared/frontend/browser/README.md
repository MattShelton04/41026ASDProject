# Shared browser primitives

`browser/index.js` is the stable, domain-neutral public surface used by the Shared home and all
five feature frontends. Docker images copy these assets; the development overlay mounts the same
sources. Feature code must import the public barrel, never a private implementation file. No
frontend framework, bundler or additional npm dependency tree is required.

## Responsibilities

| Public API | Shared responsibility | Feature responsibility |
|---|---|---|
| `el`, `append`, `escapeHtml` | Safe DOM construction / text and attribute escaping | Labels, domain projections and safe URL choices |
| `requestJsonResponse`, `createJsonClient`, `HttpProblem` | Bounded fetch **and body consumption**, request IDs, JSON/error decoding, composed cancellation | API paths, domain errors, mutation/idempotency policy |
| `withRequestLifecycle`, `RequestTimeoutError` | Deadline and abort listener cleanup, including non-cooperative promises | Propagate the supplied signal into work; do not treat browser cancellation as server rollback |
| `createLatestTask` | Cancel a previous task and invalidate its render permission | Start on selection/navigation; guard state writes with `isCurrent()` |
| `pollUntilSettled`, `abortableDelay` | Cancellable read-only polling, attempt and wall-clock limits | Terminal states, progress rendering, eventual run reconciliation |
| `createDrawerController`, `createToastController` | Interaction, focus and timer ownership | Content, messages and when to dismiss |
| `createTableRegion`, `disposeTableRegions` | Overflow affordance and observer disposal | Dispose a region **before** replacing its DOM |
| `resolveProductHome`, `initialiseFeatureShell`, `mountFeatureShell` | Product links and measured responsive header geometry | Feature entrypoint, local sidebar, filters and routes |

Transport errors retain status, problem code, request ID and cause. A `204` response returns `null`.
Unreadable JSON is an error, not a successful empty object. The transport does not retry mutations.
An abort rejects the caller's wait; a server may already have accepted a write. Reconcile that
write through its domain API rather than replaying it blindly.

```js
import { createJsonClient, createLatestTask } from "./browser/index.js";

const api = createJsonClient({ baseUrl: "/api/owned-feature/v1", timeoutMs: 10000 });
const selection = createLatestTask();

async function selectRecord(id) {
  const task = selection.start();
  try {
    const record = await api(`/records/${encodeURIComponent(id)}`, { signal: task.signal });
    if (task.isCurrent()) renderRecord(record);
  } catch (error) {
    if (task.isCurrent()) renderProblem(error);
  }
}

addEventListener("pagehide", () => selection.cancel(), { once: true });
```

`renderRecord` and `renderProblem` above are feature-owned functions, not Shared hooks.

## Common feature shell

Load `design-system/shell.css` after the feature stylesheet. Use `.ps-feature-header`,
`.ps-feature-brand` and `.ps-product-nav` for product chrome. Keep feature-specific layout outside
those classes. Each feature has a small external `shell.js` entrypoint that calls
`mountFeatureShell()` through this barrel. The barrel itself has no mounting side effects and the
HTML requires no inline bootstrap script.

`data-product-home` links resolve to the Shared home. `data-product-path` links resolve relative to
that home. Integrated `/features/...` routes retain their current origin. Standalone loopback
feature servers use port 5100 for the Shared home. Deployments can set
`globalThis.PROPERTYSCOPE_HOME_URL` to an explicit HTTP(S) URL without credentials through an
approved external configuration script. The shell measures header and workspace-strip heights
rather than assuming a fixed offset when navigation wraps or browser zoom changes.

This is a shared **product header**, not a universal business-workflow component. Domain tables,
forms, evidence claims and API response envelopes remain owned by their feature.

## Testing

From the repository root, using Node.js 20.6 or later:

```text
node --import ./scripts/frontend-test-bootstrap.mjs --test shared/frontend/browser/browser.test.mjs
```

The bootstrap maps feature-local copies of Shared assets to their source modules **only inside
Node tests**. Production imports remain ordinary relative ES modules. Run the canonical
`uv run python scripts/check.py` before merging and the separate cross-feature browser smoke
when changing shell layout; see `CONTRIBUTING.md`.

Only HTML entry scripts carry a deployment cache revision. Internal ES module imports use their
canonical query-free URL so a page does not instantiate parallel module graphs for different
`?v=` values.
