# Repository health review — PropertyScope Release 0

**Review date:** 5 September 2026
**Input:** `41026ASDProject-main-release-0.zip`
**Input SHA-256:** `83ed452768d2b6b701d7be03d16e6363eb566832a77cbbc98db755e58e6a6c36`
**Local baseline:** `72f2b06b486ccd75e47549ab521aaa6db7a69e1c` — an import of the supplied archive, not an asserted upstream GitHub commit.
**Working branch:** `review/health-and-consistency`
**Evidence convention:** Source references below use the delivered tree's line numbers unless marked “uploaded baseline.” They are reproducible code pointers, not external research citations.

## 1. Executive assessment

The repository has a stronger architectural foundation than its inconsistent feature implementations
suggest. It already separates shared agent contracts, framework-independent orchestration, HTTP
adapters, feature APIs and private database owners. There is an existing design-token vocabulary,
a public browser-barrel boundary, manifest-driven deployment and testing, and substantial deterministic
test coverage. Those are assets to preserve, not replace with a generic framework rewrite.

The largest cross-cutting weakness is **shared infrastructure without consistently shared behavior**.
The features use common colors but duplicate product headers, transport/error handling, cancellation,
polling and model/controller concerns. That duplication has already produced concrete failures:
timeouts ending at response headers, stale detail views, inconsistent request metadata, inaccessible
mobile navigation, and error states that overclaim available evidence.

This patch addresses those recurring defects and several independently important backend issues:
Feature 3's static-server path handling and request parsing, its optimistic-concurrency lost-update
reporting, and Feature 4's unsafe tool-input coercion and silent conversion of failed evidence into
empty evidence. It does **not** rewrite domain algorithms, merge private persistence owners, migrate
the application to a new frontend framework, or invent a production authentication design.

There are **39 implemented or partially implemented findings** in §4. R09 is explicitly partial.
The deferred/remaining register in §6 has concrete acceptance criteria. “Implemented” means the change
exists in the delivered tree; it does not mean every affected integration path was executable here.
The test evidence is stated separately for each finding and in §8.

**Merge recommendation:** review the shared transport and backend correctness changes first, then the
cross-feature shell. Run the repository's locked Python 3.12 quality gate and real-origin/Compose
checks before merging. This is a substantial, reviewable remediation patch, not a certification that
all possible defects in a roughly 105,000-line source inventory have been found or eliminated.

## 2. Scope, method and architecture

The uploaded archive was extracted into an untouched baseline and a separate editable copy. A local
Git baseline was created before changes. Review combined source inventory, large-module and exact
Python-function-body scans, architecture/manifest inspection, manual examination of high-risk request,
render and persistence paths, existing test execution, new regression tests, and rendered frontend
smoke checks. Exact duplicated function bodies are review leads, not proof that their ownership
should be merged. The inventory is broad; it is not a claim to have manually read every source line.

| Area | Ownership retained | Review emphasis |
|---|---|---|
| Shared frontend and edge | Product home, public primitives, routing/proxy boundary | Tokens, headers, requests, cancellation, accessibility lifecycle and asset delivery |
| Feature 1 — Property data | Acquisition, releases, discovery, its backend/database | Shared transport adapter, routing, table lifecycle, shell/CSP; remaining data-module debt |
| Feature 2 — Market intelligence | Cases, market evidence, assistant interactions | Request consistency, stale evidence, mutation guards, header and dependent CI |
| Feature 3 — Suburb analytics | Locality/crime evidence and comparisons | WSGI parsing, static/proxy boundary, concurrency, safe charts, calendar validation and fallback layout |
| Feature 4 — Due diligence | Site reviews, observations and question packs | Strict tool boundary, failure propagation, polling/map ownership, defaults and model split |
| Feature 5 — Buyer workspaces | Buyer cases, children, evidence and summaries | API/model split, actual read cancellation, error classification, dates and CI |
| Agent core / AI mode / shared contracts | Typed runs, tools, policy, durable orchestration | Architectural coupling and large-module risk; selected core tests; no provider/state-machine rewrite |
| Tooling, tests and deployment | Root quality gate plus feature-owned checks | All-feature discoverability, style ratchet, module bootstrap, action consistency, image/dev parity |

The intended dependency direction remains:

```text
Browser → owned feature API → owned database HTTP API → private database
                       ↘ shared AI-mode HTTP API → allowlisted feature tools
Shared browser primitives ← imported through public barrels by feature frontends
```

A common UI or transport does not grant Shared ownership of market evidence, due-diligence meanings,
buyer case state, or database schemas. The retained architecture validator still prohibits forbidden
cross-feature imports and database credential/volume leakage.

## 3. Measured changes and interpretation

| Measure | Uploaded baseline | Delivered state | Interpretation |
|---|---:|---:|---|
| Source inventory | 421 files / 105,066 lines | Not used as a shrinkage target | `.py/.js/.mjs/.css/.html`; excludes vendored code and docs, includes tests |
| Node behavior tests | 160 passing | 192 passing | 32 additional regressions; existing suite still passes |
| Selected Python tests | Not a full baseline gate | **466 passing** | Selected executable suites on Python 3.13; not supported-runtime/full-coverage proof |
| Cross-feature rendered smoke | No equivalent new five-feature matrix | 40 passing | Injected-document profile only; five features × four widths × two fixture modes |
| Feature 4 `app.js` | 946 lines | 816 lines | Pure model code now in a separate 187-line owned module; extraction adds interfaces/tests |
| Feature 5 `app.js` | 957 lines | 731 lines | API (68 lines) and models (231 lines) moved to owned modules; not deletion of domain behavior |
| Feature 1 `core/request.js` | 51 lines | 2 lines | Compatibility re-export rather than a copied lifecycle implementation |
| Feature 1 `core/api.js` | 82 lines | 39 lines | Thin domain adapter over common transport |
| Reviewed style exceptions | 325 entries / 517 occurrences | 322 entries / 508 occurrences | Wider all-feature gate; exceptions still need deliberate reduction |
| Superseded header/nav rule blocks removed | — | 56 | Actual old rules removed, not only hidden beneath new overrides |

