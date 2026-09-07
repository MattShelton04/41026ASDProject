# Validation report

## Result at handoff

**Available checks pass; full-stack and canonical Python validation remain blocked.** No successful build, actual model run or WCAG certification is implied. The evidence uses real Chromium with production HTML/CSS/ES modules and isolated deterministic APIs, but the explicitly named injected-document profile has an opaque origin. All mutations were in disposable memory or canonical fixture responses, never external/production data.

## Source and environment baseline

The exact input archive SHA-256 is `d46612e3795da287bd48d40cfbf1fd20e23f22ed9441605c3e74f1165ba26ca8`. All 917 original archive files were byte-compared with the untouched extracted baseline and matched. Baseline commit `86b2ac8e69f31f39cf6ad4c5061e7e2e5fb8efef` was created before primary edits. Baseline Node tests: 195/195; available baseline architecture and style checks passed.

Available runtime: Python 3.13.5, Node 22.16 and Chromium through `/usr/bin/chromium` with Playwright. The project requires Python 3.12 `<3.13`. The interpreter could not be downloaded; Docker is absent and Flask/Ruff/mypy and parts of the full project toolchain were unavailable. No validator or dependency constraint was weakened to accommodate that environment.

## Commands attempted but not completed successfully

```sh
uv sync --locked --all-packages --all-groups
uv run python scripts/check.py
uv run scripts/dev.py ui serve
uv run scripts/dev.py ui smoke --all-routes
uv run scripts/dev.py ui audit quick
uv run scripts/dev.py ui audit full
uv run scripts/dev.py stack up --offline
```

The initial sync could not obtain Python 3.12. Final canonical attempts explicitly set `UV_PYTHON_DOWNLOADS=never` and returned exit 2, “No interpreter found for Python 3.12.” A direct Python fallback for the development stack reached the tool-catalog import and failed because Flask was absent; Docker was also unavailable. Model-registry/tool-catalog checks requiring that import are not reported as passes. Real-origin Chromium navigation failed with `net::ERR_BLOCKED_BY_ADMINISTRATOR`. Exact redacted command outputs are retained under `validation/`.

## Executed source checks

```sh
node --import ./scripts/frontend-test-bootstrap.mjs --test \
  shared/frontend/browser/browser.test.mjs \
  shared/frontend/dashboard.test.mjs \
  shared/frontend/ai-chat/ai-chat.test.mjs \
  shared/frontend/mapping/mapping.test.mjs \
  shared/frontend/operations/ai-mode/polling.test.mjs \
  student-1/tests/frontend/core.test.mjs \
  student-2/tests/frontend/core.test.mjs \
  student-3/tests/frontend.test.mjs \
  student-4/tests/frontend/core.test.mjs \
  student-5/tests/frontend/buyer_cases.test.mjs

python -m pytest -o addopts='' scripts/tests/test_ui_experience_fixtures.py -q
python scripts/generate_contracts.py --check
python scripts/generate_deployment.py --check
python scripts/validate_architecture.py
python scripts/validate_workspace_packaging.py
python scripts/validate_frontend_styles.py
git diff --check
```

**203/203 Node tests pass; 7/7 pure fixture tests pass; all five listed generation/architecture/style validators pass; Git whitespace checking passes.** The interpreter was supplied the repository workspace packages through `PYTHONPATH` for checks that do not need the missing full environment. Python compilation of the new QA modules and XML/viewBox/local-reference checks for all four SVGs pass.

The original `student-1/tests/unit/test_assistant.py` also produced **20/20 passes** through an import-isolation harness. It creates a package shell with the real source path to avoid executing the Flask application factory, then invokes the unchanged test file with `--noconftest -o addopts=''`. Actual domain validators are imported; HTTP/backend startup and the normal test fixture stack are not exercised. The exact harness and log are retained. This is explicitly not the canonical backend test suite.

## Browser matrix and results

| Check | Final retained evidence | Outcome |
|---|---:|---|
| Route/width matrix | 273 cases: 39 route examples × 7 widths | 0 page overflow; 0 capture exceptions; 0 failed required responses or external requests in the supported populated profile |
| Before/after comparison | 78 before + 78 after | All 39 examples at 390/1440px; after has 0 overflow and 0 capture exceptions |
| Degraded/long/large states | 462 cases: 33 examples × 7 scenarios × 2 widths | 0 final overflow, 0 page errors and 0 capture exceptions; expected error/empty HTTP responses retained |
| Property search rerun | 56 cases: 8 scenarios × 7 widths | Valid address query and denied-history recovery; 0 overflow or unhandled page errors |
| Long-table rerun | 21 cases: 3 routes × 7 widths | 0 overflow or unhandled page errors after wrapping fix |
| Safe workflow checks | 20/20 | Passed actual clicks/forms/keyboard/state assertions; no unexpected page error or overflow |
| Existing cross-feature smoke | 40/40 | Five feature frontends × empty/unavailable × 320/390/768/1440px |
| Sampled accessibility | 28 cases; 2,132 visible text measurements | No measured contrast failures, unnamed controls/fields or duplicate IDs; visible focus and reduced motion checked |

