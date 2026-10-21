# Feature 4 evidence readiness review over HTTP (run `f58a46f5`)

The proxy contract exercised over HTTP rather than the page, on 21 October 2026, as a local
verification before the student's own run. **The decisions were recorded by the coding agent on
Michael White's behalf**, so this run shows the routes working end to end. It is not evidence of
the student's judgement; `../2956e465-ui/` is the run to cite.

| Request | Result |
|---|---|
| `GET /api/due-diligence/v1/evidence-reviews/capabilities` | `200`, `{"evidence_review": {"enabled": true}}` |
| `POST /api/due-diligence/v1/evidence-reviews` with an unexpected `actor` field | `422 invalid_evidence_review_request` |
| `POST /api/due-diligence/v1/evidence-reviews` with `input.site_review_id` and `requested_by` | `202`, `Location` under Feature 4's own route |
| Round 1 | Reviewer (`gemini-3.6-flash`) recommended **correct**: the summary did not state that the review carries seeded demonstration data |
| `POST .../{run}/decision` `correct` | `200`; Worker and Reviewer re-ran with the note |
| Round 2 | Reviewer fell back to `deterministic-rules-v1` (`model_overloaded`) and recommended approve, 10 of 10 checks passed |
| `POST .../{run}/decision` `approve` | `200`; run `approved` with 2 recorded decisions |
| `GET .../00000000-0000-4000-8000-000000000000` | `404` |

After this run, the workflow objective gained the instruction to state seeded demonstration data in
the summary.

Exported with `uv run multi-agent-server export f58a46f5-1af0-4be7-a8bb-91b6e1518dca --server`.
