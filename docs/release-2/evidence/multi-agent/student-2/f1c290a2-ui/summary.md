# Multi-agent workflow run `f1c290a2-5b15-4ca8-8d58-8743a4a86b42`

| Field | Value |
|---|---|
| Template | `f2-market-case-brief` v1 |
| Feature | `student-2-market-intelligence` |
| Final state | **approved** |
| Rounds | 2 |
| Requested by | market-intelligence-case-brief |
| Request ID | `72fe4afe-eafa-4ddf-814e-c46c08fae104` |
| Agents | model provider |
| Created | 2026-10-20T12:34:42.365997+00:00 |
| Completed | 2026-10-20T12:39:08.853215+00:00 |
| Input | `{"market_case_id": "60000000-0000-4000-8000-000000000001", "reviewer_note": "Release 2 showcase run for the submitted evidence."}` |

## Workflow history

| # | Time | From | To | Actor | Reason |
|---|---|---|---|---|---|
| 1 | 2026-10-20T12:34:42.366512+00:00 | - | planning | multi-agent-server (system) | Run accepted |
| 2 | 2026-10-20T12:34:44.366116+00:00 | planning | working | planner (planner) | Planner produced 2 step(s); handed to Worker |
| 3 | 2026-10-20T12:34:48.512053+00:00 | working | reviewing | worker (worker) | Worker gathered evidence for 2/2 step(s) |
| 4 | 2026-10-20T12:34:54.902079+00:00 | reviewing | awaiting_human | reviewer (reviewer) | Reviewer recommends approve; awaiting human decision |
| 5 | 2026-10-20T12:37:09.670722+00:00 | awaiting_human | working | Burhan Naeem (human) | Human decision: correct (Worker and Reviewer re-run with the correction) |
| 6 | 2026-10-20T12:37:13.955025+00:00 | working | reviewing | worker (worker) | Worker gathered evidence for 2/2 step(s) |
| 7 | 2026-10-20T12:37:22.487896+00:00 | reviewing | awaiting_human | reviewer (reviewer) | Reviewer recommends approve; awaiting human decision |
| 8 | 2026-10-20T12:39:08.854806+00:00 | awaiting_human | approved | Burhan Naeem (human) | Human decision: approve |

## Planner

Plan to inspect the saved market research case and calculate its deterministic sales summary using the provided market case ID.

Produced by `gemini` / `gemini-3.5-flash-lite`, prompt `planner` v1.

| # | Step | Tool | Arguments | Required |
|---|---|---|---|---|
| 1 | Inspect the saved market case (`case`) | `market.cases.inspect.v1` | `{"market_case_id": "60000000-0000-4000-8000-000000000001"}` | True |
| 2 | Calculate the deterministic sales summary (`sales`) | `market.sales.summary.v1` | `{"market_case_id": "60000000-0000-4000-8000-000000000001"}` | True |

Evidence needed:

- Case details including name, address, date window, status, and filters
- Deterministic sales summary including sale count, median price, exclusions, and data limitations

## Worker (round 1)

The evidence shows details for the market case 'Sydney example – full history' and its corresponding deterministic sales summary. The case covers the address '11 Example Street, Sydney NSW 2000' from '2019-01-01' to '2026-12-31' with a status of 'active'. The sales summary reports 10 eligible sales, 2 excluded sales (1 due to 'below_match_threshold' and 1 due to 'missing_or_zero_price'), a median price of $992,500 AUD, and coverage across 1 source release ('fixture-2026-r1').

| Step | Status | Findings |
|---|---|---|
| `case` | completed | The market case name is 'Sydney example – full history' with status 'active' and property validation state 'fixture_verified'. / The case covers address '11 Example Street, Sydney NSW 2000' for the date range '2019-01-01' to '2026-12-31'. / The minimum match tier filter is configured to 'B'. |
| `sales` | completed | There are 10 eligible sales and 2 excluded sales recorded. / The exclusion reasons are 'below_match_threshold': 1 and 'missing_or_zero_price': 1. / The calculated median price is 992500 AUD across 1 source release ('fixture-2026-r1'). / Transaction volumes per year are 1 in 2019, 1 in 2020, 2 in 2021, 1 in 2022, 2 in 2023, 1 in 2024, and 2 in 2025. / Reported limitations specify that some source records were excluded by window/quality rules, deterministic synthetic showcase data is included, and sales are historical evidence rather than a valuation. |