Line counts describe organization, not business value or “clean-code scores.” Adding tests,
validation and safe error handling can legitimately increase total repository lines.

## 4. Implemented findings

Priority is contextual: **P1** is a correctness/security/reliability issue worth fixing before wider
usage; **P2** is material maintainability or UX debt. No P0 production incident is asserted.

### R01 · P1 · The timeout ended before JSON body consumption

**Status:** Implemented.

Shared, Feature 1 and chat could receive headers and then wait indefinitely for a stalled body. A fetch-only deadline was not a whole-request deadline.

**Change:** The common transport consumes JSON inside the request lifecycle. A stalled body reaches the same deadline as a stalled connection.

**Source:** `shared/frontend/browser/http.js:L30`.

**Verification:** Node regressions exercise delayed and unreadable bodies; all 192 Node tests pass.

### R02 · P1 · Cancellation depended on a cooperative operation

**Status:** Implemented.

An operation ignoring its AbortSignal could keep its caller waiting; a pre-aborted signal did not prevent work from being started.

**Change:** Reject pre-aborted work, race the operation against cancellation, deduplicate signal listeners, and remove timers/listeners on every exit.

**Source:** `shared/frontend/browser/request.js:L10`.

**Verification:** Node tests cover pre-abort, timeout, duplicate signals and a non-cooperative operation.

### R03 · P2 · Request/error plumbing was copied across frontends

**Status:** Implemented.

Features separately assembled headers, decoded JSON, classified network failures and propagated request IDs. A fix in one client did not reach the others.

**Change:** Introduce HttpProblem, requestJsonResponse and createJsonClient. Keep feature-owned API paths and compatibility error adapters rather than forcing one domain response envelope.

**Source:** `shared/frontend/browser/http.js:L4`.

**Verification:** Existing feature Node tests still pass; test-only ESM aliases use the real shared source.

### R04 · P1 · Headers and diagnostics could be lost

**Status:** Implemented.

Feature wrappers could replace default headers when callers supplied their own. Feature 5 collapsed transport problems into misleading database-unavailable errors or empty successful payloads.

**Change:** Merge headers case-insensitively, preserve caller request IDs/idempotency keys and retain status/code/cause. Unreadable JSON is an error; 204 is deliberately null.

**Source:** `student-5/frontend/api.js:L18`.

**Verification:** Node regression tests exercise header preservation, invalid JSON and the legacy ApiProblem adapter.

### R05 · P2 · Latest-selection logic had no common lifecycle

**Status:** Implemented.

A late request could keep running and retain permission to update a screen after selection or navigation changed.

**Change:** Add createLatestTask, combining actual cancellation with an isCurrent guard. Add cancellable delay and deadline-bounded read-only polling; do not retry writes automatically.

**Source:** `shared/frontend/browser/tasks.js:L17`.

**Verification:** Node lifecycle tests; full mutation reconciliation is a domain responsibility, not provided by abort.

### R06 · P1 · Market evidence could overwrite a newer selection

**Status:** Implemented.

Repeated evidence selection and assistant activity were not consistently invalidated when another case became active.

**Change:** Cancel old evidence/assistant tasks, pass their signal through transport, and guard state updates. Prevent repeated save/delete actions and keep modal failure feedback visible.

**Source:** `student-2/frontend/app.js:L16`.

**Verification:** Existing Feature 2 Node tests plus empty/unavailable mobile dialog smoke. Not full live CRUD.

### R07 · P1 · Due-diligence navigation and question polling could outlive their view

**Status:** Implemented.

A detail request or generated-question result could arrive after navigation; polling and map resources had fragmented ownership.

**Change:** Use separate route/question tasks, bound polling, guard updates, cancel on navigation/pagehide and destroy the prior map controller.

**Source:** `student-4/frontend/app.js:L13`.

**Verification:** Node tests and shell smoke; real long-running provider transitions remain a live-stack check.

### R08 · P1 · Buyer case reads, evidence and summaries could race

**Status:** Implemented.

Changing buyer cases or refreshing evidence could allow a previous asynchronous result to render against a new selection.

**Change:** Add view/evidence/summary task ownership. Forward AbortSignal through list, detail, child-list, evidence and summary reads; invalidate older renders.

**Source:** `student-5/frontend/app.js:L72`.

**Verification:** Node API cancellation regression plus shell smoke. Child mutation completion is not server rollback.

### R09 · P2 · Repeated initialization leaked listeners and observers

**Status:** Partially implemented.

Drawer rebinding and discarded table regions could retain listeners or ResizeObservers; feature toast timers could dismiss a newer message.

**Change:** Make drawer ownership idempotent with disposal, add disposeTableRegions, dispose Feature 1 route tables and clear/replace relevant toast/pagehide timers.

**Source:** `shared/frontend/browser/interactions.js:L168`.

**Verification:** Node tests cover common disposal. Nested Feature 1 re-render disposal still needs an owner-by-owner audit; see D08.

