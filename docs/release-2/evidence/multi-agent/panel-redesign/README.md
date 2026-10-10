# Multi-agent panel redesign: "mission relay" (10 October 2026)

Evidence for the redesign of the Shared multi-agent panel (`shared/frontend/multi-agent/`) and the
two additive Multi-Agent Server changes it reads (ADR-047 decision 10): `model.started` audit
events and the `after_history` / `after_audit` history cursors.

## Live run `3ba5c95a`

One new review was started, watched and decided from the Feature 1 release review page in the
live local stack (`ps-dev`) on 10 October 2026, driven with Playwright at 1440 × 1000.

| | |
|---|---|
| Release | `abs-cpi` candidate `e9df11fb-5221-4746-ad0d-d8066405855e` (the release used in [`18740ca5-ui`](../student-1/18740ca5-ui/README.md)) |
| Agents | Model provider (`provider_mode: model`); 5 `model.started` events in the audit log |
| Round 1 | Reviewer suggested Approve with two low checks failing; the person chose "Send back once" with a note |
| Round 2 | The Worker re-ran both tools; the person chose "Accept some steps", accepting `release` only |
| Outcome | `partially_accepted`. Nothing was published; Publish stayed a separate action |
| Polling | 29 history reads; after the first, every read carried `after_history` and `after_audit` (for example `?after_history=6&after_audit=25`), so only new entries were transferred |

The decision actor is recorded as `matthew (agent live check)` because a coding agent made both
decisions on the user's behalf to exercise the live path. `run.json`, `template.json`,
`workflow_history.jsonl`, `coordination_audit.jsonl` and `summary.md` in [`3ba5c95a-live/`](3ba5c95a-live/)
come from `uv run multi-agent-server export 3ba5c95a-03e9-490a-87d3-7df079ae5bdf --server`.

The live proxy was also checked directly: `GET /api/data-platform/v1/release-reviews/{id}/history?after_audit=-1`
returned the server's `400 invalid_request` Problem Details unchanged.

## Screenshots

"Before" screenshots serve `shared/frontend/multi-agent/*` and Feature 1's
`integration/release-review.js` from `origin/main` (commit `bef57da`) through Playwright request
interception, so both versions read the same live stack and recorded runs.

| Screenshot | Shows |
|---|---|
| `00-before-1440.png` | The previous panel for run `18740ca5`: 3,491 px tall at 1440 px |
| `01-after-1440-outcome.png` | The same run: lanes, the outcome and closed drawers, 1,253 px tall |
| `02-live-round2-working.png` | Live run `3ba5c95a` in round 2: tool pins, the solid correction hand-off, "waiting on the model", and the Worker evidence drawer highlighting its new count |
| `03-live-decision-chosen.png` | The live decision card after choosing "Send back once": contextual note, name and submit label, and the "never publishes the release" line |
| `04-replay-decision-1.png` | Replay of `18740ca5` paused at decision 1: the recorded decision and real wait (2 min 2 s), with nothing sent |
| `05-before-375.png` | The previous panel at 375 px: 6,370 px tall |
| `06-after-375-replay-decision.png` | The relay strip and stacked decision card at 375 px |
| `07-reduced-motion-replay.png` | `prefers-reduced-motion: reduce`: the same view with no animation |

No capture logged a console error, and none scrolled horizontally.
