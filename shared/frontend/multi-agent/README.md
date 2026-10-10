# Shared multi-agent workflow panel

Import from `index.js`. This package renders a feature's Planner → Worker → Reviewer → human
workflow ([ADR-047](../../../docs/architecture/decisions/ADR-047-multi-agent-server.md)): it shows
the template's input form, a live stage timeline, the plan, the Worker's evidence, the Reviewer's
findings and the human decision controls, and it polls, validates and cancels. The feature owns
the proxy routes, the workflow template, vocabulary overrides and where the panel is mounted.
Load `styles.css` after the Shared design-system styles.

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
`decide(runId, body)`, `cancel(runId, {actor})`, `getHistory(runId)` and `destroy()`. Each method
accepts `{signal}` and resolves to `{body, requestId}`; errors are `MultiAgentApiError`
(`HttpProblem` from `../browser/index.js`) carrying `status`, `code`, `requestId` and `problem`.
Mutations time out after 15 s and reads after 10 s. Nothing is retried automatically.

The pure projections are exported for features and tests: `stageTimeline`, `availableDecisions`,
`canCancel`, `validateDecision`, `startFields`, `validateStartInput`, `groupFindings`,
`workerStepViews`, `evidenceExcerpt`, `problemView`, `fieldProblems`, `historyView`,
`provenanceLabel`, `formatDuration` and `nextWorkflowPollDelay`.

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
| `GET {root}/{run_id}/history` | | 200 `{run_id, state, history[], audit[]}` |

Errors are Problem Details (`application/problem+json`: `type`, `title`, `status`, `detail`,
`code`, `request_id`, optional field `errors[{field, message, code}]`). Return
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
- **Decisions.** Controls appear only for actions in `run.available_actions`. A note is required
  unless approving; `partial` requires at least one plan step (`accepted_step_ids`); the actor is
  required. In round 2, `correct` is labelled as the final correction (it ends the run as
  `corrected`). Controls are disabled while a decision is recorded. A `409` re-reads the run.
- **Rounds.** `round`, the superseded round (collapsed, with its evidence and review) and every
  recorded decision are shown. Terminal states show a clear status; `failed` shows `error.code`
  and `error.message`. Cancelling asks for confirmation first.
- **History.** "View history" lazily loads `GET {root}/{run_id}/history` (state transitions and
  audit event counts) and reloads it after the state changes.
- **Accessibility and layout.** State changes are announced politely; focus moves to the run
  heading after a start, decision or cancellation, and to the first invalid control after a failed
  validation. The panel adds a `ps-multi-agent` CSS container to `root`, so a narrow feature column
  stays single-column on a wide screen. All recorded values are rendered as text, never HTML.

Stable hooks for pages, browser tests and screenshots: `.ps-multi-agent__start` (start form),
`.ps-multi-agent__run[data-state]`, `.ps-multi-agent__timeline` / `.ps-multi-agent__stage[data-status]`,
`.ps-multi-agent__plan`, `.ps-multi-agent__worker`, `.ps-multi-agent__review`,
`.ps-multi-agent__recommendation[data-recommendation]`, `.ps-multi-agent__superseded`,
`.ps-multi-agent__decisions`, `.ps-multi-agent__decision` (decision form), `.ps-multi-agent__problem`
and `.ps-multi-agent__history`; buttons carry `data-action` (`start`, `decide`, `cancel`,
`confirm-cancel`, `start-again`, `history-link`).

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

`multi-agent.test.mjs` covers the client and pure projections; `panel.test.mjs` drives the
mounted panel through a text-only DOM double (start, polling, decision validation, correction
round, Problem Details, history, cancellation and destroy). `uv run python scripts/check.py`
runs both automatically.
