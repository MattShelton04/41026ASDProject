# Feature 2 market case brief, decided by the student (run `f7c08ae0`)

Release 2 F-5: one complete Frontend -> Feature 2 backend -> Multi-Agent Server -> Planner ->
Worker -> Reviewer -> human workflow on the Feature 2 market cases page, 20 October 2026. This is
a run whose human decision was made by Burhan Naeem himself, in the browser. It is superseded by
`../f1c290a2-ui/`, where he decided twice across a correction he initiated; cite that one.

| | |
|---|---|
| Case | `Sydney example - full history` (`60000000-...-000000000001`), 11 Example Street, Sydney NSW 2000, window 2019-01-01 to 2026-12-31, minimum match tier B |
| Page | `http://localhost:5300/#market-cases`, "Market case brief" card, "Brief this case" |
| Path | Browser -> `POST /api/market-intelligence/v1/market-briefs` -> Multi-Agent Server `:5013` -> MCP -> Feature 2 tool endpoints |
| Agents | Planner `gemini-3.5-flash-lite`, Worker and Reviewer `gemini-3.6-flash`. No deterministic fallback |
| Reviewer | Recommended `correct` on one medium finding: the Worker's prose omitted the disclosure that the case carries deterministic synthetic showcase data. The other 11 checks passed |
| Human | **`approve` by Burhan Naeem**, 2026-10-20T12:27:10Z, overriding the recommendation |
| Outcome | `approved` in round 1. Nothing was written: the saved case, its filters and its recorded sales are unchanged, and only the two read-only tools ran |

## The override

The reviewer check that failed is `limitations-stated` reported against the Worker's summary, not
against the data. The underlying tool evidence for this run does carry the limitation verbatim -
"This case currently includes deterministic synthetic showcase data." - so the fact was present in
the brief's evidence and absent only from its prose summary.

Overriding a medium finding is what the human gate is for, and the decision is recorded with its
actor and timestamp. The decision was submitted without a note, so the audit trail does not carry
the reasoning; it is recorded here instead.

For the correction loop itself - a human sending a brief back and the agents fixing it - see
`../68c410ca-ui/`, where round 2 leads with the synthetic-data disclosure and the Reviewer then
recommends approve with 0 failed checks. That run's decisions were made by the agent on Burhan's
behalf and are labelled as such.

`run.json`, `template.json`, `workflow_history.jsonl`, `coordination_audit.jsonl` and `summary.md`
come from `uv run multi-agent-server export f7c08ae0-e134-4747-a1ef-fd88056aa897 --server`.
