# Feature 1 operator experience follow-up

Observed in the real Docker/PostgreSQL interface on 9 September 2026. This is an implementation
brief for a later UI agent; recommendations below are not claims of shipped functionality.

## First priorities

1. **Name the running job.** The detail page leads with `Update 07defa9d`, losing the school/source
   identity immediately after starting it. Use “Updating NSW government schools” as the heading;
   keep the short run ID as secondary copyable metadata.
2. **Fix misleading action language.** The mode says “Replace current data”, although the actual
   action creates a candidate and publication remains a separate decision. Use “Download fresh
   source” and “Reuse downloaded data”; show what each skips and still recomputes.
3. **Make running work the primary view.** Replace four zero counters and technical checkpoints
   with an active-stage card: source, stage, elapsed time, last successful heartbeat, processed
   rows/bytes and cancel action. Show a restrained animated pipeline and smooth progress changes;
   honour reduced motion. Completed stages collapse into a compact timeline. Keep technical
   checkpoints in a disclosure instead of prominent `{}` blocks.
4. **Explain queueing.** Distinguish waiting for the acquisition worker, waiting for the database
   loader, and actively processing. Show the preceding job when available. “Queued” alone looks
   broken when a full-history job owns the serial worker for half an hour.
5. **Completion should lead somewhere.** Turn success into a candidate summary with row count,
   quality result and a clear “Review new version” action. Keep “loaded” separate from “published”.

## Progress and motion

- Use determinate progress only where a trustworthy byte/row total exists. SQL sort/join/index
  work should display elapsed time and activity, not a fabricated percentage or deadline.
- Preserve the last meaningful phase/counters while refreshing; avoid re-rendering the entire
  timeline on every poll. Update text nodes and animate a small active-stage accent.
- Label units: source rows, unique sales revisions, positive crime observations and exported
  crime series are different counts. Explain deduplication instead of implying dropped data.
- Show phase durations and throughput at completion, and compare only runs with the same scope
  and acquisition mode. Separate downloads from parsing/import/export in comparison charts.
- Use skeletons for first load; retain data with a quiet refresh indicator for subsequent loads.
  Show a stale-data indicator and a retry action after connection loss.

## Operator observability

Start with the durable data already available: task status, counters, phases, heartbeat timestamps,
structured errors, import/activation state and consumer receipts. A run event timeline can expose
these without giving the browser database credentials or raw container access.

For real-time logs, add a bounded, structured per-run event stream at the database API, relayed by
the backend. Use monotonically increasing event IDs and cursor pagination; begin with incremental
polling. Add Server-Sent Events only if the simpler approach feels inadequate. Support reconnect
from the last event ID, a bounded browser buffer, pause/autoscroll, severity/phase filters and
downloadable sanitized logs. Do not dump environment variables, lease tokens, SQL parameters,
full property records or private AI traces into frontend logs. Retain a separate request/run ID
for cross-service investigation.

Useful event types: claimed, source download started/completed, artifact verified, COPY checkpoint,
SQL phase started/completed, export checkpoint, candidate ready, publication complete, downstream
import failed, cancellation acknowledged and worker lease expired. A heartbeat is liveness
evidence, not proof that rows advanced; show both independently.

## Notifications with limited complexity

A small in-app bell/inbox for “candidate ready”, failed/interrupted jobs, publication complete and
downstream failure is feasible. Derive notifications from durable state transitions and deduplicate
by run/operation plus terminal state; do not generate one notification per poll. Include read/unread
state and direct actions to inspect/retry. Browser desktop notifications can be opt-in while the
app is open; ask for browser permission only after the operator selects that option. Email, push
infrastructure and service workers can wait until there is an actual off-device requirement.

## Acceptance checks for the UI follow-up

- Real-origin job launch, cancellation, cached replay, completion and recoverable failure flows.
- Background-tab return, disconnected/reconnected polling and stale state handling.
- Keyboard focus preserved during refresh; live regions announce stage changes, not every row.
- Reduced motion, mobile layout and long source names.
- Notifications deduplicate on reload/reconnect and identify the correct job.
- Existing quality/form suites and a browser run against the actual stack, not only injected fixtures.
