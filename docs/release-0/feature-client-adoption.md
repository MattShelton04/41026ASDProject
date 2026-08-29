# Feature client adoption

This is the shortest supported path for Features 2–5 to consume Feature 1 data and Shared AI/chat
without crossing service ownership boundaries.

## What each feature owns

Each feature backend implements its own injected HTTP clients. Production code may import
`shared_contracts`; it must not import Feature 1, another student's package, `shared_testkit` or
`agent_core`. Keep origins in deployment configuration and paths in code. Use bounded timeouts, do
not follow redirects, forward request correlation, validate every response and preserve a
deterministic non-AI path when AI-mode is unavailable.

The frontend consumes only documented Shared barrels. Shared owns browser mechanics and visual
states; the feature owns vocabulary, page context, API routes and business interpretation.

## Feature 1 data-client sequence

1. Call `GET /api/data-platform/v1/data-products` and select the exact `dataset_id`, target feature
   and schema version your feature supports.
2. Implement `POST /api/data-import/v1/propertyscope-releases` on the feature backend. Validate the
   closed publication request schema and `Idempotency-Key` before doing work.
3. Resolve the supplied relative artifact path against a configured Feature 1 origin. Download
   without redirects and verify media type, byte count, SHA-256, envelope release/generation IDs,
   schema version and record count.
4. Ask the feature's own database service to atomically import or reject the generation. Store the
   provider release ID and source evidence needed by normal feature reads.
5. Return the typed publication receipt. A replay of the same idempotency key returns the retained
   receipt; a different payload under the same key conflicts.
6. On startup or after downtime, reconcile with
   `GET /api/data-platform/v1/data-products/{dataset_id}/accepted?target_feature=feature-N`.

`GET /dataset-releases/{release_id}/records` is a small operator preview. Do not page it as a hidden
bulk import API and do not treat a candidate as accepted. Normal feature requests read the feature's
own database after import; they do not fan out to Feature 1.

Feature 2 should accept `propertyscope.property-sales.v2`. It preserves source addresses and sales
classifications in addition to v1 facts. The accepted artifact remains a bounded publication unit;
all retained historical source facts are available from
`GET /api/data-platform/v1/data-products/nsw-psi-sales/source-records?year=YYYY`. Start without a
`release_id`, retain the returned immutable release ID, and pin every subsequent page with that ID.
Feature 2 should ingest each year into its own database and checkpoint `(release_id, year, offset)`;
it must not use the operator preview as a bulk API. Feature 3 currently has separate crime-series and school-
point products. Feature 4 has no approved Feature 1 product. Feature 5 composes bounded runtime
sections from feature backend APIs and does not import all upstream databases.

## AI-mode backend adapter

The feature backend exposes a same-origin assistant API with this browser-facing shape:

```text
GET  /api/<feature>/v1/assistant/capabilities
POST /api/<feature>/v1/assistant/turns
GET  /api/<feature>/v1/assistant/turns/{run_id}
GET  /api/<feature>/v1/assistant/turns/{run_id}/events?after=0&limit=100
POST /api/<feature>/v1/assistant/turns/{run_id}/cancel
```

For a turn, validate the user message and allowlisted page identifiers, construct an
`AgentRunRequest` from `shared_contracts`, and call AI-mode's `/api/v1/agent-runs` over HTTP. Set the
feature's exact `feature_key` and a per-run `tool_allowlist`. Tool registrations call fixed HTTP
routes on the owning feature backend; AI-mode never opens a feature database. Run detail, events and
cancellation must verify that the returned run belongs to the feature and expected assistant policy
before proxying it to the browser.

The feature owns its AI-mode transport class because it also owns timeout, availability and domain
fallback decisions. `shared_contracts` supplies validation models; it intentionally does not hide a
network client.

## Shared AI-chat frontend

Copy Shared's `ai-chat/` directory into the feature frontend image or serve it from the approved
same-origin Shared asset path. Import only `ai-chat/index.js` and load `ai-chat/styles.css` after the
Shared design tokens.

```js
import { createFeatureAssistant } from "./ai-chat/index.js";

const { controller } = createFeatureAssistant({
  root: document.querySelector("#assistant-root"),
  apiRoot: "/api/place-insights/v1/assistant",
  featureKey: "student-3-place-insights",
  featureLabel: "Place insights",
  returnTo: "/features/place-insights/#assistant",
  scopes: [{
    id: "feature",
    label: "Place insights",
    description: "Crime, schools and place evidence exposed by this feature.",
  }],
  suggestions: ["What evidence is available for this place?"],
  context: {property_ref: currentPropertyRef},
});
```

Destroy the returned controller when the route unmounts. Use `controller.setContext(...)` when the
selected entity changes. Never place secrets, raw database rows or arbitrary query fields in page
context.

## Minimum verification

```text
node --test shared/frontend/ai-chat/ai-chat.test.mjs
uv run pytest shared/contracts/tests --no-cov -q
uv run python scripts/validate_architecture.py
```

Each feature then adds provider/consumer contract tests for success, empty data, schema mismatch,
checksum mismatch, timeout, unavailable dependency, idempotent replay and retained deterministic
reads when AI-mode is degraded.
