# Release 1 verification — 3 October 2026

Branch: `Matt/Release_1_Report_Updates`. Scope: Shared/Feature 1, report generation,
evidence tooling and the root README. Feature 2/4/5 owner fixes remain in the
[submission plan](../../release-1/submission-plan-2026-10-03.md).

## Runtime observations

The existing `ps-dev` deployment was reused. No volumes were reset and no property dataset was
downloaded, published or replaced. All 20 Compose containers ran; the 18 with healthchecks were
healthy. AI-mode, MCP and RAG ran as host processes. Authenticated readiness passed.
Feature 3's registered authored guidance corpus was ingested explicitly into the existing RAG
index; all five registered corpora were ready afterward.

- [Service probe](../../release-1/evidence/live-service-probe.json),
  [Compose/host status](../../release-1/evidence/live-stack-status.txt) and
  [accepted-data counts](../../release-1/evidence/live-data-status.json).
- [MCP](../../release-1/evidence/validation-mcp.json) and
  [RAG](../../release-1/evidence/validation-rag.json) named validation modes succeeded with all
  four loop phases. Their decisions are deterministic; the transport and services are live.
- Seventeen browser scenarios produced 52 hash-verified images: five MCP answers, five cited
  RAG answers, five insufficient-context answers and two shared operations views. All 20
  focused answer/citation images were visually inspected. The owning-backend/provider run
  identity, MCP transport marker, citation version and insufficiency assertions passed.
  Three F4 captures identify code commit `bbcbd25`; twelve feature and two shared captures
  identify `937389a`. These are capture commits, not a claim that all artifacts were captured
  at the eventual PDF baseline.
- [Live operations](../../release-1/evidence/live-feature-operations.json) verifies the shared
  home, all five public frontends/APIs and owning persistence services. F1 source and F4 review
  audit records were created, read, updated and deleted, ending in 404. Other features were
  inspected read-only. This does not prove browser mutations for every feature or ten records
  in every assessed persistence table.
- The public [presentation](https://youtu.be/0Z0Rt146lD0) page was accessible; player metadata
  reports 575 seconds. Matthew confirmed all five participated in the 2 October showcase and
  that the tutor approved OpenAI/PostgreSQL. Playback coverage and Q&A quality were not graded.

## Deterministic checks

The complete `uv run python scripts/check.py` gate passed with exit 0 against the final code
(last code commit `09f0f21`). Formatting, lint, generated contracts/deployment, architecture,
packaging, model/tool configuration, frontend styles, JavaScript compilation and typing passed.

| Suite | Passed / skipped | Enforced coverage |
|---|---|---|
| Shared, AI and scripts | 1,143 / 7 | 90.84% ≥ 90% |
| Feature 1 | 882 / 72 | 75.96% ≥ 60% |
| Feature 2 | 34 / 0 | 81.17% ≥ 70% |
| Feature 3 | 112 / 1 | 86.64% ≥ 80% |
| Feature 4 | 89 / 0 | 90.22% ≥ 85% |
| Feature 5 | 184 / 0 | 83.57% ≥ 80% |
| Frontend JavaScript | 238 / 0 | Not coverage-gated |

Focused report engine/Release 0/Release 1 builder tests passed (40), as did capture tests
including actual Chromium toast settling (61). Narrow-container assistant browser checks and
the Shared frontend tests passed. These checks use fixtures or deterministic doubles; they
do not establish provider answer accuracy. The local diagnostic log is ignored at
`Temp/release1-handoff-quality-gate.log`; this table preserves the results without bundling
runtime output.

Optional disposable-PostgreSQL cases and platform-dependent tests are skipped by the canonical
gate when their explicit prerequisites are absent. Live owner-service operations above are a
separate integration observation, not a substitute for those optional fault/recovery tests.

## Report and review

The report has 2,785 counted words, including cover, captions, tables, fenced evidence and
substantive appendices. Generated contents and diagram pixels are excluded. There are no
unfinished author callouts or missing figures. Five rendered architecture/flow diagrams retain
matching source/asset hashes.

Two independent [rubric reviews](release-1-review-aggregate-2026-10-03.md) informed the rewrite.
The native answer and citation figures are readable at page size. The corrected 34-page draft
was rendered with Poppler; reviewers checked every page. The list-order defect found during QA
was corrected with an actual PDF text-order regression. Final baseline/build/hash and final
page inspection will be recorded here after the immutable evidence commit is created.

The final guard checks required sections, evidence identities, contribution commits, workflow
links and indexed local artifacts against their actual Git blobs at the selected baseline.
Passing it establishes these report checks; it does not award marks or validate the unseen Q&A.
