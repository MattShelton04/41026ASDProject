# Release 1 review decisions — 3 October 2026

Two independent agents assessed the current Canvas rubric: the
[report/evidence review](release-1-review-report-2026-10-03.md) and
[technical review](release-1-review-technical-2026-10-03.md).
They agree that selected MCP, cited RAG and insufficient-context paths work through all five
owning frontends/backends. They do not support an unconditional full-marks claim.

## Estimated marks and limits

Both reviews support 3/3 for setup, MCP, RAG, loop modes, Compose and report evidence, conditional
on the final readable, pinned PDF. The final local artifact now passes the guard and page review
at evidence baseline `efe8921`, with 2,785 words and 34 pages. Both estimate 2/3 for retained feature functionality and
integrated working software because Feature 2 context switching and Feature 4's native question
renderer remain defective. One assigns CI 3/3 under the precise MCP/RAG-only descriptor; the
other assigns 2/3 under the broader brief's instruction to disable AI-mode too.

The resulting assessable subtotal is **24–25/27**. Demonstration/Q&A remains **ungraded, 0–3**.
Attendance and participation were confirmed by Matthew; no additional attendance confirmation
is needed. These estimates are review judgements, not awarded marks or a guarantee.

## Improvements adopted

| Review finding | Change and validation |
|---|---|
| Full-viewport figures make source text too small | Capture native answer and citation-card screenshots; retain untouched viewport views and image hashes. Use large focused figures in the PDF. |
| Old report word exemptions exceed the brief | Count cover, captions, tables, fenced output and substantive appendices. Preserve Release 0's historical policy. Final guard enforces 3,000 words. |
| Quality requirements omit named qualities or mix quality/latency | Add measurable maintainability, interoperability and availability checks; separate retrieval recall from bounded tool deadlines and the observed retrieval sample. |
| Contributions are sparse or inaccurate | Date actual commits, link them directly and correct Feature 2/3/4 descriptions from Git evidence. Separate this branch's shared capture work from owners' feature work. |
| Citation evidence is not explicit in the PDF | Include a supporting passage/date/version card for each feature; link its full UI view and public run metadata. |
| F4 evidence can look official despite being seeded | Label the selected source-attributed constraints/buildings synthetic demonstrations. |
| Success claims obscure different validation boundaries | Keep provider captures, deterministic loop modes, live HTTP operations and fixture/browser tests distinct; record the exploratory F4 adaptation failure. |
| CI and deployment claims are stale | Retain verified baseline run URLs with their real SHA; refresh local status/probes and disclose the Student 5 AI-mode startup. |
| Wrapped known-issues bullets render out of order | Preserve list continuations in the Markdown parser; add a rendering regression and inspect the corrected PDF. |

## Remaining owner and human tasks

The [submission plan](../../release-1/submission-plan-2026-10-03.md) gives concrete acceptance
checks for Feature 2 case-switch context/history, Feature 4 generated-question rendering and
Feature 5 CI startup. Those changes are outside this branch's authorised Shared/Feature 1 scope.
Fixing and retesting them can address the identified technical deductions.

The presentation's unauthenticated watch page loads and its metadata reports 575 seconds.
Human review must still establish feature/terminal/loop coverage; the marker assesses Q&A quality.
The report does not infer that from attendance. Fresh persisted counts establish the listed
Feature 2/3/5 tables, while Feature 1/4 transient CRUD does not certify every assessed table's
ten-row requirement. Do not add artificial operational history to obtain that claim.

Final PDF/build and canonical quality-gate results are recorded in the accompanying
[verification record](release-1-verification-2026-10-03.md). All final pages must be inspected
before submission; a successful build alone does not prove readability or answer correctness.
