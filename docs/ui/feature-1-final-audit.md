# Feature 1 final UI audit

## Recommendation

Ready for a laptop demonstration with documented low-risk exceptions. The reviewed source has no
known blocker or high-severity product defect in the Shared, Property Discovery or Data Operations
flows selected below.

This was deliberately a laptop-first release pass. It did not turn the prompt pack into a broad
mobile redesign, an exhaustive WCAG certification or visual-regression infrastructure.

## Final scope

- Shared Home, Property Search and Data Operations overview at 1440x1000.
- Shared Home, Property Search, Property Detail and Data Operations overview at 1024x768.
- Run Detail, Release Detail and AI Review Detail populated lifecycle cases at 1024x768.
- Deterministic form, navigation, retry, polling, stale-response, focus, disclosure and scroll
  regressions through the Feature 1 Playwright suite.
- Canonical repository formatting, lint, architecture, type, syntax, unit and component gates.

Mobile remains bounded-resilience evidence only. Brand/footer target sizing and full dense-table
parity are advisory; core navigation, search, dialogs and tasks remain protected by the existing
tests and audit policy.

## Evidence summary

| Surface | Viewport | Batches | Result |
| --- | --- | ---: | --- |
| Shared Home quick profile | 1440x1000 | 1 | Pass, no findings |
| Property Search quick profile | 1440x1000 | 1 | Pass, no findings |
| Operations overview quick profile | 1440x1000 | 1 | Pass, no findings |
| Shared Home populated cases | 1024x768 | 2 | Canonical pass; two native-input clipping false positives in the artificial long-input case |
| Property Search populated cases | 1024x768 | 3 | Pass, no errors |
| Property Detail populated cases | 1024x768 | 4 | Pass, no errors |
| Operations overview | 1024x768 | 1 | Pass, all 15 controls replayed |
| Run Detail populated lifecycle and partial feed | 1024x768 | 9 | Product states pass; one confirmation-overlay replay-path limitation |
| Release Detail populated lifecycle | 1024x768 | 11 | Product states render; nested-overlay replay and replaced-trigger focus limitations documented below |
| AI Review Detail populated lifecycle | 1024x768 | 5 | Pass, all 93 replay actions completed with no findings |

Local ignored evidence is under `.propertyscope-runtime/ui-audit/final-*`. It includes atomic batch
JSON, screenshots, `audit.json`, `index.html` and `TRIAGE.md` files. Paths in checked-in audit
configuration remain repository-relative; no local user or worktree path is required.

## Resolved high-impact findings

- Shared controls, dialogs, drawers, feedback and tables use native semantics and predictable
  focus/close behavior.
- Feature 1 forms are single-flight, retain values after server errors and guard only meaningful
  unsaved changes.
- Property Discovery ignores stale searches, keeps Back/Forward context and renders core facts
  before optional map/evidence feeds.
- Operations overview distinguishes partial from total dependency failure and does not present
  failed metrics as zero.
- Job and release lifecycle restrictions have visible reasons and context.
- Run polling preserves valid content, scroll, focused controls and disclosure state; independent
  evidence feeds degrade with bounded last-good data and explicit warnings.
- Generic retries pass through the normal title/heading focus lifecycle.
- AI result refresh and polling preserve disclosure state, restore refresh-control focus when
  appropriate and do not steal focus from outside the refreshed subtree.
- Changed browser modules use consistent cache keys, including the shared polling dependency.

## Audit limitations and low-risk exceptions

1. Native text inputs intentionally clip/scroll their very long value internally. The clipping
   heuristic reports the Shared header and hero inputs in the artificial long-input case even
   though the controls remain fully visible, focusable and editable and the page does not overflow.
2. Recursive overlay replay can assign an underlying disclosure as the setup path for a control
   inside an already-open confirmation dialog. The underlying element is correctly blocked by the
   modal, so Playwright times out. Direct dialog tests cover the real flow.
3. After a successful release edit the route replaces the old trigger and focuses the new page
   heading. The generic audit expects focus on the removed trigger and reports it as unrestored;
   the resulting focus location is deliberate and coherent.
4. The audit found that the running full-data frontend predated the Shared browser-module bind
   mount, while the child mountpoint was also missing beneath the read-only Feature 1 source bind.
   A tracked mountpoint now makes the Compose overlay valid. The scoped frontend recreation was
   verified healthy and `/features/data-platform/browser/index.js` returns JavaScript; backend,
   runner, database and named volumes were not recreated.

## Commands used

```text
uv run python scripts/check.py
uv run pytest student-1/tests/e2e/test_form_behaviour_playwright.py --no-cov -q
node --test student-1/tests/frontend/core.test.mjs
uv run scripts/dev.py ui-audit-quick --route-group <group> --viewport laptop-wide
uv run scripts/dev.py ui-audit-full --route <route> --scenario populated --viewport laptop-compact
```

The stacked pull requests also ran the canonical, Feature 1 browser and container CI jobs. The
behavioral stack ends at PRs 35 through 38, on top of the reviewed foundation PRs 28 through 34.

## Explicitly deferred

- exhaustive screen-reader/WCAG certification and broad 200%-400% zoom matrices;
- non-core mobile touch-target cleanup and operator table-card redesigns;
- permission/read-only states without an approved product contract;
- visual-regression baseline CI;
- speculative bundling, virtualization, map or polling architecture;
- additional dependencies, task runners or audit framework expansion.
