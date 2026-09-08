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

## Decisions and bounded follow-ups

- Keep the existing uv workspace, application factories, typed contracts, manifest projections,
  public browser barrels and isolated coverage gates. They are implemented and enforced; replacing
  them would add churn without demonstrated benefit.
- Do not extract every numeric literal: protocol status codes, documented limits and independent
  feature policy defaults are not automatically duplication. Centralize values only where multiple
  shared consumers require the same identity or policy.
- Retain feature-specific source/corpus registration and operations in their current explicit
  ownership. Generalizing them needs another approved consumer, not a speculative framework.
- No student slice edits, dependency upgrades, API schema changes, database migrations, provider
  calls, official data acquisition, Azure design or authentication product decisions are planned.
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

## Validation and implementation evidence

Baseline canonical gate is running. Final results, commit sequence, live observations and
independent code-review resolutions will be recorded here before handoff.
