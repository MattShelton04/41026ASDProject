# Multi-agent workflow run `f58a46f5-1af0-4be7-a8bb-91b6e1518dca`

| Field | Value |
|---|---|
| Template | `f4-evidence-readiness-review` v1 |
| Feature | `student-4-due-diligence` |
| Final state | **approved** |
| Rounds | 2 |
| Requested by | Michael White |
| Request ID | `e60fee0f-6c22-4dcd-b9fd-59375bd289d3` |
| Agents | model provider |
| Created | 2026-10-21T04:39:55.294548+00:00 |
| Completed | 2026-10-21T04:42:02.705393+00:00 |
| Input | `{"site_review_id": "d4000000-0000-0000-0000-000000000001"}` |

## Workflow history

| # | Time | From | To | Actor | Reason |
|---|---|---|---|---|---|
| 1 | 2026-10-21T04:39:55.295191+00:00 | - | planning | multi-agent-server (system) | Run accepted |
| 2 | 2026-10-21T04:39:59.514452+00:00 | planning | working | planner (planner) | Planner produced 2 step(s); handed to Worker |
| 3 | 2026-10-21T04:40:08.862040+00:00 | working | reviewing | worker (worker) | Worker gathered evidence for 2/2 step(s) |
| 4 | 2026-10-21T04:40:17.850827+00:00 | reviewing | awaiting_human | reviewer (reviewer) | Reviewer recommends correct; awaiting human decision |
| 5 | 2026-10-21T04:41:11.924657+00:00 | awaiting_human | working | Michael White (human) | Human decision: correct (Worker and Reviewer re-run with the correction) |
| 6 | 2026-10-21T04:41:37.497170+00:00 | working | reviewing | worker (worker) | Worker gathered evidence for 2/2 step(s) |
| 7 | 2026-10-21T04:41:47.750739+00:00 | reviewing | awaiting_human | reviewer (reviewer) | Reviewer recommends approve; awaiting human decision |
| 8 | 2026-10-21T04:42:02.707200+00:00 | awaiting_human | approved | Michael White (human) | Human decision: approve |

## Planner

This plan inspects the saved site review to retrieve its address, property reference, status, and checklist, then retrieves the planning, environmental, strata, and building evidence summary for the property to evaluate evidence readiness.

Produced by `gemini` / `gemini-3.5-flash-lite`, prompt `planner` v1.

| # | Step | Tool | Arguments | Required |
|---|---|---|---|---|
| 1 | Inspect the saved site review (`review`) | `duediligence.review.inspect.v1` | `{"site_review_id": "d4000000-0000-0000-0000-000000000001"}` | True |
| 2 | Read the planning and building evidence (`evidence`) | `duediligence.evidence.summary.v1` | `{"site_review_id": "d4000000-0000-0000-0000-000000000001"}` | True |

Evidence needed:

- Site review metadata, status, and checklist
- Planning, environmental, strata, and building evidence summary records

## Worker (round 1)

The site review for '11 Example Street, Sydney NSW 2000' (ID: d4000000-0000-0000-0000-000000000001) is currently in 'draft' status with an 'undecided' disposition. Evidence gathered shows confirmed R2 Low Density Residential zoning, FSR 0.5:1, and an active strata managing agent, but also highlights unavailable items (NSW Strata Hub status, bushfire category, heritage listing) and partial coverage items (written undertakings, 9.5m building height limit).

| Step | Status | Findings |
|---|---|---|
| `review` | completed | Site review 'd4000000-0000-0000-0000-000000000001' has address '11 Example Street, Sydney NSW 2000' and status 'draft' with disposition 'undecided'. / The checklist contains 3 items, all marked as 'done: false'. / 10 verification questions are generated prioritizing unavailable, partial coverage, non-intersection, and confirmed evidence items. |
| `evidence` | completed | Zoning 'R2 Low Density Residential' (c4000000-0000-0000-0000-000000000001) and FSR 'FSR 0.5:1' (c4000002-0000-0000-0000-000000000013) are 'confirmed' with confidence 0.98 and 0.96. / Building orders (REF-00012) and active managing agent status (REF-00001) are 'confirmed' with confidence 0.94 and 0.96. / Bushfire mapping (c4000002-0000-0000-0000-000000000016), heritage status (c4000002-0000-0000-0000-000000000012), and strata status (b4000002-0000-0000-0000-000000000011) are marked 'unavailable'. / Maximum building height 9.5m (c4000002-0000-0000-0000-000000000014) and written undertakings (b4000002-0000-0000-0000-000000000013) are marked 'partial_coverage'. |

