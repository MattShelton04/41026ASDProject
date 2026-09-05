# Shared and Feature 1 review — Improvements 55

Review date: 5 September 2026. Baseline: `f805178`.
Scope: Shared contracts, consumer transport, browser shell and AI services; Feature 1
frontend, HTTP boundaries, property discovery, ingestion and publication setup.
Other students' implementations are outside this change's ownership.

## Implementation plan

1. **HTTP failure correctness.** Stop the Feature 1 response adapter turning unreadable
   upstream bodies into successful JSON. Preserve valid Problem Details, correlation and
   legitimate no-content responses. Test malformed successes and failures without a network.
2. **Browser resource ownership.** Dispose table observers at Shared route replacement and
   Feature 1 search, run refresh and release-preview replacement. Close menu listeners when
   their table is disposed. Verify repeated operations return resources to baseline.
3. **Responsive search.** Cancel obsolete searches as the query changes, allow the corrected
   query immediately, and prevent old completion/pagination from changing the new result or
   its loading state. Keep mutation submission guards unchanged.
4. **Shell consistency.** Correct stale home availability copy and make repeated home-route
   binding idempotent. Verify navigation and normal-origin rendering in Shared/Feature 1.
5. **Verification and handoff.** Run the locked canonical gate, focused failure regressions,
   normal-origin form suite and Shared/Feature 1 audits. Retain a concrete review record,
   remaining concerns and validation limits. Commit coherent stages, push the requested
   branch and open a PR.

## Initial findings

| Priority | Finding | Effect |
|---|---|---|
| P1 | `http_support.forward` substitutes `{status: 200}` when upstream JSON cannot be decoded | A broken dependency can look like a successful empty collection or saved operation. |
| P2 | Shared routing does not dispose its table regions; Feature 1 disposes at hash navigation but misses inner replacements and polling | ResizeObservers retain removed tables during prolonged use. |
| P2 | Feature 1 action menus attach document/window listeners without a disposal hook | An open menu removed during navigation or refresh retains its DOM and listeners. |
| P2 | Property search uses the mutation-style single-submission guard | Editing a pending query invalidates its result but still blocks the replacement search until the old request finishes. |
| P2 | Release preview permits previous and next requests concurrently and replaces detached panels after completion | An older response can overwrite a newer page and create observers in a removed view. |
| P2 | Home listeners are rebound when a home anchor changes without replacing its DOM | Repeated navigation can attach multiple handlers to the same form. |
| P3 | Home copy says remaining research areas will appear despite five enabled cards | Availability guidance contradicts the manifest-driven directory. |

The existing design already has valuable safeguards: database ownership checks, strict generated
contracts, source streaming, bounded search candidates, durable cancellation, fenced import leases,
atomic accepted-generation activation and separate human publication approval. Improvements must
preserve these invariants; no new product rules or database technology are inferred by this review.

## Validation record

Pending implementation. The initial working tree was clean, the locked Python 3.12 environment
synced successfully, and the existing Docker stack reported healthy Shared and Feature 1 services.
The baseline canonical gate is being run before changes. Live inspection is read-only; browser
mutation tests use the dedicated deterministic fixture host.
