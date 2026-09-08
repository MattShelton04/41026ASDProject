# Shared setup audit and refinement

Date: 8 September 2026. Branch: `Matt/Shared_refinement_xyz`.

## Scope and method

Review the shared packages, AI service integration, developer launcher, quality runner,
Compose/CI wiring and maintained documentation. Preserve student-owned implementations and
existing service/database ownership. This is a source and deterministic regression audit,
supplemented by local runtime checks where available; it is not a claim that all possible
defects or future product requirements have been exhausted.

The starting tree was clean. Read the root README, CONTRIBUTING, shared-platform design and
area guides. Inspect configuration and transport call sites against their tests, run the
canonical baseline, obtain an independent plan review, implement focused commits, and obtain
a different independent code review before the final gate and PR.

## Findings and implementation plan

| ID | Priority | Evidence and consequence | Planned correction and acceptance |
|---|---|---|---|
| S1 | High | `shared/tool-runtime/src/shared_tool_runtime/http.py` configures redirect rejection only on its owned client. An injected `httpx.Client(follow_redirects=True)` can follow an unapproved destination before the response check. | Pass `follow_redirects=False` per invocation. Prove that a redirect-enabled injected client sends exactly one request and returns `tool_redirect_rejected`. Preserve client ownership. |
| S2 | Medium | HTTP tool response decoding catches transport exceptions but not `httpx.DecodingError`; malformed compressed upstream data can escape the typed tool-result boundary. | Map decoding failures to a safe, non-retryable typed invalid-response error without upstream text. Test a real malformed encoded response through MockTransport. |
| S3 | Medium | `scripts/devtools/ai_runtime.py` independently parses saved JSON in three readers and assumes keys/types. Truncated JSON, arrays, missing keys and non-string values produce uncaught exceptions during lifecycle commands. | One validated saved-state reader, strict placement/mode checks, actionable errors preserving the original file. Never infer a different owner from corrupt state. Exercise readers and the public CLI before any process mutation. |
| S4 | Medium | Host, container and launcher code repeat AI service identities/ports; host preparation accepts an unknown mode as silently disabled capabilities. Host and container entrypoints also duplicate the exact AI token authentication implementation. | Extract a small dependency-light runtime settings module and reuse the existing authentication boundary. Validate capability modes before filesystem/process effects. Keep fixed internal container ports distinct from configurable host exposure. Test parity and invalid-input rejection. |
| S5 | Medium | `scripts/check.py` discovers only `*.js`, even though onboarding accepts `.mjs` and `.cjs`, and computes compile discovery for unrelated stages. Shared Node tests require a manually maintained list. | Discover first-party `.js`/`.mjs`/`.cjs` under frontend roots and tooling modules, exclude vendor, discover Shared `*.test.*` files, retain manifest-owned feature tests, and evaluate only requested stages. Test temporary trees and unrelated-stage isolation. |
| S6 | Medium | `integration-ci.yml` validates base and development Compose only. The optional AI overlay is a supported fresh-install default but is absent from the integrated Compose config check. | Add a configuration-only check including `docker-compose.ai.yml` and its profile, with regression coverage. Do not launch MCP/RAG in CI or require runtime secrets. |
| S7 | Medium | `ai-services/README.md` calls implemented MCP/RAG placeholders; architecture sections 6 and 16 say no AI Compose definitions exist; section 6.4.1 says only Feature 1 is enabled. The architecture coverage target says 85% while the gate enforces 90%. | Reconcile maintained guidance with manifests, runtime code and the gate. Preserve the explicit host assessment requirement, optional Docker development placement and future Azure/multi-agent distinction. Link this audit from the docs index. |
| S8 | High | Live `stack down` returned success but left `ps-dev-shared-ai-mode-1` healthy and its network in use. `_down()` selects only `release-0`; Docker AI services belong to `ai-container`. It then removes the provider secret despite leaving its consumer running. | For Docker placement, add the AI profile to the shutdown composition before `down`. Keep host shutdown unchanged. Test direct and combined modes and volume-preserving flags; rerun live shutdown and verify no project containers remain running. Do not use volume reset for validation. |

## Decisions and bounded follow-ups

- Keep the existing uv workspace, application factories, typed contracts, manifest projections,
  public browser barrels and isolated coverage gates. They are implemented and enforced; replacing
  them would add churn without demonstrated benefit.