| Evidence | Tool | Outcome | Transport | Result SHA-256 |
|---|---|---|---|---|
| `ev-review-r1` | `duediligence.review.inspect.v1` v1 | succeeded | mcp | `86dd162bc826b18fc530d154ed1923f249d2e5c99d89cc932bec1dd97e681f53` |
| `ev-evidence-r1` | `duediligence.evidence.summary.v1` v1 | succeeded | mcp | `661d3ce28f8d1a3e153a246be743e9a7249534fb5090546b4929da59401af130` |

## Reviewer (round 1)

The site review inspection and evidence summary completed successfully with all automated checks passing. However, the human review guidance explicitly requires the output to state when a review carries seeded demonstration data (as noted in the site review notes: 'Seed record 1 - replace with real due-diligence content.'), which was omitted from the worker summary.

Recommendation: **correct**

| Finding | Check | Severity | Outcome | Message | Recommendation |
|---|---|---|---|---|---|
| `f-review-inspected` | review-inspected | info | pass | Passed: The requested site review was inspected. (duediligence.review.inspect.v1 succeeded) | - |
| `f-evidence-read` | evidence-read | info | pass | Passed: The evidence summary for the review's property was read. (duediligence.evidence.summary.v1 succeeded) | - |
| `f-review-matches` | review-matches | info | pass | Passed: The inspected site review is the one the run was started for. (site_review.id = 'd4000000-0000-0000-0000-000000000001'; expected eq 'd4000000-0000-0000-0000-000000000001') | - |
| `f-property-addressed` | property-addressed | info | pass | Passed: The review resolves to a property address the questions can refer to. (site_review.address_display is present) | - |
| `f-planning-evidence-recorded` | planning-evidence-recorded | info | pass | Passed: At least one planning or environmental constraint record exists. (constraints has 7 item(s); at least 1 required) | - |
| `f-building-evidence-recorded` | building-evidence-recorded | info | pass | Passed: At least one strata or building record exists. (buildings has 5 item(s); at least 1 required) | - |
| `f-planning-evidence-attributed` | planning-evidence-attributed | info | pass | Passed: The planning evidence names the source that recorded it. (constraints.0.source_name is present) | - |
| `f-building-evidence-attributed` | building-evidence-attributed | info | pass | Passed: The building evidence names the source that recorded it. (buildings.0.source_name is present) | - |
| `f-review-active` | review-active | info | pass | Passed: The site review has not been archived. (site_review.status = 'draft'; expected not_in ['archived']) | - |
| `f-checklist-recorded` | checklist-recorded | info | pass | Passed: The review records at least one checklist item to verify. (site_review.checklist has 3 item(s); at least 1 required) | - |
| `f-model-1` | model | medium | **fail** | The worker summary fails to mention that the site review carries seeded demonstration data, as explicitly required by the human review guidance when notes indicate seed records. | Update the summary to explicitly disclose that the review contains seeded demonstration data ('Seed record 1 - replace with real due-diligence content'). |

## Worker (round 2)

The site review for 11 Example Street, Sydney NSW 2000 (ID d4000000-0000-0000-0000-000000000001) is currently in status "draft" with disposition "undecided". This review carries seeded demonstration data, as noted in the record's notes ("Seed record 1 - replace with real due-diligence content."). The associated planning and building evidence includes 5 building records and 7 constraint records across various evidence states including confirmed, partial_coverage, unavailable, and non_intersection.

Correction note: State in the summary that this review carries seeded demonstration data.

