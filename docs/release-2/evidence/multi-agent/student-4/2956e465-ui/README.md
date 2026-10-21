# Feature 4 evidence readiness review, decided by the student across two rounds (run `2956e465`)

Release 2 F-5: one complete Frontend -> Feature 4 backend -> Multi-Agent Server -> Planner ->
Worker -> Reviewer -> human workflow, started and decided from the Feature 4 site review page in
the live local stack on 21 October 2026. **This is the run to cite.** Both decisions were made by
Michael White in the browser. The correction went against the Reviewer, which had recommended
approve with all ten checks passing.

| | |
|---|---|
| Site review | `Due-diligence review 1` (`d4000000-...-000000000001`), 11 Example Street, Sydney NSW 2000; seeded demonstration data |
| Page | `http://localhost:5400/#site-reviews/d4000000-0000-0000-0000-000000000001`, "Evidence readiness review" card |
| Path | Browser -> `POST /api/due-diligence/v1/evidence-reviews` -> Multi-Agent Server `:5013` -> MCP -> Feature 4 tool endpoints |
| Agents | Planner `gemini-3.5-flash-lite`; Worker `gemini-3.6-flash` in both rounds; Reviewer `gemini-3.6-flash` in round 1. In round 2 the model answered `model_overloaded` and the Reviewer fell back to `deterministic-rules-v1`, which is recorded in `coordination_audit.jsonl` |
| Round 1 | Reviewer recommended **approve**: all 10 checks passed |
| Human | **`correct` by Michael White**, overriding that recommendation. The Worker had pointed at the review's saved question list instead of drafting its own questions. It did not flag two pairs of conflicting records (zoning confirmed R2 and non-intersecting; strata registered and unavailable). It also quoted the seed note without saying plainly that the data is demonstration data |
| Round 2 | The Worker stated the seeded data plainly and flagged both conflicts with record IDs. It wrote the bushfire and heritage questions in full, each naming a professional. Reviewer (deterministic fallback) recommended approve, 0 failed and 10 passed |
| Outcome | **`approve` by Michael White** in round 2, with a recorded limitation: the building height, strata and undertakings items name the professional but not the question, so those are written by hand when saving questions. Nothing was written to the site review, and only the two read-only tools ran |

## Why this run is the strongest evidence of the human gate

The ten reviewer checks are structural. They confirm that the right review was read, that
planning and building evidence exist and name a source, and that the review is not archived.
They cannot see whether the prose a professional reads actually asks the right questions. In
round 1 every check passed and the Reviewer recommended approve. The human read the draft against
the recorded evidence and found three gaps. The agents fixed them in round 2. The remaining gap was
completeness rather than accuracy, and the correction had been used, so it was approved with the
limitation recorded in the decision note rather than rejected.

Round 1 is kept beside round 2 in `run.json` and in the panel, so the before and after can be
compared directly.

Both tool calls (`duediligence.review.inspect.v1`, `duediligence.evidence.summary.v1`) succeeded in
each round and are declared `side_effect: read_only` in `student-4/config/multi-agent/workflow.yaml`.

`run.json`, `template.json`, `workflow_history.jsonl`, `coordination_audit.jsonl` and `summary.md`
come from `uv run multi-agent-server export 2956e465-a01a-4999-8aa0-cdb917c497d5 --server`.
Screenshots were captured with Playwright (1440 x 1000) against the same stack. Each one reopens
the recorded run through the page's per-review run memory. The decisions themselves were made in
the browser.

| Screenshot | Shows |
|---|---|
| `00-approved-run.png` | The approved run: replay scrubber, stage timeline and the recorded outcome |
| `01-plan.png` | The Planner's two read-only steps and their resolved arguments |
| `02-worker-evidence.png` | Round 2: the correction applied, the conflicts flagged and the drafted questions |
| `03-reviewer-recommendation.png` | Round 2 Reviewer: recommends approve, 0 failed and 10 passed |
| `04-round-1--superseded.png` | Round 1 kept for comparison: the draft that referred to the saved list |
| `05-recorded-decisions.png` | Both decisions, with actor, round and each note |
| `06-activity-log.png` | State transitions and coordination audit events from the history route |

## The other runs here

| Run | Decided by | What it adds |
|---|---|---|
| `../ec73c476-ui/` | Michael White | A single-round approval from the page; the Worker and Reviewer both fell back to deterministic rules (`model_overloaded`). Superseded by this run |
| `../f58a46f5-api/` | agent, on Michael's behalf | The proxy contract exercised over HTTP rather than the page: a correction for the missing seeded-data disclosure, then approve |