### R10 · P2 · Feature headers were five separate implementations

**Status:** Implemented.

Brand styling, product links, search placement and mobile behavior drifted despite existing shared tokens.

**Change:** Use one shared shell stylesheet and navigation implementation across all five features. Keep local feature routes, filters and business content feature-owned.

**Source:** `shared/frontend/design-system/shell.css:L4`.

**Verification:** 40 injected-DOM shell cases pass across five features and four viewport widths; normal-origin caveat applies.

### R11 · P2 · Product navigation disappeared or pointed to the wrong origin

**Status:** Implemented.

Some feature headers hid global navigation on mobile or used their own product-home rewriting logic.

**Change:** Keep all four product links visible, centralize integrated/standalone URL resolution and allow an explicit validated deployment home URL. Remove the duplicate Feature 1 link rewriting.

**Source:** `shared/frontend/browser/shell.js:L2`.

**Verification:** Node resolver tests; smoke checks all four hrefs and their visibility. Does not click through a real origin.

### R12 · P2 · Fixed header offsets broke wrapping/zoom layouts

**Status:** Implemented.

A fixed sidebar top offset could disagree with the actual height of a wrapped product header and workspace strip.

**Change:** Measure header/strip heights and expose shared CSS custom properties; clean up ResizeObserver on disposal. Add responsive focus/contrast rules.

**Source:** `shared/frontend/browser/shell.js:L30`.

**Verification:** Four-width smoke confirms no root overflow in its empty/unavailable fixtures, not every populated/zoomed layout.

### R13 · P2 · Shell consolidation risked adding another CSS override layer

**Status:** Implemented.

Leaving obsolete feature topbar/nav selectors in place would preserve hidden cascade conflicts.

**Change:** Remove 56 superseded header/navigation rule blocks. Keep feature styles only for feature content and use shared semantic tokens for missing colors/focus values.

**Source:** `shared/frontend/design-system/shell.css:L1`.

**Verification:** Semantic-style gate passes. Reviewed baseline now has 322 entries / 508 occurrences, not zero style debt.

### R14 · P2 · Light-header badges and mobile due-diligence spacing were inconsistent

**Status:** Implemented.

Legacy inverse-surface service badges became hard to read on the common light header; mobile layout left excessive blank space and a disproportionately large sidebar.

**Change:** Use semantic text/status colors for the common header; collapse secondary mobile chrome and anchor the due-diligence content grid at the start.

**Source:** `shared/frontend/design-system/shell.css:L81`.

**Verification:** Inspected final due-diligence mobile screenshot; mobile empty/unavailable smoke passes.

### R15 · P2 · Initial availability copy overclaimed evidence

**Status:** Implemented.

Property and due-diligence headers implied records were available before a request proved it; service health alone cannot establish complete evidence coverage.

**Change:** Start with neutral research/service wording. Due-diligence readiness reports Review service available, not a claim that all records or evidence are available.

**Source:** `student-4/frontend/app.js:L136`.

**Verification:** Product-shell assertions and browser fixtures; no real-data availability claim.

### R16 · P1 · Suburb map failure overflowed the mobile page

**Status:** Implemented.

A renderer failure exposed a large raw error/JSON string; the map layout had intrinsic sizing that caused severe horizontal overflow.

**Change:** Use bounded, user-facing fallback copy, allow the map/grid to shrink, wrap diagnostic text, and prevent generic input sizing from stretching map checkboxes.

**Source:** `student-3/frontend/app.js:L144`.

**Verification:** Observed failure in the harness, then reran all eight suburb shell cases with zero root horizontal overflow.

### R17 · P1 · Local static server paths were not contained

**Status:** Implemented.

Joining a request path to frontend/shared roots without resolving and checking containment could expose files outside the intended static surface. This server is loopback-only, so this is a local-development exposure, not a demonstrated remote production exploit.

**Change:** Decode/resolve safely, enforce root containment, reject dotfiles/backslashes/symlink escapes, allow only static suffixes and limit SPA fallback to eligible paths.

**Source:** `student-3/frontend/dev_server.py:L22`.

**Verification:** 18 tests cover approved/forbidden paths, symlink escape and proxy route allowlisting.

### R18 · P1 · The development proxy could misframe or truncate requests

**Status:** Implemented.

A min(length, limit) read silently truncated large bodies; malformed/negative lengths and unrestricted mutation paths were insufficiently handled. Oversized responses could be silently truncated.

**Change:** Reject malformed/chunked/oversized bodies, detect short reads, allow only the owned API/explicit health routes, cap responses with overflow detection and preserve HTTP error/request-ID information.

**Source:** `student-3/frontend/dev_server.py:L102`.

**Verification:** Source reviewed and syntax-checked; route allowlist tested. Dedicated byte-level proxy integration cases remain required (D11).

### R19 · P1 · WSGI request parsing could read the wrong amount or accept non-object JSON

**Status:** Implemented.

Duplicated parsers trusted Content-Length too broadly, including dangerous negative reads, and did not consistently distinguish truncation or JSON shape.

**Change:** Add a bounded framework-neutral read_json_object helper and use it at Feature 3 backend/database boundaries. Preserve each service's own Problem Details mapping.

**Source:** `shared/contracts/python/shared_contracts/wsgi.py:L10`.

**Verification:** 16 shared parser tests pass, including negative/malformed lengths, oversize, truncation and non-object JSON.

### R20 · P1 · Optimistic concurrency could report a losing update as success

**Status:** Implemented.

