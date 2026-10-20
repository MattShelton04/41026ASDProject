# Feature 2 market case brief, decided by the student across two rounds (run `f1c290a2`)

Release 2 F-5: one complete Frontend -> Feature 2 backend -> Multi-Agent Server -> Planner ->
Worker -> Reviewer -> human workflow, started and decided from the Feature 2 market cases page in
the live local stack on 20 October 2026. **This is the run to cite.** Both decisions were made by
Burhan Naeem in the browser, and the correction was his own judgement rather than the Reviewer's.

| | |
|---|---|
| Case | `Sydney example - full history` (`60000000-...-000000000001`), 11 Example Street, Sydney NSW 2000, window 2019-01-01 to 2026-12-31, minimum match tier B |
| Page | `http://localhost:5300/#market-cases`, "Market case brief" card, "Brief this case" |
| Path | Browser -> `POST /api/market-intelligence/v1/market-briefs` -> Multi-Agent Server `:5013` -> MCP -> Feature 2 tool endpoints |
| Agents | Planner `gemini-3.5-flash-lite`, Worker and Reviewer `gemini-3.6-flash`. No deterministic fallback |
| Round 1 | Reviewer recommended **approve**: all 11 automated checks passed |
| Human | **`correct` by Burhan Naeem**, overriding that recommendation: the summary reported the figures without the limitations, which the feature's own review guidance requires to be reported together |
| Round 2 | Worker restated the brief with the exclusions and the deterministic synthetic showcase data beside the eligible count and median. Reviewer recommended approve, 0 failed and 11 passed |
| Outcome | **`approve` by Burhan Naeem** in round 2. Nothing was written: the saved case, its filters and its recorded sales are unchanged, and only the two read-only tools ran |

## Why this run is the strongest evidence of the human gate

The automated checks read the tool results, not the Worker's prose. In round 1 every check passed
and the Reviewer recommended approve, because the limitation was present in the step findings. The
prose summary, which is what a reader actually reads, omitted it. The human caught what the
automation could not see, sent the brief back with a specific instruction, and the agents fixed it.

Round 1 is kept beside round 2 in `run.json` and in the panel, so the before and after can be
compared directly.

Both tool calls (`market.cases.inspect.v1`, `market.sales.summary.v1`) succeeded in each round and
are declared `side_effect: read_only` in `student-2/config/multi-agent/workflow.yaml`.

`run.json`, `template.json`, `workflow_history.jsonl`, `coordination_audit.jsonl` and `summary.md`
come from `uv run multi-agent-server export f1c290a2-5b15-4ca8-8d58-8743a4a86b42 --server`.
Screenshots were captured with Playwright (1440 x 1000) against the same stack, reopening the
recorded run through the page's own deep link (`#market-cases?brief=<run>`); the decisions
themselves were made in the browser.

| Screenshot | Shows |
|---|---|
| `00-approved-run.png` | The approved run: replay scrubber, stage timeline with the `sent back once` hand-off, and the recorded outcome |
| `01-plan.png` | The Planner's two read-only steps and their resolved arguments |
| `02-worker-evidence.png` | Round 2 Worker findings per step and the MCP tool evidence |
| `03-reviewer-recommendation.png` | Round 2 Reviewer: recommends approve, 0 failed and 11 passed |
| `04-round-1--superseded.png` | Round 1 kept for comparison: the summary that omitted the limitations |
| `05-recorded-decisions.png` | Both decisions, with actor, round and the correction note |
| `06-activity-log.png` | State transitions and coordination audit events from the history route |

## The other runs here

| Run | Decided by | What it adds |
|---|---|---|
| `../f7c08ae0-ui/` | Burhan Naeem | A single-round approval that overrode a medium finding; superseded by this run |
| `../68c410ca-ui/` | agent, on Burhan's behalf | The same correction loop, run as a local verification before the student's own |
| `../58936cad-api/` | agent, on Burhan's behalf | The proxy contract exercised over HTTP rather than the page |
