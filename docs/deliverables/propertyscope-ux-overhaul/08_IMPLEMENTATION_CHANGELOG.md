# Implementation changelog

## Baseline and commit history

Baseline: `86b2ac8e69f31f39cf6ad4c5061e7e2e5fb8efef` from the exact uploaded source ZIP, with 917 source files and a clean initial working tree. No edits were made to the supplied ZIP or its extracted baseline files. Focused implementation commits before this documentation/packaging checkpoint:

```text
3bdca8b feat(ui): establish Fieldbook identity, shared navigation and trustworthy assistant
afc4d00 feat(ux): unify evidence workflows, responsive features and audited AI recovery
6ab0e09 test(ui): add isolated cross-feature states, workflow and accessibility browser audits
fee5e9a style(assistant): keep bounded capability guidance within Python conventions
0f16819 fix(ux): retain property search under denied history and wrap long mobile records
```

The package manifest records the final documentation-inclusive commit and complete changed-file inventory. This document does not manufacture an upstream Git SHA: the input ZIP had no Git history.

## Shared identity and foundation

Reworked semantic tokens, warm/evergreen foundations, research/operator density, page hierarchy, responsive shell, local parcel mark and outlined wordmark. Shared navigation consumes enabled-feature availability and no longer offers disabled-feature bypass links or stale planned-only copy. Updated the gallery and design-system documentation. Existing public import barrels remain stable; domain logic was not moved into shared UI.

## Assistant and activity

Added bounded contextual memory-only drafts, autosizing and composition-safe input, duplicate-turn guards, immutable submitted context, presentation fingerprints and stable polling disclosure/focus. Cancellation uses a revision guard. Rejected submission preserves an empty draft and every retry is explicitly prepared rather than automatically sent. Public answer/evidence hierarchy and safe durable activity links replace raw-ID-led presentation.

AI operations now uses the same light identity, responsive list/detail and visible mobile heading. Optional cursor storage and history updates cannot crash reading. Friendly labels reflect available/observed feature keys without changing authorization. Return navigation validates the supported destinations. Feature 1 capability-guide revision is `2026-09-07.v4`; its “planned” wording is corrected to tool-connection scope, without enlarging allowlists.

## Features 1–5

Property data distinguishes search/research from compact operations, introduces stable pending geometry, fixes pagination gutters and long responsive-table text, and constructs activity URLs through one pure helper. Property search no longer depends on successful optional History API writes. The limitation first appeared under the opaque test origin; defensive behavior now allows the real request to continue when history access is denied.

Sales & market uses selected-case-first hierarchy, real volume proportions, named table regions and native dialog focus/error recovery. Case changes discard stale evidence; async selection results are guarded. Scoped assistant state and cancellation remain truthful.

Suburb context moves filters ahead of the map, treats null/missing observations separately from zero, differentiates chart series, validates distinct comparison localities/dates and fixes the required-field Cancel trap. Labels, charts and map-control touch geometry align with shared tokens.

Site & planning leads with dated/source-attributed evidence and explicitly absent coverage. Search/detail requests reject stale results; native forms and long content remain usable. “Generate & save questions” reflects the actual bounded saved workflow. Safe URLs and available coordinates are used; no geography is invented.

Buyer workspace promotes the address/case task over UUIDs, clarifies evidence availability, preserves summary content during pending updates, exposes actual workflow phases, and avoids linking its local summary ID to an unrelated global agent-run route. Section navigation preserves the router hash.

## QA and maintainability

Added a loopback-only browser fixture adapter with in-memory Feature 2–5 records, exact mutation boundaries, version/validation errors and deterministic assistant states. It is not production data or a new service. Added route/control/state, interaction and sampled accessibility scripts. The existing cross-feature smoke was updated for actual navigation behavior.

The frontend Node suite increased from 195 passing tests at baseline to 203 passing tests. Seven pure fixture tests pass; twenty existing assistant-domain tests pass in an explicitly isolated import harness, not a full backend integration run. The style exception baseline shrank from 322 distinct entries / 508 occurrences to 142 entries / 247 occurrences; no new allowlist weakening was used.