Feature 3 read an expected version and ran UPDATE ... WHERE version=?, but did not verify that the update affected a row. A concurrent winner could leave the losing request returning current data as though its save succeeded.

**Change:** Check cursor.rowcount and raise version_conflict when the conditional write loses. Reject bool/non-positive/non-integer versions.

**Source:** `student-3/database/src/propertyscope_suburb_store/repository.py:L538`.

**Verification:** Repository tests include a competing SQLite writer between the initial read and conditional update.

### R21 · P2 · Month/date strings could look valid without being real dates

**Status:** Implemented.

A YYYY-MM-shaped string is not sufficient calendar validation; JavaScript date normalization can turn an invalid due date into another date.

**Change:** Validate actual calendar months, month order and positive integer versions in saved suburb comparisons; round-trip buyer task ISO dates before accepting them.

**Source:** `student-3/backend/src/propertyscope_suburb_analytics/app.py:L59`.

**Verification:** Eight new comparison month/version tests and buyer model Node tests pass.

### R22 · P1 · Tool inputs were interpolated into internal paths before strict validation

**Status:** Implemented.

Due-diligence read-only tool endpoints coerced arbitrary input into a review ID, rather than enforcing the exact UUID-object contract declared by their tool catalog.

**Change:** Require the exact site_review_id object, reject additional fields/non-object values/invalid UUIDs, normalize the UUID, and return an explicit 422 problem.

**Source:** `student-4/backend/src/propertyscope_due_diligence/tool_inputs.py:L8`.

**Verification:** 11 pure validator tests pass. Additional Flask endpoint regressions were written but could not run here.

### R23 · P1 · Failed evidence could be presented as no evidence

**Status:** Implemented.

Due-diligence code decoded non-200 constraint/building responses and used .get("items", []), silently converting structured upstream failures into empty evidence.

**Change:** Relay non-200 evidence responses explicitly in deterministic evidence, map and AI-tool paths; only a successful response may be interpreted as an empty collection.

**Source:** `student-4/backend/src/propertyscope_due_diligence/api.py:L140`.

**Verification:** Endpoint regression tests added for failure propagation; execution blocked by missing Flask/Werkzeug. Pure tool validation is separately tested.

### R24 · P1 · Question generation could conceal a persistence failure

**Status:** Implemented.

A generated question pack could be rendered as though safely stored even when persisting it back to the review failed.

**Change:** Surface a warning that the pack could not be saved and require reconciliation; preserve the generated result without asserting durable success.

**Source:** `student-4/frontend/app.js:L360`.

**Verification:** Source inspection and existing frontend tests; authenticated/save-failure browser interaction remains unverified.

### R25 · P1 · Suburb HTML/SVG strings did not consistently escape attributes

**Status:** Implemented.

Labels inserted into rendered HTML/SVG could break markup when they contained quotes or untrusted text.

**Change:** Use the shared text/attribute escaping helper at interpolation boundaries and ignore non-finite numeric chart inputs.

**Source:** `student-3/frontend/app.js:L2`.

**Verification:** Node regression exercises the actual trend renderer with a malicious label; this is not a full XSS audit.

### R26 · P2 · A trend line could imply continuity across missing evidence

**Status:** Implemented.

Connecting points across a missing month visually implies a continuous observed series that the source does not establish.

**Change:** Extract a pure trend-path helper that starts a new segment after missing points, while keeping observed zero distinct from missing data.

**Source:** `student-3/frontend/trend.js:L1`.

**Verification:** Node trend gap, zero and non-finite-value tests pass.

### R27 · P2 · Shared default objects and malformed routes were fragile

**Status:** Implemented.

Mutating a returned default checklist could affect future forms; malformed percent-encoding or unknown hashes could interrupt routing.

**Change:** Clone due-diligence checklist defaults, catch malformed decoding in relevant routers and give suburb unknown routes a deterministic explore fallback.

**Source:** `student-4/frontend/models.js:L83`.

**Verification:** Existing/new frontend tests; suburb unknown-route fallback is exercised in the mobile smoke.

### R28 · P2 · Health vocabulary disagreed across feature clients

**Status:** Implemented.

A ready service returning healthy could still be labeled partial by a frontend expecting only ready.

**Change:** Accept the supported ready/healthy readiness forms without claiming that service readiness proves evidence completeness.

**Source:** `student-3/frontend/app.js:L362`.

**Verification:** Suburb fixture smoke; no live readiness timing/Compose validation.

### R29 · P2 · Two frontend controllers mixed pure models with orchestration

**Status:** Implemented.

Due-diligence and buyer app.js files combined validation/model projection, API clients, rendering, navigation and async orchestration.

**Change:** Extract Feature 4 models and Feature 5 models/API into feature-owned modules with compatibility exports. Their controllers shrink from 946→816 and 957→731 lines respectively.

**Source:** `student-5/frontend/models.js:L1`.

**Verification:** Existing behavior tests retained and updated to inspect/import the extracted implementation; total LOC is not claimed to fall by these controller reductions.

### R30 · P2 · New shared imports were not testable from feature source paths

**Status:** Implemented.

Browsers receive copied/mounted shared assets, but Node source tests cannot resolve those deployment-relative imports directly.

**Change:** Add a narrowly scoped test-only module resolver/bootstrap. It aliases only feature-local shared asset paths; production uses ordinary relative ES modules.

**Source:** `scripts/frontend-test-loader.mjs:L3`.

**Verification:** All 192 Node tests run through the bootstrap; it is not installed in production.

### R31 · P2 · JavaScript syntax checks omitted later slices