The primary widths are 360, 390, 430, 768, 1024, 1440 and 1728px. The state matrix uses 360/1440px, interaction flows 390×844px, and the legacy smoke adds 320px. Captures are full-page with a 1000px viewport height for layout probes.

**Profile limitations are not hidden by the table.** The route matrix has 21 limited captures (Home, F1 Source list and Source detail × 7 widths). Seven Home captures have the known opaque-origin HTMX “Invalid base URL” error. The final 78-case screenshot set has the corresponding six limited captures and two Home errors. Those three route examples are not functional passes. Baseline valid property search additionally fails its optional history write in the opaque profile; its baseline screenshot is labeled accordingly. The redesigned search continues safely.

The final state matrix records **171 expected failed HTTP responses**, status counts `{'404': 12, '503': 159}`. Deliberate API outages yield 503, and absent detail entities can yield 404. These are not silently converted to successful calls. The error fixtures are precisely why the UI’s recovery states can be inspected. A scenario does not necessarily alter every route; layout captures are distinct from verified business transitions.

## Reproducible browser commands

The fixture process was launched directly with the repository's local fixture server because uv could not start the supported interpreter. The following audit commands use its loopback port; they contain no production endpoint:

```sh
# Keep the fixture server in a separate terminal.
python -m scripts.ui_fixture_server --port 5300 --scenario populated

python -m scripts.ui_experience_audit --base http://127.0.0.1:5300 \
  --routes all --widths 360,390,430,768,1024,1440,1728 \
  --output .propertyscope-runtime/ux-matrix \
  --executable /usr/bin/chromium --injected-document

python -m scripts.ui_experience_audit --base http://127.0.0.1:5300 \
  --routes all --widths 390,1440 --output .propertyscope-runtime/ux-captures \
  --executable /usr/bin/chromium --injected-document

python -m scripts.ui_experience_interactions --base http://127.0.0.1:5300 \
  --output .propertyscope-runtime/ux-interactions \
  --executable /usr/bin/chromium --injected-document

python -m scripts.ui_experience_accessibility --base http://127.0.0.1:5300 \
  --output .propertyscope-runtime/ux-accessibility \
  --executable /usr/bin/chromium --injected-document

python -m scripts.ui_feature_smoke --injected-document \
  --chromium /usr/bin/chromium --output .propertyscope-runtime/ux-feature-smoke
```

`--injected-document` is opt-in; without it the new runners use real-origin navigation. In a supported local environment, start the canonical fixture server and prefer the real-origin profile. Select a platform-appropriate Chromium executable or omit that argument to use Playwright's installed browser. The 33 state-route names and exact scenarios are retained in `validation/states.json`; its command uses `--scenarios empty,slow,error,partial,long-content,large,validation-error --widths 360,1440`. It excludes the three HTMX-limited examples and the three assistant entry examples; degraded assistant transitions are exercised by the separate workflows.

## Workflow assertions

The final workflow report records valid property search and evidence disclosure under denied history; data-update preview/confirmation; candidate human-review context; keyboard menu open/Escape/focus; market case create/edit/modal containment/validation/assistant; distinct-locality comparison save/Cancel; missing-value trend rendering and validation; site review edit and saved question pack; buyer task/note/toggle/summary; shared composer, IME and duplicate prevention; failed-run preparation, polling outage, review-required, cancellation, provider rejection, invalid context, no evidence, guide outage; and storage-denied AI activity navigation.

F1 command/release browser fixtures do not persist a real accepted release. The fixture adapter's synthetic backend-shaped records are not backend integration evidence. Native browser dialogs are real; `page.on('dialog')` automatically accepts explicit JavaScript confirmations in this safe harness only. Unknown APIs fail loudly and no external production write is possible.

## Iteration and retained failures

An early matrix found nine pagination overflows; the pagination component was separated from dialog gutters. The final stress sweep then found three long-content mobile table overflows; arbitrary unbroken text now wraps in responsive data cells. A valid property query exposed a history write throwing before the data request; optional history storage is now guarded and a regression test plus 56-case rerun pass. The first full screenshot pass timed out on one capture during concurrent audit work; a bounded 20-second screenshot timeout and complete rerun produced zero capture exceptions. The prior reports are retained, with final rows explicitly annotated as targeted reruns rather than erased failures.

## Packaging verification

The apply bundle contains a binary Git patch, byte-exact before/after hashes, a verified standard-library payload fallback and a Python entry point. Its `verification.json` records actual fresh-snapshot checks, application, final-tree comparison, repeated-apply behavior and mismatch/integrity refusals. The full source ZIP and documentation are built from tracked final files, excluding Git metadata, secrets, environments, caches, local databases and downloaded dependencies. All original archive files remain unchanged. Package validation is separate from the unavailable canonical application test gate.

## What this does not prove

No full-stack, real-origin CSP/auth/cookie behavior, real HTMX source form workflow, GPU map rendering, live model behavior, Safari/Firefox or manual screen-reader/mobile-keyboard certification was performed. No independent subagent was available; separate self-review passes challenged the design, mobile behavior, evidence trust and code reuse. The remaining release checks are listed explicitly in [known limitations](11_KNOWN_LIMITATIONS_AND_FOLLOWUPS.md).