| Step | Status | Findings |
|---|---|---|
| `review` | completed | Site review d4000000-0000-0000-0000-000000000001 is titled "Due-diligence review 1" for address "11 Example Street, Sydney NSW 2000". / The review status is "draft", disposition is "undecided", and version is 10. / Review notes state: "Seed record 1 - replace with real due-diligence content." / The checklist contains 3 items, all marked with done: false. |
| `evidence` | completed | Collected 5 building records, including confirmed records REF-00012 (building_order) and REF-00001 (strata), unavailable record REF-00011, partial_coverage record REF-00013, and non_intersection record REF-00014. / Collected 7 planning constraint records, including confirmed zoning R2 Low Density Residential (c4000000-0000-0000-0000-000000000001) and FSR 0.5:1 (c4000002-0000-0000-0000-000000000013). / Constraint records identified unavailable states for heritage listing status (c4000002-0000-0000-0000-000000000012) and bushfire prone land mapping Category 1 (c4000002-0000-0000-0000-000000000016). / Constraint record c4000002-0000-0000-0000-000000000014 for maximum building height (Maximum 9.5 m) has an evidence state of partial_coverage. |

| Evidence | Tool | Outcome | Transport | Result SHA-256 |
|---|---|---|---|---|
| `ev-review-r2` | `duediligence.review.inspect.v1` v1 | succeeded | mcp | `86dd162bc826b18fc530d154ed1923f249d2e5c99d89cc932bec1dd97e681f53` |
| `ev-evidence-r2` | `duediligence.evidence.summary.v1` v1 | succeeded | mcp | `661d3ce28f8d1a3e153a246be743e9a7249534fb5090546b4929da59401af130` |

## Reviewer (round 2)

10 of 10 reviewer check(s) passed. Reviewed after the human correction: State in the summary that this review carries seeded demonstration data.

Recommendation: **approve**

| Finding | Check | Severity | Outcome | Message | Recommendation |
|---|---|---|---|---|---|
| `f-review-inspected` | review-inspected | info | pass | Passed: The requested site review was inspected. (duediligence.review.inspect.v1 succeeded) | - |
| `f-evidence-read` | evidence-read | info | pass | Passed: The evidence summary for the review's property was read. (duediligence.evidence.summary.v1 succeeded) | - |
| `f-review-matches` | review-matches | info | pass | Passed: The inspected site review is the one the run was started for. (site_review.id = 'd4000000-0000-0000-0000-000000000001'; expected eq 'd4000000-0000-0000-0000-000000000001') | - |
| `f-property-addressed` | property-addressed | info | pass | Passed: The review resolves to a property address the questions can refer to. (site_review.address_display is present) | - |
| `f-planning-evidence-recorded` | planning-evidence-recorded | info | pass | Passed: At least one planning or environmental constraint record exists. (constraints has 7 item(s); at least 1 required) | - |
| `f-building-evidence-recorded` | building-evidence-recorded | info | pass | Passed: At least one strata or building record exists. (buildings has 5 item(s); at least 1 required) | - |
| `f-planning-evidence-attributed` | planning-evidence-attributed | info | pass | Passed: The planning evidence names the source that recorded it. (constraints.0.source_name is present) | - |
| `f-building-evidence-attributed` | building-evidence-attributed | info | pass | Passed: The building evidence names the source that recorded it. (buildings.0.source_name is present) | - |
| `f-review-active` | review-active | info | pass | Passed: The site review has not been archived. (site_review.status = 'draft'; expected not_in ['archived']) | - |
| `f-checklist-recorded` | checklist-recorded | info | pass | Passed: The review records at least one checklist item to verify. (site_review.checklist has 3 item(s); at least 1 required) | - |

## Human decisions

| Round | Decision | Actor | Time | Note | Result |
|---|---|---|---|---|---|
| 1 | correct | Michael White | 2026-10-21T04:41:11.923354+00:00 | State in the summary that this review carries seeded demonstration data. | working |
| 2 | approve | Michael White | 2026-10-21T04:42:02.705393+00:00 | Round 2 states the seeded data; questions are ready for a professional. | approved |

## Coordination audit

34 event(s) in `coordination_audit.jsonl`: agent.handoff x7, decision.recorded x2, model.fallback x1, model.invocation x7, model.started x7, plan.created x1, review.completed x2, run.created x1, tool.call x4, worker.completed x2
