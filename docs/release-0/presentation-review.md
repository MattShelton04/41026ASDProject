# Independent presentation-pack review

Reviewed 3 September 2026 in the isolated presentation worktree. Scope: the timed
script, recording runbook, Feature 1 rubric assessment, rehearsal JSON and
student-owned presentation checklist. This is a document/evidence review, not a
claim that the final video, report or integrated acceptance recording exists.

## Verdict

The proposed sequence covers the assessed video requirements: shared entry,
Feature 1 CRUD, feature-frontend AI, Docker deployment and successful student CI.
The property/map/ABS walkthrough gives those requirements a coherent example.
Supporting report deliverables have explicit destinations. The plan correctly
keeps agentic-loop execution out of the video under the 30 August clarification.

The 1:00 and 1:45 allocations are achievable as edited recordings with continuous
narration. They are not measured human rehearsals. In particular, the published
release, CRUD and CI shots need deliberate cuts and readable outcome dwell time.

## Findings raised for the preparation agent

| Finding | Required correction / verification |
|---|---|
| The original runbook said six Feature 1 windows while the script had seven. | Say seven and keep the shot schedule aligned with the script. |
| The 12-second published-release window originally included navigation, summary, checks and preview rows. | Make preview optional and give the essential summary/checks explicit shot budgets. Cut navigation or waiting; retain readable evidence. |
| The CRUD confirmation instruction said only to confirm. | Name the exact **Delete definition** button, then show the unique-source search returning **No sources found** with **All statuses** selected. |
| The chosen property's zero-sale response uses the accepted seeded PSI baseline. The runbook identifies this, but the AI script's nearby background was less explicit. | Repeat that qualification beside the AI prompt/background. Do not call this proof of completed official PSI ingestion or proof the property never sold. |

An initial approximate concern about excessive opening speech speed was withdrawn
after exact word counts were supplied. The original narration totals were 123
words for the overview and 210 for Feature 1. Its opening Feature 1 windows had
28 and 27 words in 12 seconds, respectively: 140 and 135 words/minute. The concern
is screen dwell time, not an unsupported claim that the speech is too fast.

### Resolved after revision

Re-read the revised script and runbook after the preparation agent's changes.
All four findings above are resolved: the count is seven, the release shot now
allocates six seconds to its summary and five to checks with one for transition,
preview rows are optional, the confirmation names **Delete definition**, and
the seeded PSI qualification appears beside the Feature 1 AI background.
The opening narration is also shorter, and duration headings now say **target**
rather than promising an exact unmeasured performance. No remaining document
defect blocks use of this plan for rehearsal. The final evidence expectations
below still apply; document review does not certify an unrecorded demonstration.

## Independently verified

- Read the current full Release 0 assignment in the Uni folder, the 30 August
  and 3 September announcements, and relevant original specification sections.
  The newer capture requires individual frontend AI and CI/CD in the video,
  plus deployment steps; the loop belongs in report evidence. The stated
  6 September PDF deadline and Friday 4 September showcase are consistent.
- The supplied course assignment directory contains only Release 0. Future MCP,
  RAG, multi-agent, testing and cloud requirements exist in the specification,
  but no supplied future scoring rubric was found. The assessment appropriately
  avoids inventing future marks; its provisional Release 0 table sums to 14/20.
- Re-read root instructions, README, CONTRIBUTING, documentation guidance and
  Feature 1 README. Existing service ownership and approved-exception wording
  support the background explanations. Written approval attachments remain a
  submission obligation, not something proved by these documents alone.
- Read the source CRUD fragment handlers and templates. The documented field
  labels, statuses, success messages, GET/POST/PUT/DELETE flow and filter behavior
  match the implementation. The final delete button is **Delete definition**.
  This static review does not substitute for persisted integrated CRUD footage.
- Read the property panel labels and assistant context adapter. **Sources and
  identifiers**, **Socio-economic area context** and **General Property data
  question** are supported. The stored property's UUID version nibble is outside
  the browser's `[1-5]` restriction, supporting the documented context workaround.
- Compared the property reference, G-NAF PID, coordinates, release IDs, source
  counts, SEIFA year/deciles/attribution and zero-sale statement with the retained
  JSON. They agree. Browser/map rendering and actual AI submissions were verified
  by the preparation agent; this reviewer did not independently replay them.
- Queried GitHub with `gh run view`. Student 1 run **33741678659** and Integration
  run **33741678658** both succeeded at
  `f787250098abccfc279b9d814ee5f9e7a0e013dc`. Job **100604814510** is the correct
  Student 1 stack job, and all named build/start/fixture/smoke steps succeeded.
  Integration includes the canonical quality gate and Compose-model validation.
  These historical runs do not certify the presentation branch or final runtime.
- Read workflow triggers: a change under `student-1/` triggers Student 1 on a PR;
  Integration runs on PRs. A useful checklist change can produce honest CI
  evidence without a manufactured failure or altered product behavior.

## Final verification expectations

1. Record genuine uncut integrated source CRUD and successful deployment before
   editing the timed clip. Preserve visible outcomes and label removed waits.
2. Rehearse both exact AI prompts and load the chosen map/SEIFA page from the
   agreed final runtime. Keep actual badges, limits and source provenance visible.
3. Identify runtime checkout/SHA separately from spike CI and final submission
   evidence. The existing source-mounted stack can change under another agent.
4. Keep the requested branch in its separate worktree and the PR draft with
   **[NO CHECKIN]** prefix. Preserve final successful run links and reported
   quality-check results. Do not merge as part of presentation preparation.
5. Finish the group integration/report/video obligations, especially Feature 3,
   approvals, table-count evidence, development-review logs and final video URL.
   This pack is preparation and does not close those remaining evidence gaps.

This reviewer made no product changes, ran no new application test suite, and
performed no browser, live-model, data or service mutations. The preparation
agent owns the required final `uv run python scripts/check.py` gate and final
revision verification.
