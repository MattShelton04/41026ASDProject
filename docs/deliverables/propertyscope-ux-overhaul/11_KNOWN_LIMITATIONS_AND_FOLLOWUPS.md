# Known limitations and follow-ups

## Unverified release-critical integration, not cosmetic future work

**Canonical Python environment.** The repository requires Python 3.12 with `<3.13`; only 3.13.5 was available and the required interpreter could not be downloaded. Flask, Ruff, mypy and some other project dependencies were unavailable. The canonical `uv run python scripts/check.py` did not run successfully. Available generation, architecture, style, Node and isolated pure tests passed, but are not a substitute for the complete gate. Formatting/type checking and the full backend test suite must run in the supported environment before release.

**Integrated stack.** Docker is absent. The canonical offline stack command was attempted, but no production-like stack could start. No real service-to-service workflow, persistent database mutation, auth, cookie behavior or deployed edge configuration was validated. Browser fixtures were deliberately isolated from any production data.

**Real-origin browser navigation.** Chromium loopback navigation returned `net::ERR_BLOCKED_BY_ADMINISTRATOR`. Production HTML and modules were instead exercised in the repository’s explicitly weaker injected-document profile. It cannot prove CSP, origin, storage or HTMX behavior under actual deployment. Shared Home and Feature 1 Source list/detail have opaque-origin/Flask-fragment limitations and are not counted as functional passes. Their source changes preserve existing CSP and HTMX ownership rather than bypassing security checks to make a test green.

**Map rendering.** WebGL/GPU rendering was unavailable. Map alternatives, controls, source context and responsive layout were inspected; genuine basemap tiles, geometry, panning and popup positioning over a working map remain unverified. No invented static map was substituted.

**Live AI.** No live-provider turn was performed and no secret was required or exposed. Recorded fixture states cover normal and degraded UI behavior. They do not prove provider behavior, model answer quality, full durable backend persistence or real cancellation propagation. Existing model/tool boundaries remain unchanged.

## Coverage limits of the evidence

The route matrix contains representative examples for every implemented route family discovered, not every possible entity, query, permission state or state transition. Repeated route/scenario captures are layout probes; a scenario can be a no-op for a route that does not consume that data. Validation-error recovery needs an actual mutation interaction, which is tested separately. Empty detail 404s and deliberately failed 503s are expected, recorded failures—not successful network calls.

No independent subagent facility was available. Inventory, design, keyboard/mobile, trust and code-health challenges were separate **self-review passes**, followed by source/browser verification. They should not be described as an independent external audit.

Manual assistive technology, Safari/Firefox, real mobile keyboards, forced colors and complete non-text contrast checks remain necessary. A zero-overflow measurement and a zero-failure sampled contrast report do not certify WCAG compliance. The footprint measurement is source bytes, not a performance benchmark.

## Deliberate product boundaries, not unfinished integrations

The redesign does not create a universal property entity graph, automatically synchronize market/site/buyer cases, or give one assistant every feature’s tools. Cross-feature navigation is clearer, but scope and handoff remain constrained by real contracts. The buyer summary’s local ID is deliberately not linked to a global agent run. Source attribution and unknown coverage are shown, not repaired through fabricated data.

Feature-specific renderers remain where independent deployability and ownership justify them. Public tokens/primitives unify their expression; domain logic is not centralized merely to reduce file count. An unimplemented dark theme, a floating chat bubble and decorative view transitions are not outstanding bugs in this delivery.

## Recommended release sequence

Use the manifest-verified apply package on the exact original snapshot, then run the canonical source gate under Python 3.12. Start the canonical offline Compose stack in an environment with Docker; repeat all-route smoke/audit on a real origin and exercise Source create/edit/validation/dirty-close flows. Validate maps with working WebGL, then perform a bounded live-provider turn only with an explicitly safe credential and data environment. Finish with assistive-technology and real mobile-device checks before asserting a production-ready or accessibility-certified release.