| Evidence | Tool | Outcome | Transport | Result SHA-256 |
|---|---|---|---|---|
| `ev-case-r1` | `market.cases.inspect.v1` v1 | succeeded | mcp | `986817ec0ea5909c73c03a4e4f990341153a10ef81e9c9185857a22662f6f0c9` |
| `ev-sales-r1` | `market.sales.summary.v1` v1 | succeeded | mcp | `a8519aa35613cc18e9b110355efc8cc7a0f33950b540842ca741ad74513318a3` |

## Reviewer (round 1)

All checks passed successfully. The worker output accurately reflects the evidence from inspecting the market case and computing the sales summary, including eligible sale counts, median price, exclusions, and limitations without making any property valuations or forecasts.

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

## Worker (round 2)

The market case 'Sydney example – full history' for 11 Example Street, Sydney NSW 2000 covers the date window from 2019-01-01 to 2026-12-31 with a minimum match tier filter of B. Out of 12 total sales records, 10 are eligible and 2 are excluded (1 due to 'below_match_threshold' and 1 due to 'missing_or_zero_price'). The median recorded price for eligible sales is 992,500 AUD. Crucially, as noted in the data limitations and case notes, this dataset contains deterministic synthetic showcase data, and recorded sales are historical evidence rather than real market evidence, a valuation, or a buying recommendation.

Correction note: The summary reports the figures without the limitations. State the exclusions and the deterministic synthetic showcase data alongside the eligible count and median, so the median is not read as real market evidence.

| Step | Status | Findings |
|---|---|---|
| `case` | completed | The market case is named 'Sydney example – full history' with ID '60000000-0000-4000-8000-000000000001'. / The property address is '11 Example Street, Sydney NSW 2000' and status is 'active'. / The case covers the date window '2019-01-01' to '2026-12-31' with a minimum match tier filter of 'B'. / Notes specify this is a 'Showcase case with two deliberately excluded records.' |
| `sales` | completed | There are 10 eligible sales and 2 excluded sales. / Exclusion reasons comprise 1 'below_match_threshold' and 1 'missing_or_zero_price'. / The calculated median price is 992,500 AUD across 1 source release ('fixture-2026-r1'). / Limitations explicitly state: 'This case currently includes deterministic synthetic showcase data.' / Limitations also note that records are historical evidence, not a valuation or buying recommendation, and some records were excluded by window or quality rules. |

| Evidence | Tool | Outcome | Transport | Result SHA-256 |
|---|---|---|---|---|
| `ev-case-r2` | `market.cases.inspect.v1` v1 | succeeded | mcp | `986817ec0ea5909c73c03a4e4f990341153a10ef81e9c9185857a22662f6f0c9` |
| `ev-sales-r2` | `market.sales.summary.v1` v1 | succeeded | mcp | `a8519aa35613cc18e9b110355efc8cc7a0f33950b540842ca741ad74513318a3` |

## Reviewer (round 2)

All checks passed successfully. The worker summary correctly presents the eligible sale count (10), exclusions (2), median recorded price ($992,500 AUD), source coverage, and explicitly highlights the limitations, including that the case contains deterministic synthetic showcase data rather than real market evidence.

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
| 1 | correct | Burhan Naeem | 2026-10-20T12:37:09.669672+00:00 | The summary reports the figures without the limitations. State the exclusions and the deterministic synthetic showcase data alongside the eligible count and median, so the median is not read as real market evidence. | working |
| 2 | approve | Burhan Naeem | 2026-10-20T12:39:08.853215+00:00 | - | approved |

## Coordination audit

29 event(s) in `coordination_audit.jsonl`: agent.handoff x7, decision.recorded x2, model.invocation x5, model.started x5, plan.created x1, review.completed x2, run.created x1, tool.call x4, worker.completed x2