**Status:** Implemented.

The canonical source-root list covered Shared and Features 1–2, leaving Features 3–5 outside that syntax stage.

**Change:** Discover every student frontend for syntax checks, while retaining manifest-owned test enablement and excluding vendored sources.

**Source:** `scripts/check.py:L33`.

**Verification:** Canonical compile stage passes; test asserts all five app.js files are included.

### R32 · P2 · The semantic-style gate covered only Shared and Feature 1

**Status:** Implemented.

A shared design system is not enforced if later feature styles can add unchecked raw values.

**Change:** Expand style roots to all five features, reconcile real legacy exceptions and fix the newly surfaced values. The exception ratchet remains explicit rather than pretending legacy debt is gone.

**Source:** `scripts/validate_frontend_styles.py:L14`.

**Verification:** Style validator passes; baseline entries decrease from 325 to 322, occurrence counts from 517 to 508 despite broader scope.

### R33 · P2 · Default Python discovery/type-check configuration lagged feature enablement

**Status:** Implemented.

Root pytest testpaths omitted Features 3–5 and the canonical production mypy list lagged those slices. Note: canonical manifest-discovered feature test commands already existed; this was not a complete absence of feature testing.

**Change:** Add default testpaths and production type-check targets for later features; align first-party import classification and affected import blocks.

**Source:** `pyproject.toml:L51`.

**Verification:** Selected tests pass on Python 3.13. Full Python 3.12, mypy, Ruff and coverage ratchets remain unverified here.

### R34 · P2 · Shared changes did not consistently trigger dependent feature CI

**Status:** Implemented.

Features copied shared browser assets but some path-filtered workflows did not react to shared/frontend changes.

**Change:** Add Shared frontend triggers to Feature 2/3/4 workflows and use the common Node test bootstrap in feature jobs.

**Source:** `.github/workflows/student-2.yml:L8`.

**Verification:** Workflow YAML parses and consistency tests pass; GitHub-hosted execution was not performed.

### R35 · P2 · CI action/runtime pinning differed by feature

**Status:** Implemented.

Integration and some feature workflows pinned actions, while Feature 2/4/5 used moving action tags and relied on a runner-provided Node version.

**Change:** Reuse the exact checkout/setup-uv/setup-node action SHAs already used by the canonical workflow, pin uv consistently, disable persisted checkout credentials and explicitly install Node. Add bounded runtime/concurrency to Feature 2 and Feature 5.

**Source:** `.github/workflows/student-5.yml:L43`.

**Verification:** Eight workflow consistency tests pass. The pins are aligned to the repository's existing accepted configuration, not independently downloaded/verified here.

### R36 · P1 · Production/development asset projections could diverge after extraction

**Status:** Implemented.

Copying a new module into an image is insufficient when a development directory mount hides it. Shared browser, new extracted modules and shared contracts need matching runtime mounts.

**Change:** Update Feature 2/4 shared browser copies; include Feature 5 API/models/shell assets; ensure all feature shell entrypoints and Feature 3/5 extracted assets plus Feature 3 shared contracts are visible in development.

**Source:** `docker-compose.dev.yml:L1`.

**Verification:** Product-shell mount tests, packaging validator and deployment drift check pass; actual image builds/reload checks remain blocked by unavailable Docker.

### R37 · P2 · Shell bootstrapping risked violating CSP or barrel boundaries

**Status:** Implemented.

Inlining initialization or importing private shared files would sidestep the existing architecture/CSP contract.

**Change:** Add tiny feature-owned external shell.js entrypoints importing only browser/index.js. Keep the public barrel free of mounting side effects.

**Source:** `student-1/frontend/shell.js:L1`.

**Verification:** Product-shell tests assert external entrypoints/public imports for all five features; architecture validator passes.

### R38 · P2 · No small common five-feature visual smoke existed

**Status:** Implemented.

The sophisticated retained Shared/Feature 1 UI audit did not itself provide a compact, uniform empty/error shell check for every enabled feature.

**Change:** Add a separate deterministic Playwright matrix with fixture-only network access, sharding, four widths, empty/unavailable states and selected dialog/drawer interactions. Keep it outside the non-browser canonical gate.

**Source:** `scripts/ui_feature_smoke.py:L120`.

**Verification:** 40/40 injected-document cases pass, with zero uncaught page errors and zero root horizontal overflow in those cases. Normal browser navigation was blocked before app load.

### R39 · P2 · Shared browser documentation no longer matched actual responsibilities

**Status:** Implemented.

Documentation described a Feature 1-centric DOM helper surface, which encouraged more request/navigation duplication.

**Change:** Document the cross-feature transport/lifecycle/shell contract, cancellation semantics, module loading, cleanup, Node bootstrap and stronger/weaker browser profiles.

**Source:** `shared/frontend/browser/README.md:L1`.

**Verification:** Documentation and public export review; no claim that documentation alone proves runtime correctness.

## 5. How the common interfaces should evolve

### Transport and lifecycle, not a universal domain client

`requestJsonResponse` owns the mechanics that were repeatedly implemented badly: request metadata,
JSON decoding, total request lifetime and transport errors. Feature adapters still own their endpoint
paths, request/response models and user-facing domain errors. For example, Feature 5 keeps `ApiProblem`
rather than silently breaking its existing consumers. Feature 4's compatibility adapter preserves the
response-like interface used by its controller while delegating the actual I/O to Shared.

