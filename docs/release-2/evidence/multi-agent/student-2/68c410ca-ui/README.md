# Feature 2 market case brief from the UI (run `68c410ca`)

Release 2 F-5: one complete Frontend -> Feature 2 backend -> Multi-Agent Server -> Planner ->
Worker -> Reviewer -> human workflow, started and decided from the Feature 2 market cases page in
the live local stack on 20 October 2026. It ran two rounds because the first brief was sent back.

| | |
|---|---|
| Case | `Sydney example - full history` (`60000000-...-000000000001`), 11 Example Street, Sydney NSW 2000, window 2019-01-01 to 2026-12-31, minimum match tier B |
| Page | `http://localhost:5300/#market-cases`, "Market case brief" card, "Brief this case" |
| Path | Browser -> `POST /api/market-intelligence/v1/market-briefs` -> Multi-Agent Server `:5013` -> MCP -> Feature 2 tool endpoints |
| Agents | Model provider: Planner `gemini-3.5-flash-lite`, Worker and Reviewer `gemini-3.6-flash`. No deterministic fallback (`fallback: false` on all three) |
| Round 1 | Reviewer recommended `correct` on one medium finding: the brief omitted the limitation that the case carries synthetic showcase data. 11 other checks passed |
| Human | `correct`, asking for the synthetic-data disclosure to be reported together with the count, median and exclusions |
| Round 2 | Worker led with the synthetic-data disclosure; Reviewer recommended `approve` with 0 failed and 11 passed |
| Outcome | `approved` in round 2. Nothing was written: the saved case, its filters and its recorded sales are unchanged, and the run only called the two read-only tools |

Both tool calls (`market.cases.inspect.v1`, `market.sales.summary.v1`) succeeded in each round and
are declared `side_effect: read_only` in `student-2/config/multi-agent/workflow.yaml`.

`run.json`, `template.json`, `workflow_history.jsonl`, `coordination_audit.jsonl` and `summary.md`
come from `uv run multi-agent-server export 68c410ca-cdd9-4268-bbaa-30de64d0b50c --server`.
Screenshots were captured with Playwright (1440 x 1000) against the same stack, reopening the
recorded run in the page's own brief panel; the two decisions themselves were made in the Claude
desktop browser pane.

| Screenshot | Shows |
|---|---|
| `00-approved-run.png` | The approved run: replay scrubber, stage timeline with the `sent back once` hand-off, and the recorded outcome |
| `01-plan.png` | The Planner's two read-only steps and their resolved arguments |
| `02-worker-evidence.png` | Round 2 Worker findings per step and the MCP tool evidence |
| `03-reviewer-recommendation.png` | Round 2 Reviewer: recommends approve, 0 failed and 11 passed |
| `04-round-1--superseded.png` | Round 1 kept for comparison, including the brief that omitted the synthetic-data limitation |
| `05-recorded-decisions.png` | Both decisions with actor, round and note |
| `06-activity-log.png` | State transitions and coordination audit events from the history route |

The decisions here are recorded against `claude-code (for Burhan Naeem)`: they were made by the
agent on Burhan's behalf as a local verification run, and each note states what was checked. Cite
this run for the **two-round correction loop** - a human sending a brief back and the agents
fixing it.

For the human-in-the-loop requirement itself, cite `../f1c290a2-ui/`, whose two decisions were both
made by Burhan Naeem in the browser and are recorded under his own name.
