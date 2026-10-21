# Multi-agent workflow run `ec73c476-8773-4644-9669-e8c0a7ae5383`

| Field | Value |
|---|---|
| Template | `f4-evidence-readiness-review` v1 |
| Feature | `student-4-due-diligence` |
| Final state | **approved** |
| Rounds | 1 |
| Requested by | due-diligence-evidence-review |
| Request ID | `2f3e9027-f3e4-4d4b-958f-52ef20f85bb2` |
| Agents | model provider |
| Created | 2026-10-21T05:20:18.572593+00:00 |
| Completed | 2026-10-21T05:56:56.984751+00:00 |
| Input | `{"reviewer_note": "Michael White", "site_review_id": "d4000000-0000-0000-0000-000000000001"}` |

## Workflow history

| # | Time | From | To | Actor | Reason |
|---|---|---|---|---|---|
| 1 | 2026-10-21T05:20:18.573183+00:00 | - | planning | multi-agent-server (system) | Run accepted |
| 2 | 2026-10-21T05:20:23.792526+00:00 | planning | working | planner (planner) | Planner produced 2 step(s); handed to Worker |
| 3 | 2026-10-21T05:20:33.887144+00:00 | working | reviewing | worker (worker) | Worker gathered evidence for 2/2 step(s) |
| 4 | 2026-10-21T05:20:39.426283+00:00 | reviewing | awaiting_human | reviewer (reviewer) | Reviewer recommends approve; awaiting human decision |
| 5 | 2026-10-21T05:56:56.985763+00:00 | awaiting_human | approved | Michael White (human) | Human decision: approve |

## Planner

This plan inspects the saved site review to gather its address, property reference, status, disposition, checklist, and notes, and then reads the planning, environmental, strata, and building evidence summary for the property to assess readiness and identify any missing or partial items.

Produced by `gemini` / `gemini-3.5-flash-lite`, prompt `planner` v1.

| # | Step | Tool | Arguments | Required |
|---|---|---|---|---|
| 1 | Inspect the saved site review (`review`) | `duediligence.review.inspect.v1` | `{"site_review_id": "d4000000-0000-0000-0000-000000000001"}` | True |
| 2 | Read the planning and building evidence (`evidence`) | `duediligence.evidence.summary.v1` | `{"site_review_id": "d4000000-0000-0000-0000-000000000001"}` | True |

Evidence needed:

- Site review metadata, status, notes, and checklist
- Property planning, environmental, strata, and building evidence summary

## Worker (round 1)

Gathered evidence for 2 of 2 planned step(s).

| Step | Status | Findings |
|---|---|---|
| `review` | completed | duediligence.review.inspect.v1 returned evidence (86dd162bc826b18fc530d154ed1923f249d2e5c99d89cc932bec1dd97e681f53). / site_review: object with 13 field(s). |
| `evidence` | completed | duediligence.evidence.summary.v1 returned evidence (661d3ce28f8d1a3e153a246be743e9a7249534fb5090546b4929da59401af130). / buildings: 5 item(s). / constraints: 7 item(s). |

| Evidence | Tool | Outcome | Transport | Result SHA-256 |
|---|---|---|---|---|
| `ev-review-r1` | `duediligence.review.inspect.v1` v1 | succeeded | mcp | `86dd162bc826b18fc530d154ed1923f249d2e5c99d89cc932bec1dd97e681f53` |
| `ev-evidence-r1` | `duediligence.evidence.summary.v1` v1 | succeeded | mcp | `661d3ce28f8d1a3e153a246be743e9a7249534fb5090546b4929da59401af130` |

## Reviewer (round 1)

10 of 10 reviewer check(s) passed.

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
| 1 | approve | Michael White | 2026-10-21T05:56:56.984751+00:00 | - | approved |

## Coordination audit

23 event(s) in `coordination_audit.jsonl`: agent.handoff x4, decision.recorded x1, model.fallback x2, model.invocation x5, model.started x5, plan.created x1, review.completed x1, run.created x1, tool.call x2, worker.completed x1