`createLatestTask` is deliberately small: start, cancel, a signal and permission to render. Its value is
not just aborting the fetch; it prevents a late completion from being rendered into another record's
view. The owner must still call `isCurrent()` before updating state. A browser abort is **not** an undo
request. The server may have committed a mutation or created a run before the browser stopped waiting.
Do not add automatic POST/PUT/DELETE retries without an explicit idempotency/reconciliation contract.

`pollUntilSettled` owns attempt and elapsed-time limits, not the meaning of “done.” Each feature declares
its terminal states and decides how to display completed, failed, timed-out or review-blocked runs.
Feature 2 still has its own bounded assistant loop; consolidating every poller was not necessary to fix
the demonstrated races and remains incremental work.

### Product shell, not one giant feature component

The shared shell is intentionally limited to product branding, global navigation, responsive geometry
and token-based header treatment. A market-case sidebar is not the same domain interface as a property
release workbench. Forcing both into a large configurable “feature shell” would replace visible CSS
duplication with a harder-to-maintain options matrix. The new shell removes common mechanics while
leaving each work area understandable to its owner.

A feature's three-line external `shell.js` bootstrap is intentional repetition at an ownership boundary,
not a second navigation implementation. It preserves CSP-compatible external scripts and the rule that
feature consumers use `browser/index.js`. Its corresponding Docker copy and development mounts are
part of the change, not a later deployment afterthought.

Next candidates for reuse are a common problem/empty-state presentation contract and small form-field
primitives with consistent label/help/error linkage. Before extracting them, identify at least two real
call sites with the same behavior. Avoid moving business-specific evidence labels or accepted-release
interpretations into Shared simply because their current HTML looks similar.

## 6. Remaining findings and recommended backlog

These are not hidden behind the “implemented” label. Some need domain decisions, some need a larger
migration, and some require the complete runtime to validate safely.

### D01 · P1 before non-demo deployment · Production identity and tenant isolation

Feature 5 uses a configured release0-demo-owner and server-side demo ownership. Internal tokens are service boundaries, not end-user authentication.

**Source:** `student-5/backend/src/propertyscope_buyer_workspaces/configuration.py:L8`.

**Completion criteria:** Agree an identity/authorization contract at the edge and feature APIs; derive the owner from authenticated identity, enforce it on every child/read/write/tool path, and test two users attempting cross-owner access. Keep demo mode explicitly separate. No authentication provider was invented in this patch.

### D02 · P1 merge gate · Supported runtime and complete verification

The full locked Python 3.12 gate, Ruff, mypy, Flask suites, coverage, Docker builds, Compose persistence and normal-origin browser behavior could not run here.

**Source:** `scripts/check.py:L156`.

**Completion criteria:** Run uv sync --locked --all-packages --all-groups and uv run python scripts/check.py, retain logs, then run normal-origin feature smoke and existing Compose/e2e commands. Fix newly revealed failures before merge; do not lower coverage thresholds to make this patch pass.

### D03 · P2 · Buyer-case pagination can hide records after page one

The frontend loads buyer cases and child collections with page=1/page_size=100; a sufficiently large workspace can therefore contain records that the UI cannot reach.

**Source:** `student-5/frontend/api.js:L36`.

**Completion criteria:** Implement explicit paging or cursor-based loading using the owned API metadata, with loading/error states and stable ordering. Seed more than 100 cases and more than 100 children; verify every record is reachable and filters do not imply a full-dataset search when they only filter the loaded page.

### D04 · P2 · Large data-platform modules still concentrate too many responsibilities

The largest unchanged production modules include Feature 1 repository.py (2,568 lines), import_profiles.py (1,794), runner.py (1,348) and release_builders.py (1,347). Size is a navigation/change-risk signal, not by itself a defect.

**Source:** `student-1/database/src/propertyscope_data_store/repository.py:L1`.

**Completion criteria:** Split by cohesive read/import/publication responsibilities behind existing facade methods. Characterize transaction/lease/publication invariants first; move one concern at a time and run PostgreSQL/PostGIS and ingestion/replay tests. Avoid reworking large stateful code without the database/runtime needed to verify it.

### D05 · P2 · Buyer backend API and shared agent runner remain large

Feature 5 backend api.py is 1,326 lines and agent-core runner.py is 1,232 lines in the baseline. Both mix multiple orchestration paths with high-cost invariants.

**Source:** `ai-services/agent-core/src/agent_core/runner.py:L1`.

**Completion criteria:** Extract pure transition/decision functions and owned route registration modules incrementally. Preserve idempotency, review, durable-run and tool-policy semantics. Run the Hypothesis state-machine suite and persistence/concurrency tests before claiming an architectural simplification is behavior-preserving.

### D06 · P2 · Python HTTP/problem contracts are still inconsistent

The browser transport is consolidated, but feature Python clients and Problem Details helpers still differ in timeout, error propagation and header handling. Some similar code is legitimate framework adaptation: Feature 3 is WSGI while other slices use Flask.

**Source:** `student-3/backend/src/propertyscope_suburb_analytics/clients.py:L1`.

**Completion criteria:** First share a small framework-neutral error/correlation contract and a transport conformance test suite. Extract only demonstrated common behavior. Keep Flask response construction and feature endpoint semantics in their owners; test unavailable, non-JSON, timeout and request-ID propagation at each boundary.

### D07 · P2 / architecture decision · Documented database interpretation disagrees with Feature 4 source

The living design describes a Feature 1-only PostgreSQL exception while Feature 4 has an actual PostgreSQL-owning store. This review does not infer that a new exception was formally approved.

**Source:** `docs/architecture/shared-platform-design.md:L213`; `student-4/database/src/propertyscope_due_diligence_store/repository.py:L1`.

