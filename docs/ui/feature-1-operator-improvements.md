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
   In the fresh schools run, “Review candidate data” opened the optional AI review instead of the
   release detail. Separate “Open candidate” from “Ask AI to review”.

## Progress and motion

- Use determinate progress only where a trustworthy byte/row total exists. SQL sort/join/index
  work should display elapsed time and activity, not a fabricated percentage or deadline.
  The G-NAF Parquet file already knows its row count; propagate that verified total to COPY
  progress instead of leaving a 5.19-million-row phase indeterminate.
- Preserve the last meaningful phase/counters while refreshing; avoid re-rendering the entire
  timeline on every poll. Update text nodes and animate a small active-stage accent.
- Label units: source rows, unique sales revisions, positive crime observations and exported
  crime series are different counts. Explain deduplication instead of implying dropped data.
- Show phase durations and throughput at completion, and compare only runs with the same scope
  and acquisition mode. Separate downloads from parsing/import/export in comparison charts.
- Use skeletons for first load; retain data with a quiet refresh indicator for subsequent loads.
  Show a stale-data indicator and a retry action after connection loss.
- During a worker restart, the G-NAF screen continued saying “Running” and increased its ETA
  while no progress occurred. Show stale heartbeat age before lease expiry, suspend the ETA,
  and explain that recovery becomes available when the lease expires. After resume, distinguish
  attempt elapsed time from total elapsed time: old `started_at`/`finished_at` and counters
  currently make a restarted export look partially complete before it has rebuilt those rows.
- Remove internal task prefixes such as `Discover · 00/discover` from the primary timeline.
  In isolated environments, configure product-home links to the matching environment: the
  fresh port 5210 UI currently links to the existing port 5100 workspace.

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

The live bulk test exposed a lock stall that also made property pages time out. The backend lock
cycle is fixed in the performance pass, but the UI should still distinguish “worker reachable,
no recent progress” from “actively processing”. Show queue wait separately from loader duration;
the current import task timer also includes time waiting for G-NAF publication. A resumed task's
cumulative timer must not be presented as a clean performance comparison.
Explain recovery at stage granularity: an interrupted COPY transaction restarts from the verified
canonical file, and an interrupted gzip export rebuilds from its first record. “Resume” does not
mean the displayed processed-row counter is a durable row-level checkpoint. Reset the attempt
display explicitly while preserving the failed attempt's evidence in history.

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
