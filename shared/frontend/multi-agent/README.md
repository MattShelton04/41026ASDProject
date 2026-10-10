# Shared multi-agent workflow panel

Import from `index.js`. This package renders a feature's Planner → Worker → Reviewer → human
workflow ([ADR-047](../../../docs/architecture/decisions/ADR-047-multi-agent-server.md)) as a
**mission relay**: four live lanes on one time axis (a relay strip in narrow columns), one line
saying what is happening now, one plain-language question when it is the person's turn, and
everything else (plan, evidence, checks, the replaced round, decisions, activity log) in drawers
that start closed. It polls, validates, cancels and replays recorded runs. The feature owns the
proxy routes, the workflow template, vocabulary overrides and where the panel is mounted. Load
`styles.css` after the Shared design-system styles.

The panel only ever talks to the **feature backend's proxy** (`apiRoot`). It never calls the
Multi-Agent Server, which runs as a host process with a service token that the browser must not see.

## Public API

```js
import { createMultiAgentClient, createMultiAgentPanel } from "../multi-agent/index.js";

const client = createMultiAgentClient({ apiRoot: "/api/data-platform/v1/release-reviews" });
const panel = createMultiAgentPanel({
  root: document.querySelector("#review-panel"),
  client,
  initialInput: { release_id: releaseId },  // prefills the template's inputs
  hiddenInputs: ["release_id"],             // submitted and listed, but not editable
  actor: currentOperatorName,               // prefills the decision's actor field
  runId: null,                              // or reopen an existing run
  announce: (message) => pageAnnouncer.say(message),  // optional; default is an own polite region
  historyHref: (runId) => `#/reviews/${runId}`,        // optional "Open full history" link
  onRunChange: (run) => updateUrl(run.id),             // optional; called on each state change
  labels: { start: "Review this release" },            // optional vocabulary overrides
});
// panel.start(input?)  → validate the form (or send `input` as given) and start a run
// panel.open(runId)    → load and show a recorded run, polling it if agents are still working
// panel.refresh()      → reload the template if it failed, re-read the current run
// panel.focus()        → focus the run heading, or the panel heading before a run exists
// panel.destroy()      → stop polling and timers, abort in-flight requests (client.destroy())
// panel.run / panel.template → the latest WorkflowRun and WorkflowTemplateDescriptor
```

| Option | Default | Meaning |
|---|---|---|
| `root`, `client` | required | Mount element (its content is replaced) and one client per mounted panel |
| `initialInput` | `{}` | Values for template inputs, by input `name` |
| `hiddenInputs` | `[]` | Input names the page supplies; validated, submitted and shown read-only |
| `runId` | `null` | Open an existing run at mount instead of showing the start form |
| `actor` / `requestedBy` | `""` | Decision actor prefill; `requested_by` on start (falls back to `actor`) |
| `title` / `description` | template title / objective | Panel heading and introduction |
| `labels` | `DEFAULT_MULTI_AGENT_LABELS` | Overrides, merged one level deep (for example `states.awaiting_human.label`) |
| `historyHref(runId)` | none | Adds a link to a feature-owned history or activity page |
| `announce(message)` | own `role="status"` region | Integrates an existing page announcer |
| `pollDelay(state, failures, hidden)` | `nextWorkflowPollDelay` | Polling policy override (tests, demos) |

`createMultiAgentClient({fetcher, apiRoot})` returns a frozen object with `getTemplate`,
`listRuns({limit, state})`, `startRun(input, {requestedBy})`, `getRun(runId)`,
`decide(runId, body)`, `cancel(runId, {actor})`, `getHistory(runId, {afterHistory, afterAudit})`
and `destroy()`. Non-zero history cursors become `after_history` / `after_audit`. Each method
accepts `{signal}` and resolves to `{body, requestId}`; errors are `MultiAgentApiError`
(`HttpProblem` from `../browser/index.js`) carrying `status`, `code`, `requestId` and `problem`.
Mutations time out after 15 s and reads after 10 s. Nothing is retried automatically.

The pure projections are exported for features and tests: `stageTimeline`, `availableDecisions`,
`canCancel`, `validateDecision`, `startFields`, `validateStartInput`, `groupFindings`,
`workerStepViews`, `evidenceExcerpt`, `problemView`, `fieldProblems`, `historyView`,
`provenanceLabel`, `formatDuration` and `nextWorkflowPollDelay`. The timeline projections in
`timeline.js` are exported too: `mergeHistory`, `buildTimeline`, `snapshotAt`, `laneView`,
`relayView`, `nowView`, `advanceReplay` and `eventSentence`.

## Proxy contract

A feature backend that hosts this panel implements these routes under its `apiRoot`, forwarding
to the Multi-Agent Server with `MULTI_AGENT_BASE_URL` and `MULTI_AGENT_SERVICE_TOKEN` and its own
fixed `template_id`. Bodies are the shapes in `shared/contracts/openapi/multi-agent.v1.openapi.json`.

| Method and path | Body / query | Success |
|---|---|---|
| `GET {root}/template` | | 200 `WorkflowTemplateDescriptor` `{template, input_schema, tools[{name, available}], source}` |
| `POST {root}` | `{input: {...}, requested_by?}` | 202 `WorkflowRun` |
| `GET {root}` | `limit`, `state` | 200 `{items: [WorkflowRunSummary], count}` |
| `GET {root}/{run_id}` | | 200 `WorkflowRun` |
| `POST {root}/{run_id}/decision` | `{decision: approve\|correct\|partial\|reject, note, actor, accepted_step_ids?}` | 200 `WorkflowRun` |
| `POST {root}/{run_id}/cancel` | `{actor?}` | 200 `WorkflowRun` |
| `GET {root}/{run_id}/history` | `after_history`, `after_audit` (optional cursors) | 200 `{run_id, state, history[], audit[]}`; only entries after each cursor |

Errors are Problem Details (`application/problem+json`: `type`, `title`, `status`, `detail`,
`code`, `request_id`, optional field `errors[{field, message, code}]`). Pass the history cursors
through unchanged and relay the server's `400 invalid_request` for a bad cursor. Return
`503 multi_agent_unavailable` when the server cannot be reached and pass the server's own codes
(`invalid_workflow_input`, `invalid_state_transition`, `run_not_found`, …) through. Echo
`X-Request-ID`. The panel shows title, detail, code, HTTP status and request ID inline, and
attaches field issues (`input.release_id`, `note`, `actor`, …) to the matching control.

## Behaviour

- **Form.** Template `inputs` become controls: `string` → text (textarea above 200 characters),
  `format: uuid` → a pattern-checked text input, `date` → date, `uri` → URL, `enum` → select,
  `integer`/`number` → number with `minimum`/`maximum`, `boolean` → checkbox. Validation runs in
  the browser first with accessible messages; the server validates again.
- **Polling.** `GET {root}/{run_id}` repeats only while the state is `planning`, `working` or
  `reviewing`: about 1 s (1.5 s while working), doubling per consecutive failure up to 15 s, and at
  least 5 s while the document is hidden. Returning to the tab polls at once. A failed poll keeps
  the last recorded state with a warning. `awaiting_human` and the terminal states do not poll.
- **History.** The full history is read when a run is opened or started. Each successful poll then
  reads `GET {root}/{run_id}/history` again with `after_history` and `after_audit` set to the
  latest sequences, and merges the new entries. A state change, decision or cancellation always
  catches up at once; a routine read is skipped while one is in flight. If history cannot be read,
  the lanes fall back to the run's stages and the panel offers a retry. Deciding never depends on it.
- **Lanes and the now line.** Every mark comes from a recorded fact: stages from the run, and from
  the history the tool calls (`tool.call`, as each returns), model calls (`model.invocation`, drawn
  from start to finish when they return; retries in amber), the `model.started` audit event (so
  the now line can say "waiting on the model"), and hand-offs (`agent.handoff`, dotted; a
  correction is solid). The axis grows with the run, so nothing in the future is drawn; running
  stages and waits are striped and never show a percentage. A wait for a person is shortened on
  the axis to 3.2 s and its real length is reported in text. Below a 640 px column the lanes
  become a four-station relay strip with a baton and a "sent back once" loop.
- **Decisions.** The card puts the Reviewer's suggestion and failed checks (three at a time, with
  "Why") beside one question: "What do you want to do?". Choices appear only for actions in
  `run.available_actions`, in plain language (Approve, Send back once, Accept some steps, Reject;
  in round 2 `correct` is the Final correction, which ends the run as `corrected`). The note,
  steps and name appear only after a choice, with a label and submit button that match it.
  Approving over failed critical or high checks shows the guidance as a warning. The card always
  says that deciding records a decision and never publishes (`labels.decisionSafety`; Feature 1
  names the release). `validateDecision` still mirrors the server's rules; until a choice is made
  only the missing choice is reported, and each error clears once fixed. A `409` re-reads the run.
- **Replay.** A finished run with recorded history opens at its outcome and offers a replay:
  play/pause, previous/next recorded event, a scrubber, speed, and jumps to each decision and the
  outcome. It plays the recorded timestamps (waits for a person shortened), stops at each decision
  point and shows what the person actually decided, then continues. Nothing is sent from a replay.
  Open runs follow live polling and never replay.
- **Rounds.** The round, the replaced round (in its own drawer, with its evidence and review) and
  every recorded decision are shown. `failed` shows `error.code` and `error.message`. Cancelling
  asks for confirmation first.
- **Motion and accessibility.** New marks animate once (pins ping, model bars resolve, batons
  travel, the decision card rises); a run that is opened is drawn without animation.
  `prefers-reduced-motion` removes all animation and transitions, and a replay then steps from
  one recorded moment to the next instead of gliding. The lanes are a list whose rows read as
  "Worker, Working · 3.4 s"; the drawing itself is hidden from assistive technology. State changes
  and replay pauses are announced politely, but the per-second timer is not. Focus moves to the run
  heading after a start, decision or cancellation, to the first invalid control after a failed
  validation, and survives re-renders. The panel adds a `ps-multi-agent` CSS container to `root`,
  so a narrow feature column gets the narrow layout on a wide screen. Positions are CSS custom
  properties; nothing measures layout. All recorded values are rendered as text, never HTML.

Stable hooks for pages, browser tests and screenshots: `.ps-multi-agent__start` (start form),
`.ps-multi-agent__run[data-state][data-replay]`, `.ps-multi-agent__lanes` /
`.ps-multi-agent__stage[data-stage][data-status]` (one per lane), `.ps-multi-agent__relay`,
`.ps-multi-agent__now[data-tone]`, `.ps-multi-agent__decide` with `.ps-multi-agent__suggest[data-recommendation]`
and `.ps-multi-agent__decision` (decision form), `.ps-multi-agent__recorded` (replay),
`.ps-multi-agent__outcome`, `.ps-multi-agent__drawer[data-disclosure]`, `.ps-multi-agent__plan`,
`.ps-multi-agent__worker`, `.ps-multi-agent__review`,
`.ps-multi-agent__recommendation[data-recommendation]`, `.ps-multi-agent__superseded`,
`.ps-multi-agent__decisions`, `.ps-multi-agent__problem`, `.ps-multi-agent__history` and
`.ps-multi-agent__replay`. Buttons carry `data-action` (`start`, `decide`, `cancel`,
`confirm-cancel`, `start-again`, `history-link`, `reload-template`, `reload-run`,
`reload-history`, `keep-run`, and for replays `replay`, `replay-previous`, `replay-next`,
`replay-seek`, `replay-jump`, `replay-outcome`, `replay-continue`).

## Mounting in a feature frontend

A shared asset must work both in the built image and under the development bind mounts:

1. Add `COPY shared/frontend/multi-agent /usr/share/nginx/html/multi-agent` to the feature's
   frontend Dockerfile stage.
2. Add `./shared/frontend/multi-agent:/usr/share/nginx/html/multi-agent:ro` to the feature's
   frontend service in `docker-compose.dev.yml`.
3. Commit an empty `student-N/frontend/multi-agent/README.md` mount point (see Feature 1's).
4. Import only `../multi-agent/index.js` (`scripts/validate_architecture.py` enforces the barrel)
   and load `multi-agent/styles.css` after the design-system styles.

Feature 1 is mounted today. Node tests resolve `student-N/frontend/multi-agent/` to this package
through `scripts/frontend-test-bootstrap.mjs`.

## Testing

```text
node --import ./scripts/frontend-test-bootstrap.mjs --test shared/frontend/multi-agent/*.test.mjs
```

`multi-agent.test.mjs` covers the client and pure projections; `timeline.test.mjs` covers history
merging, snapshots, the shortened axis, lanes, the relay strip, the now line and the replay clock
on a fixture shaped like a recorded two-round run; `panel.test.mjs` drives the mounted panel
through a text-only DOM double (start, polling with history cursors, lanes, decision validation,
correction round, replay, Problem Details, history failure, cancellation and destroy).
`uv run python scripts/check.py` runs them all automatically.
