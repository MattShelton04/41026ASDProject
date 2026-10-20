# Feature 2 market case brief over the API (run `58936cad`)

The same workflow driven through Feature 2's proxy routes rather than the page, on 20 October 2026.
It records that the feature's own HTTP surface — not just the browser panel — carries the whole
run, and it is the single-round counterpart to the two-round UI run in `../68c410ca-ui/`.

| | |
|---|---|
| Case | `Sydney example - full history` (`60000000-...-000000000001`) |
| Path | `curl` -> `POST /api/market-intelligence/v1/market-briefs` -> Multi-Agent Server `:5013` -> MCP -> Feature 2 tool endpoints |
| Agents | Planner `gemini-3.5-flash-lite`, Worker and Reviewer `gemini-3.6-flash` |
| Round 1 | Reviewer recommended `approve`; all 11 checks passed |
| Outcome | `approved`. Nothing was written; both tools are read-only |

What the proxy was observed to do on this run:

- `GET  /market-briefs/template` returned the pinned `f2-market-case-brief` template with both
  tools reporting `available: true`.
- `POST /market-briefs` with an `actor` field was refused `422 invalid_market_brief_request`
  (`unexpected field(s): actor`); the start contract accepts `input`, `requested_by` and
  `template_id` only, and the template is pinned server-side rather than taken from the client.
- The `202` response's `Location` was rewritten to
  `/api/market-intelligence/v1/market-briefs/<run>` — the feature's own route, never the
  Multi-Agent Server's — and `X-Workflow-Run-ID` was set.
- `POST /market-briefs/<run>/decision` recorded the approval with its actor and note.

`run.json`, `template.json`, `workflow_history.jsonl`, `coordination_audit.jsonl` and `summary.md`
come from `uv run multi-agent-server export 58936cad-384f-47f5-8aa4-220f16bce1f0 --server`.
The decision was made by the agent on Burhan Naeem's behalf as a local verification run; the note
on the decision states what was checked.