- Do not extract every numeric literal: protocol status codes, documented limits and independent
  feature policy defaults are not automatically duplication. Centralize values only where multiple
  shared consumers require the same identity or policy.
- Retain feature-specific source/corpus registration and operations in their current explicit
  ownership. Generalizing them needs another approved consumer, not a speculative framework.
- No student slice edits, dependency upgrades, API schema changes, database migrations, paid model
  generation, official data acquisition, Azure design or authentication product decisions are planned.
- Live environment inventory initially shows no running Compose project. Validate Compose and
  attempt the documented offline workflow after source changes; record any startup limitation.
- HTTPX phase timeouts are not strict total wall-clock deadlines. Review the surrounding executor
  cancellation behavior before changing it; do not claim this audit creates hard process isolation.

## Independent plan review

Reviewer: `validate_plan`, an independent read-only subagent. All S1–S7 were confirmed.
Accepted refinements before implementation:

- S3 validates saved state before any `stack up` effects, including explicit CLI/environment
  placement overrides; handles invalid UTF-8 and read errors without exposing file contents.
  Recovery requires restoring a known owner/mode, never silently deleting state or guessing.
- S4 adopts the container's stronger 32–128 URL-safe token validation for both entrypoints and
  a common unauthorized response. The initial description of the implementations as exact
  duplicates was inaccurate: the host accepted any nonempty token and used different detail text.
  New settings/auth modules must be explicitly copied into the AI image and importable without
  host-only modules. Verify fixed Compose-port parity without generating a new topology framework.
- S2 uses streamed malformed gzip bytes to exercise decoding inside the executor, and retains
  a valid compressed-response success case.
- S5 excludes vendor/dependency directories, proves automatic Shared test discovery, retains
  feature-manifest ownership, and updates the scripts guide.
- S6 validates all four overlays with both profiles, without generated credentials or env files.
- S7 also corrects diagram labels and sections 6.3/6.5 and obsolete feature implementation claims.

No substantive finding was rejected. No extra domain scope or speculative abstraction was added.

S8 was added after live shutdown verification, following the initial code review. `validate_plan`
independently confirmed the still-running AI container and approved the narrow shutdown-only
profile correction. Accepted its additional checks for both capability modes, host placement,
ordinary/reset volume flags, argument ordering, no remaining stopped containers, and retained data.

## Validation and implementation evidence

Implemented S1–S8. Focused commits:

- `2500607`: independently validated audit and plan.
- `b385c78`: tool redirect enforcement and typed decoding failures.
- `dfa9d34`: saved-state validation, shared settings/authentication and image packaging.
- `9a7f646`: JavaScript/test discovery and full Compose CI validation.
- `35bb0df`: maintained runtime guidance and semantic CI projection invariant.
- `4a59282`: include all Docker AI owners in normal stack shutdown.

Validation completed so far:

- HTTP tool regressions: 16 passed, including redirect-enabled injected clients, preserved
  client ownership, malformed streamed gzip and valid gzip.
- Runtime/lifecycle/container/developer tests: 135 passed. Includes invalid state and explicit
  switches before effects, authentication parity, fixed port parity and imports from the actual
  Dockerfile-selected scripts in an isolated directory.
- Quality-runner/workflow tests: 21 passed, including source suffixes, dependency exclusion,
  automatically included Shared tests and manifest-owned feature tests.
- `stack doctor`: Docker Engine and Compose available; deployment inputs valid.
- Four-overlay `docker compose ... --profile release-0 --profile ai-container config --quiet`:
  passed both in the checkout and in a temporary directory containing only those Compose files,
  with no `.env`, generated runtime env files or provider credentials.
- `stack up --offline`: passed; all enabled feature services started. `stack rebuild
  shared-ai-mode --offline`: passed; rebuilt image and recreated AI-mode reached healthy.
- Rebuilt image entrypoint imports: passed with `docker run --rm --network none`, no bind
  mounts, and assertions that host runtime/deployment configuration modules were not imported.
- Real HTTP boundary: direct AI liveness 200, direct unauthenticated history 401, shared proxy
  history 200. Post-shutdown inspection found S8: the feature containers stopped but AI-mode
  remained running. The initial successful command exit alone did not prove complete shutdown.