**Completion criteria:** Have the feature/platform owner record the intended exception or migration decision and update the living topology, deployment expectations, backup/restore guidance and assignment evidence consistently. Do not “fix” this by moving credentials into the backend or silently switching database technology.

### D08 · P2 · Lifecycle cleanup is improved, not universally complete

The new common disposal APIs cover primary routes and controllers. Dynamic Feature 1 subview replacement and all existing pollers/observers still need a lifecycle ownership audit.

**Source:** `shared/frontend/browser/interactions.js:L168`.

**Completion criteria:** Instrument active timers, listeners and observers; repeatedly navigate, filter and reopen drawers/tables/maps. Assert counts return to baseline after disposal. Introduce a tiny route-disposal registry only when multiple remaining call sites justify it.

### D09 · P2 · Remaining CSS debt and accessible form/state consistency

There are still 322 explicit style exceptions, per-feature content rules, different empty/error forms and substantial imperative rendering. The common header does not establish full WCAG conformance.

**Source:** `docs/ui/frontend-style-baseline.json:L1`.

**Completion criteria:** Reduce exceptions by touched area rather than mass restyling. Audit populated states at 200% zoom, keyboard-only focus order, dialog return focus, screen-reader error linkage, forced colors and reduced motion. Add axe/manual assistive-technology checks without treating an automated accessibility score as proof.

### D10 · P2 · No repository-wide checked frontend contract layer

Plain JavaScript remains appropriate for this project, but domain payload expectations and optional fields can still drift between services and renderers.

**Source:** `student-5/frontend/models.js:L1`.

**Completion criteria:** Add JSDoc/checkJs or targeted generated contract types incrementally to model/API modules first. Keep runtime validation at trust boundaries. Do not start with a TypeScript/framework rewrite that obscures the current behavior and student ownership.

### D11 · P1/P2 validation follow-through · New negative-path tests need the complete execution environment

The Feature 4 endpoint regressions were written but not executed. The development proxy's framing/response limits were reviewed and syntax-checked, while its automated suite currently targets path containment/allowlisting.

**Source:** `student-4/tests/test_backend_api.py:L1`; `student-3/tests/test_dev_server.py:L1`.

**Completion criteria:** Run the Flask endpoint tests with the locked workspace; add socket-level proxy tests for negative/duplicate/chunked lengths, partial bodies, oversized upstream responses, preserved HTTP errors and correlation IDs. Confirm failed evidence never becomes an empty-success result in the real UI.

### D12 · P2 before distribution · Dependency/container supply-chain evidence is absent from this review

Action references now align with existing canonical pinned references. Image tags, dependency vulnerability status and transitive licensing were not independently audited; no CVE-clean claim is made.

**Source:** `.github/workflows/integration-ci.yml:L27`.

**Completion criteria:** Run a lock-aware dependency audit and container/SBOM scan in an appropriate environment, review findings against actual runtime exposure, and establish an update cadence. Use digest pinning where reproducibility requires it. Do not mistake actionlint for a security/dependency scan.

### D13 · P2 · Package imports couple pure submodules to application dependencies

Importing some package submodules eagerly imports the Flask application factory through __init__.py, complicating standalone validation and pure tests.

**Source:** `ai-services/ai-mode/src/ai_mode/__init__.py:L1`.

**Completion criteria:** Consider lazy application-factory exports or a neutral core package. Preserve existing public create_app imports and CLI discovery; add import-without-runtime-dependencies and application-factory compatibility tests before changing package initialization.

### D14 · P2 · Operational and business-evidence validation remains separate

Synthetic empty/error fixtures validate rendering mechanics, not statewide data completeness, evidence accuracy, valuation/statistical methodology, migration safety, backups or provider economics.

**Source:** `scripts/ui_feature_smoke.py:L3`.

**Completion criteria:** Keep retained real-stack evidence clearly versioned; test persisted CRUD across restart and failed-dependency recovery. Validate business claims with representative accepted data and feature owners. Run live provider checks only with explicit credentials, budgets and evidence recording.

## 7. Suggested follow-through order

**First: validate and merge the concrete correctness work.** Review R01–R08 and R17–R24, then execute
D02/D11 on the supported stack. These changes address hangs, stale views, boundary validation and
misleading success; they deserve priority over further cosmetic redesign.

**Second: review the shell in populated workflows.** Use real fixtures for all five features, not just
empty collections. Confirm navigation, focus, modal behavior, search/filter behavior, loading, errors,
map failure and narrow/zoomed layouts. Keep the shared header; adjust feature content without
reintroducing feature-local overrides for product navigation.

**Third: close bounded product gaps.** Pagination and explicit accessible empty/error/form states are
more useful than immediately decomposing every large module. D03 and D09 can proceed separately,
provided both agree on any new shared primitives.

**Fourth: decompose stateful modules with executable invariants.** Feature 1's data modules (D04),
Feature 5's route module and agent-core (D05) are separate work streams, but core orchestration changes
must not be mixed into an unrelated UI refactor. D06/D10 should begin as contracts/conformance tests,
not framework consolidation.

**Before any real multi-user exposure:** close D01, confirm deployment secrets/TLS/CSP and tenant
boundaries, and record the database decision in D07. The current demo architecture must not be
implicitly rebranded as production-ready.

## 8. Verification record and limitations

### Executed successfully

- **192 Node behavior tests** using the repository's test-only module bootstrap, including the
  original 160 tests and 32 new regressions.
