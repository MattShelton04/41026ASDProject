# Multi-agent workflow run `58936cad-384f-47f5-8aa4-220f16bce1f0`

| Field | Value |
|---|---|
| Template | `f2-market-case-brief` v1 |
| Feature | `student-2-market-intelligence` |
| Final state | **approved** |
| Rounds | 1 |
| Requested by | burhan.naeem |
| Request ID | `29d97ab0-b64d-4342-90bd-9ee0c447ca10` |
| Agents | model provider |
| Created | 2026-10-20T11:10:39.340465+00:00 |
| Completed | 2026-10-20T11:16:28.197197+00:00 |
| Input | `{"market_case_id": "60000000-0000-4000-8000-000000000001", "reviewer_note": "Release 2 demonstration run."}` |

## Workflow history

| # | Time | From | To | Actor | Reason |
|---|---|---|---|---|---|
| 1 | 2026-10-20T11:10:39.341506+00:00 | - | planning | multi-agent-server (system) | Run accepted |
| 2 | 2026-10-20T11:10:45.068165+00:00 | planning | working | planner (planner) | Planner produced 2 step(s); handed to Worker |
| 3 | 2026-10-20T11:10:49.010660+00:00 | working | reviewing | worker (worker) | Worker gathered evidence for 2/2 step(s) |
| 4 | 2026-10-20T11:10:51.306106+00:00 | reviewing | awaiting_human | reviewer (reviewer) | Reviewer recommends approve; awaiting human decision |
| 5 | 2026-10-20T11:16:28.198325+00:00 | awaiting_human | approved | claude-code (agent, on behalf of Burhan Naeem) (human) | Human decision: approve |

## Planner

This plan inspects the specified market case to retrieve its metadata, filters, and date window, and then calculates the deterministic sales summary including sale counts, median price, exclusions, sources, and limitations.

Produced by `gemini` / `gemini-3.5-flash-lite`, prompt `planner` v1.

| # | Step | Tool | Arguments | Required |
|---|---|---|---|---|
| 1 | Inspect the saved market case (`case`) | `market.cases.inspect.v1` | `{"market_case_id": "60000000-0000-4000-8000-000000000001"}` | True |
| 2 | Calculate the deterministic sales summary (`sales`) | `market.sales.summary.v1` | `{"market_case_id": "60000000-0000-4000-8000-000000000001"}` | True |

Evidence needed:

- Market case metadata, status, date window, and filters
- Deterministic sales summary including counts, median price, exclusions, sources, and limitations

## Worker (round 1)

The evidence shows details for active market case 'Sydney example – full history' at '11 Example Street, Sydney NSW 2000' covering the date range '2019-01-01' to '2026-12-31' with a minimum match tier of 'B'. The sales summary indicates 10 eligible sales, a median price of 992,500 AUD, and 2 excluded sales (1 below match threshold, 1 missing or zero price), alongside documented limitations regarding historical evidence and synthetic data.

| Step | Status | Findings |
|---|---|---|
| `case` | completed | Market case name is 'Sydney example – full history' for address '11 Example Street, Sydney NSW 2000'. / The date window spans from '2019-01-01' to '2026-12-31' with status 'active'. / The minimum match tier filter is set to 'B', and property validation state is 'fixture_verified'. |
| `sales` | completed | Eligible sale count is 10, with an excluded sale count of 2. / Exclusion reasons comprise 1 'below_match_threshold' and 1 'missing_or_zero_price'. / The median price AUD is 992,500. / Transaction volume by period shows 1 in 2019, 1 in 2020, 2 in 2021, 1 in 2022, 2 in 2023, 1 in 2024, and 2 in 2025. / Source coverage shows source_release_count of 1 ('fixture-2026-r1'). |

| Evidence | Tool | Outcome | Transport | Result SHA-256 |
|---|---|---|---|---|
| `ev-case-r1` | `market.cases.inspect.v1` v1 | succeeded | mcp | `986817ec0ea5909c73c03a4e4f990341153a10ef81e9c9185857a22662f6f0c9` |
| `ev-sales-r1` | `market.sales.summary.v1` v1 | succeeded | mcp | `a8519aa35613cc18e9b110355efc8cc7a0f33950b540842ca741ad74513318a3` |

## Reviewer (round 1)

All automated checks passed successfully. The worker output accurately reflects the evidence gathered, including the case name, address, date window, eligible sale count (10), median price (AUD 992,500), exclusions (2), limitations, and disclosure of synthetic showcase data without making any valuation or price forecasts.

Recommendation: **approve**

| Finding | Check | Severity | Outcome | Message | Recommendation |
|---|---|---|---|---|---|
| `f-case-inspected` | case-inspected | info | pass | Passed: The requested market case was inspected. (market.cases.inspect.v1 succeeded) | - |
| `f-summary-calculated` | summary-calculated | info | pass | Passed: The deterministic sales summary was calculated. (market.sales.summary.v1 succeeded) | - |
| `f-case-named` | case-named | info | pass | Passed: The brief can name the case rather than an internal identifier. (market_case.name is present) | - |
| `f-property-addressed` | property-addressed | info | pass | Passed: The case resolves to a property address the brief can refer to. (market_case.address_display is present) | - |
| `f-property-attributable` | property-attributable | info | pass | Passed: The property reference was checked against the Property data research area. (market_case.property_validation_state = 'fixture_verified'; expected in ['verified', 'fixture_verified']) | - |
| `f-has-eligible-sales` | has-eligible-sales | info | pass | Passed: At least one sale observation is eligible under the case filters. (summary.eligible_sale_count = 10; expected gt 0) | - |
| `f-limitations-stated` | limitations-stated | info | pass | Passed: The summary reports the limitations that bound its figures. (summary.limitations has 3 item(s); at least 1 required) | - |
| `f-sources-recorded` | sources-recorded | info | pass | Passed: The eligible sales are attributed to at least one source release. (summary.source_release_count = 1; expected gt 0) | - |
| `f-exclusions-reported` | exclusions-reported | info | pass | Passed: The summary reports how many observations it excluded. (summary.excluded_sale_count is present) | - |
| `f-match-threshold-recorded` | match-threshold-recorded | info | pass | Passed: The minimum match tier that filtered the evidence is recorded. (summary.minimum_match_tier is present) | - |
| `f-median-available` | median-available | info | pass | Passed: A median recorded price could be calculated from the eligible sales. (summary.median_price_aud is present) | - |

## Human decisions

| Round | Decision | Actor | Time | Note | Result |
|---|---|---|---|---|---|
| 1 | approve | claude-code (agent, on behalf of Burhan Naeem) | 2026-10-20T11:16:28.197197+00:00 | Checked on Burhan Naeem's behalf: all 11 reviewer checks passed; the brief reports 10 eligible sales, median AUD 992,500, 2 exclusions with reasons, the B match tier, source coverage and the synthetic-showcase limitation together; no valuation, forecast or buy recommendation. Approved as a local Release 2 verification run. | approved |

## Coordination audit

17 event(s) in `coordination_audit.jsonl`: agent.handoff x4, decision.recorded x1, model.invocation x3, model.started x3, plan.created x1, review.completed x1, run.created x1, tool.call x2, worker.completed x1