- Script Chromium suite: all 11 canaries passed independently.
- S8 AI/dev regressions: 94 passed, including eight combinations of placement, capability and
  volume flags. Corrected live shutdown: no project containers remain in `docker ps --all`;
  the exact labelled named-volume set and AI history database file are retained.
- Integrated browser, real `http://localhost:5100` origin: shared home loaded all five research
  areas; status reported every feature API ready, AI degraded and MCP/RAG deliberately disabled.
  After rebuilding, the shared proxy loaded retained activity history and reported persisted
  state connected. These were read-only observations of existing records, not new model runs.
  Offline readiness can still probe the provider using its dummy credential; no paid model
  generation or external data acquisition was performed.

The first baseline gate passed static stages but its test process exited with code 1 without a
failure report. Its last reported file, `test_ui_audit.py`, passed independently (10 tests).
The first implementation gate caught one strict-mypy import-export error; the launcher now imports
placement settings directly from their owning module. The next gate reached 90.84% core coverage
with 913 passed, one skipped and one stale CI assertion failing. That assertion counted exactly
two Compose checks; it now verifies that every Compose check includes the enabled projection
(all seven naming tests pass). The corrected S1–S7 gate subsequently passed completely,
followed by a successful complete rerun including S8.

Final `uv run python scripts/check.py`: **exit 0** on implementation commit `4a59282`.
Formatting, lint, contract/deployment drift, architecture, workspace packaging, model/tool
catalogues, styles, strict typing, JavaScript syntax and every test stage passed.

| Test stage | Passed | Skipped | Coverage | Required |
|---|---:|---:|---:|---:|
| Shared / AI / scripts | 922 | 1 | 90.84% | 90% |
| Feature 1 | 684 | 36 | 74.09% | 60% |
| Feature 2 | 24 | 0 | 79.78% | 70% |
| Feature 3 | 104 | 1 | 91.29% | 80% |
| Feature 4 | 83 | 0 | 90.02% | 85% |
| Feature 5 | 136 | 0 | 82.63% | 80% |
| Node behavior | 209 | 0 | Not measured | All pass |

Totals: **1,953 Python tests passed, 38 skipped; 209 Node tests passed**. Skip reasons are
listed below. Final evidence-only documentation updates do not change the validated implementation.

The full gate also exposed documentation drift about browser coverage: script-level Chromium
canaries run when the executable is installed, although CONTRIBUTING claimed all browser tests
were excluded. Corrected the guide; feature e2e suites remain separate. No tests were removed or
coverage thresholds reduced.

## Independent code review and resolution

Reviewer: `review_implementation`, a different read-only subagent from the plan reviewer.
Reviewed committed and uncommitted changes against `main`, confirmed completion of S1–S7 and
ran 133 focused tests successfully. No actionable code defect was reported. The requested
follow-up was to complete this evidence record. The primary agent validated that review against
the diff, the full-gate results and actual container/browser checks. The stale Compose-count test
found by the broader gate was corrected as described above; no reviewer suggestion was accepted
without checking its evidence.
The reviewer then checked the corrected CI invariant, CONTRIBUTING browser guidance and evidence
record and again reported no actionable finding.
After S8, the same code reviewer independently passed all eight shutdown regressions and confirmed
profile placement, host behavior, volume flags and cleanup ordering without further findings.

HTTPX API behavior was checked against the [official client API](https://www.python-httpx.org/api/)
and [exception hierarchy](https://www.python-httpx.org/exceptions/), then exercised through the
locked local dependency. `DecodingError` is distinct from `TransportError`, and redirects can be
overridden per streamed request.

## Remaining validation boundaries

- The canonical run skips 36 Feature 1 PostgreSQL integration cases because no disposable
  test database URL is configured. Existing application data is not a disposable test target.
- Two symbolic-link tests skip on this Windows account because link-creation privileges are
  unavailable. No elevated execution or test bypass was introduced.
- Feature-specific e2e matrices, real model generation, semantic retrieval evaluation, official
  source acquisition, cloud deployment and hosted GitHub Actions execution are separate evidence.
  No claim of those outcomes follows from the local gate or read-only browser checks.
- Live shutdown was exercised in Docker direct mode. Deterministic tests cover host/Docker and
  direct/combined shutdown, and image imports/configuration cover all AI entry modules. A live
  combined MCP/RAG run or host/Docker transition was not needed for this bounded change.
- The final branch is based on the fetched `origin/main` with no missing upstream commits.