- **466 selected Python tests**, including Shared contracts/consumer protocol, agent-core except its
  Hypothesis state-machine file, executable scripts tests, the complete Feature 3 test directory and
  Feature 4's pure tool-input validator. Executed with available Python 3.13.5 and installed packages,
  not the project's locked Python 3.12 environment.
- Generated contract and deployment **drift checks**, architecture boundaries, workspace/Docker
  manifest packaging validation and semantic-style validation.
- The canonical first-party JavaScript syntax stage and AST parsing of **315 Python files** with the
  available interpreter. Parsing is not type checking.
- **40 rendered browser cases**, sharded by feature: 320/390/768/1440 px, empty/unavailable fixtures,
  four visible product links with expected targets, no root horizontal overflow and no uncaught page
  errors. Selected mobile dialogs/drawer Escape and unknown-route fallback were also exercised.
- `git diff --check` for whitespace integrity.

The selected Python command was:

```sh
python -m pytest -p pytest_cov --no-cov \
  shared/contracts/tests shared/consumer-protocol/tests \
  ai-services/agent-core/tests scripts/tests student-3/tests \
  student-4/tests/test_tool_inputs.py \
  --ignore=ai-services/agent-core/tests/test_state_machine.py \
  --ignore=scripts/tests/test_ui_audit_browser.py \
  --ignore=scripts/tests/test_source_scale_benchmark.py \
  --ignore=scripts/tests/test_ui_fixtures.py \
  --ignore=scripts/tests/test_validate_tool_catalogs.py
```

This environment-specific command used source-package paths on `PYTHONPATH` and disabled unrelated
pytest plugin autoloading. It is recorded for provenance, **not** offered as a replacement quality gate
or recommended local installation. The normal user command remains `uv run python scripts/check.py`.
No repository Python requirement, lockfile or coverage threshold was weakened to accommodate this
review environment.

Node tests were selected from the same `scripts.check.test_commands()` metadata used by the canonical
runner, taking its Node command, and were not replaced by a hand-picked assertion subset.

### Blocked or not executed

The locked environment setup failed because Python 3.12 could not be downloaded in the container's
network environment. The available interpreter was 3.13.5. Flask/Werkzeug, Hypothesis, Ruff, mypy,
PostgreSQL drivers and some other locked dependencies were unavailable. Consequently the **complete
quality gate is not certified passing**. In particular, Feature 4 Flask endpoint tests, most other
feature backend suites, AI-mode provider/persistence suites and coverage thresholds were not run here.
The model registry validator also stopped at an eager Flask import; the model registry and tool
catalog validators therefore have no successful full-environment result from this review.

Docker was unavailable. No claim is made about successful image builds, Compose service readiness,
real database migrations, persistence across restart, API-to-DB integration outside the executed
Feature 3 tests, or live OpenAI/Gemini behavior.

Normal Chromium navigation was blocked before application load by the installed browser's managed URL
policy (`ERR_BLOCKED_BY_ADMINISTRATOR`), including localhost. The final browser result uses the explicit
`--injected-document` profile: production HTML/CSS/modules with intercepted fixture APIs in
`about:blank`. Its CORS relaxation exists only inside the test harness. This profile cannot validate
origin-dependent routing, CSP, cookies, storage persistence, authentication or service workers. It is
useful rendering/interaction evidence, not a substitute for normal-origin e2e. External map/provider
requests were blocked; map fallback was tested, not successful external tile delivery.

The screenshots are current fixture renders, not visual-regression comparisons against an approved
baseline. The smoke asserts uncaught page errors, not a universal absence of browser console warnings.

### Required local merge gate

```text
uv sync --locked --all-packages --all-groups
uv run python scripts/check.py
uv run playwright install chromium
uv run python -m scripts.ui_feature_smoke --output .propertyscope-runtime/feature-smoke
uv run pytest student-1/tests/e2e/test_form_behaviour_playwright.py --no-cov -q
uv run scripts/dev.py stack doctor
uv run scripts/dev.py stack build
```

Then run the existing feature/Compose smoke commands and persistence checks described in the
feature READMEs/workflows. Inspect any formatting/type failure rather than assuming it is unrelated
or automatically suppressing it. Run the normal-origin smoke without `--injected-document`.

## 9. Patch handoff and safety

The deliverables contain an aggregate Git patch plus a standalone Python application script. The
script checks its patch checksum, requires a clean Git worktree/index, verifies the **content** of
all touched baseline files against the supplied archive, rejects new-path collisions and performs
`git apply --index --check` before changing the tree. It can create a new branch after preflight, then
stages the patch for review. It does not commit, push, reset, delete local work or change the source
archive. Its baseline is content-addressed: your upstream commit ID does not have to match the local
import commit created for this review.

Keep the extracted patch bundle **outside** your repository. From any directory:

```text
python /path/to/propertyscope-review-patches/apply_review.py --repo /path/to/project --check
python /path/to/propertyscope-review-patches/apply_review.py --repo /path/to/project --branch review/repo-health
```

Omit `--branch` to apply to your already-created branch. Inspect `git diff --cached`, run the full
validation above, and commit deliberately. The bundle README records preflight behavior, drift
handling, manual application and rollback guidance. Applying only part of this change is not advised:
frontend imports, copied assets, development mounts and the Node bootstrap must move together.

There are no database schema migrations in this patch. The original upload is untouched, and a
separate modified-source archive is provided for comparison or experimentation. A local Git bundle
is also provided for reviewing the imported baseline and remediation history; it is not an upstream
repository clone and contains no claim about upstream branch history.