## Dependencies, contracts and footprint

No new runtime dependency, CDN, framework, provider credential, database schema, public endpoint or tool permission was introduced. Python remains targeted at the existing supported 3.12 contract. The first-party frontend source comparison (JS/CSS/HTML/SVG, excluding vendor/tests) is 850,995 → 910,228 uncompressed bytes, +59,233 (7.0%). This is a source-footprint measure, not a measured startup/interaction-time claim. All font files are excluded; SVG glyph outlines retain attribution.

## Changed source/test/tool files

The exact final SHA-256 inventory, including documentation and binary evidence assets, is in the apply-package manifest. Source/test/tool changes at this checkpoint:

```text
README.md
docs/ui/frontend-style-baseline.json
scripts/tests/test_ui_experience_fixtures.py
scripts/ui_audit/experience_accessibility.js
scripts/ui_audit/experience_inventory.js
scripts/ui_experience_accessibility.py
scripts/ui_experience_audit.py
scripts/ui_experience_fixtures.py
scripts/ui_experience_interactions.py
scripts/ui_experience_seed.json
scripts/ui_feature_smoke.py
shared/frontend/ai-chat/ai-chat.test.mjs
shared/frontend/ai-chat/components.js
shared/frontend/ai-chat/controller.js
shared/frontend/ai-chat/definitions.js
shared/frontend/ai-chat/experience.js
shared/frontend/ai-chat/feature-route.js
shared/frontend/ai-chat/formats.js
shared/frontend/ai-chat/styles.css
shared/frontend/app.js
shared/frontend/browser/shell.js
shared/frontend/dashboard.test.mjs
shared/frontend/design-system/CHANGELOG.md
shared/frontend/design-system/README.md
shared/frontend/design-system/base.css
shared/frontend/design-system/brand/NOTICE.txt
shared/frontend/design-system/brand/favicon.svg
shared/frontend/design-system/brand/propertyscope-logo.svg
shared/frontend/design-system/brand/propertyscope-mark.svg
shared/frontend/design-system/brand/propertyscope-monochrome.svg
shared/frontend/design-system/components.css
shared/frontend/design-system/gallery.html
shared/frontend/design-system/shell.css
shared/frontend/design-system/tokens.css
shared/frontend/index.html
shared/frontend/mapping/mapping.css
shared/frontend/operations/ai-mode/app.js
shared/frontend/operations/ai-mode/contexts.js
shared/frontend/operations/ai-mode/index.html
shared/frontend/operations/ai-mode/polling.js
shared/frontend/operations/ai-mode/polling.test.mjs
shared/frontend/operations/ai-mode/styles.css
shared/frontend/routes/assistant.js
shared/frontend/routes/features.js
shared/frontend/routes/roadmap.js
shared/frontend/styles.css
student-1/backend/src/propertyscope_data_platform/assistant.py
student-1/frontend/app.js
student-1/frontend/components/pagination.js
student-1/frontend/components/states.js
student-1/frontend/core/router.js
student-1/frontend/index.html
student-1/frontend/integration/activity.js
student-1/frontend/routes/ai-diagnosis.js
student-1/frontend/routes/assistant.js
student-1/frontend/routes/properties.js
student-1/frontend/styles.css
student-1/tests/frontend/core.test.mjs
student-1/tests/unit/test_assistant.py
student-2/frontend/app.js
student-2/frontend/index.html
student-2/frontend/styles.css
student-2/tests/frontend/core.test.mjs
student-3/frontend/app.js
student-3/frontend/index.html
student-3/frontend/styles.css
student-3/tests/frontend.test.mjs
student-4/frontend/app.js
student-4/frontend/index.html
student-4/frontend/styles.css
student-5/frontend/app.js
student-5/frontend/index.html
student-5/frontend/styles.css
student-5/tests/frontend/buyer_cases.test.mjs
```
