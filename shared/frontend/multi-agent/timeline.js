/**
 * Pure projections from one run and its recorded history to the Mission relay view. No DOM, no I/O.
 *
 * `buildTimeline` puts every recorded fact on one clock relative to the run's creation:
 * stages from `GET {root}/{id}`, transitions and audit events from `GET {root}/{id}/history`.
 * `snapshotAt(model, t)` is what was recorded by time t; at or after the model's end it is the
 * run document itself, so a live view shows exactly what the server returned and nothing more.
 * Waits for a person are shortened on the drawing and replay axis, never in the reported times.
 */
import {
  ACTIVE_WORKFLOW_STATES, DEFAULT_MULTI_AGENT_LABELS, MAX_WORKFLOW_ROUNDS, STAGE_ORDER, humaniseValue,
  isTerminalWorkflow, workflowStatus,
} from "./definitions.js";
import { formatDuration, groupFindings } from "./projections.js";

/** Longest stretch a wait for a person takes on the axis and in a replay. */
export const HUMAN_WAIT_AXIS_MS = 3200;
/** The live axis never shows less than this, so the first seconds do not fill the width. */
export const MIN_AXIS_MS = 6000;
const AXIS_HEADROOM = 1.06;
const AWAITING_ACTIONS = Object.freeze(["approve", "correct", "partial", "reject", "cancel"]);
const STAGE_STATES = Object.freeze({ planner: "planning", worker: "working", reviewer: "reviewing", human: "awaiting_human" });
const ROLE_NAMES = Object.freeze({ planner: "Planner", worker: "Worker", reviewer: "Reviewer", human: "Person", system: "Server" });
const EVENT_ORDER = Object.freeze({ "agent.handoff": 3, transition: 2 });

function parse(value) {
  const parsed = Date.parse(value || "");
  return Number.isFinite(parsed) ? parsed : null;
}

function round(value) { return Math.round(value * 100) / 100; }

// ---- incremental history -------------------------------------------------------------------

export function emptyHistory(runId = null) {
  return { runId, history: [], audit: [], afterHistory: 0, afterAudit: 0 };
}

function mergeEntries(existing, incoming) {
  const bySequence = new Map(existing.map((entry) => [entry.sequence, entry]));
  for (const entry of Array.isArray(incoming) ? incoming : []) {
    if (Number.isInteger(entry?.sequence) && entry.sequence > 0) bySequence.set(entry.sequence, entry);
  }
  return [...bySequence.values()].sort((left, right) => left.sequence - right.sequence);
}

/**
 * Merge one `WorkflowRunHistory` page into what is already known. The two sequences are numbered
 * separately, so each keeps its own cursor (`after_history`, `after_audit`) for the next poll.
 */
export function mergeHistory(current, body) {
  const runId = body?.run_id ?? current?.runId ?? null;
  const base = current && current.runId === runId ? current : emptyHistory(runId);
  const history = mergeEntries(base.history, body?.history);
  const audit = mergeEntries(base.audit, body?.audit);
  return { runId, history, audit, afterHistory: history.at(-1)?.sequence ?? 0, afterAudit: audit.at(-1)?.sequence ?? 0 };
}

// ---- timeline model ------------------------------------------------------------------------

function eventsFrom(history, relative) {
  const events = [];
  for (const entry of history?.history || []) {
    const at = relative(entry.at);
    if (at === null) continue;
    events.push({
      id: `h${entry.sequence}`, kind: "transition", at, round: Number(entry.round) || 1, role: entry.role || "",
      actor: entry.actor || "", from: entry.from_state || null, to: entry.to_state || "", reason: entry.reason || "", detail: {},
    });
  }
  for (const entry of history?.audit || []) {
    const at = relative(entry.at);
    if (at === null) continue;
    const detail = entry.detail && typeof entry.detail === "object" ? entry.detail : {};
    const event = { id: `a${entry.sequence}`, kind: entry.event || "", at, round: Number(entry.round) || 1, role: entry.role || "", actor: entry.actor || "", detail };
    // A model or tool call is recorded when it returns; its duration says when it began.
    if (Number.isFinite(detail.duration_ms) && detail.duration_ms >= 0) event.startedAt = Math.max(0, at - detail.duration_ms);
    events.push(event);
  }
  return events.sort((left, right) => left.at - right.at
    || (EVENT_ORDER[left.kind] || 1) - (EVENT_ORDER[right.kind] || 1)
    || left.id.localeCompare(right.id, "en", { numeric: true }));
}

function roundDocuments(run) {
  const rounds = {};
  for (const attempt of Array.isArray(run?.superseded) ? run.superseded : []) {
    rounds[Number(attempt.round) || 1] = { worker: attempt.worker_output || null, review: attempt.review || null };
  }
  rounds[Number(run?.round) || 1] = { worker: run?.worker_output || null, review: run?.review || null };
  return rounds;
}

/**
 * One clock for a run. `now` only matters while the run is still open: the running stage and an
 * open wait for a person extend to it. Terminal runs end at their last recorded time.
 */
export function buildTimeline(run, history = null, { now = Date.now() } = {}) {
  const recordedStages = Array.isArray(run?.stages) ? run.stages : [];
  const origin = parse(run?.created_at) ?? parse(history?.history?.[0]?.at) ?? parse(recordedStages[0]?.started_at) ?? now;
  const relative = (value) => { const parsed = parse(value); return parsed === null ? null : Math.max(0, parsed - origin); };
  const events = eventsFrom(history, relative);
  const stages = recordedStages.map((stage, index) => ({
    key: `${Number(stage.round) || 1}-${stage.stage}-${index}`,
    stage: stage.stage,
    round: Number(stage.round) || 1,
    status: stage.status || "pending",
    startedAt: relative(stage.started_at),
    completedAt: relative(stage.completed_at),
    detail: stage.detail || null,
  })).filter((stage) => stage.startedAt !== null);
  const open = !isTerminalWorkflow(run?.state);
  const times = [
    relative(run?.completed_at), relative(run?.updated_at),
    ...stages.flatMap((stage) => [stage.startedAt, stage.completedAt]), ...events.map((event) => event.at),
  ].filter((value) => value !== null);
  const recordedEnd = Math.max(0, ...times);
  const end = open ? Math.max(recordedEnd, now - origin) : recordedEnd;

  // Each entry into the human stage is a decision point; the stage's end is when it was decided.
  const decisions = Array.isArray(run?.decisions) ? run.decisions : [];
  // The stage opens a moment before the transition and hand-off are written; a point is "reached"
  // once all three are recorded, and "decided" once the decision has been recorded.
  const decisionPoints = stages.filter((stage) => stage.stage === "human").map((stage) => {
    const entered = events.filter((event) => event.round === stage.round
      && ((event.kind === "transition" && event.to === "awaiting_human") || (event.kind === "agent.handoff" && event.detail.to === "human")));
    const decided = events.find((event) => event.kind === "transition" && event.from === "awaiting_human" && event.at >= stage.startedAt);
    return {
      round: stage.round,
      stageStart: stage.startedAt,
      at: Math.max(stage.startedAt, ...entered.map((event) => event.at)),
      decidedAt: stage.completedAt === null ? null : Math.max(stage.completedAt, decided?.at ?? 0),
      decision: decisions.find((decision) => Number(decision.round) === stage.round) || null,
    };
  });
  const squeezes = decisionPoints.map((point) => {
    const real = Math.max(0, (point.decidedAt ?? end) - point.stageStart);
    return { from: point.stageStart, to: point.stageStart + real, real, axis: Math.min(real, HUMAN_WAIT_AXIS_MS) };
  }).filter((squeeze) => squeeze.real > squeeze.axis);
  const toAxis = (real) => {
    let shift = 0;
    for (const squeeze of squeezes) {
      if (real >= squeeze.to) shift += squeeze.real - squeeze.axis;
      else if (real > squeeze.from) return squeeze.from - shift + ((real - squeeze.from) / squeeze.real) * squeeze.axis;
    }
    return real - shift;
  };
  const toReal = (axis) => {
    let shift = 0;
    for (const squeeze of squeezes) {
      const start = squeeze.from - shift;
      if (axis >= start + squeeze.axis) { shift += squeeze.real - squeeze.axis; continue; }
      if (axis > start) return squeeze.from + ((axis - start) / squeeze.axis) * squeeze.real;
      break;
    }
    return axis + shift;
  };
  return Object.freeze({
    run, origin, events, stages, end, open, decisionPoints, squeezes, toAxis, toReal,
    axisEnd: toAxis(end), rounds: roundDocuments(run), hasHistory: events.length > 0,
  });
}

// ---- snapshots -----------------------------------------------------------------------------

function stageAt(stage, at, full) {
  const done = stage.completedAt !== null && stage.completedAt <= at;
  let status = done || full ? stage.status : "running";
  if (stage.stage === "human" && status === "running") status = "waiting";
  return { ...stage, status, completedAt: done ? stage.completedAt : null, detail: done ? stage.detail : null };
}

function replayState(seen, stages) {
  const transitions = seen.filter((event) => event.kind === "transition");
  if (transitions.length) {
    const last = transitions.at(-1);
    return { state: last.to, round: last.round };
  }
  const active = [...stages].reverse().find((stage) => stage.status === "running" || stage.status === "waiting");
  return { state: STAGE_STATES[active?.stage] || "planning", round: active?.round || 1 };
}

/** What was recorded by time `t` (milliseconds after the run was created). */
export function snapshotAt(model, t = model.end) {
  const full = t >= model.end;
  const at = full ? model.end : Math.max(0, t);
  const run = model.run || {};
  const seen = full ? model.events : model.events.filter((event) => event.at <= at);
  const stages = model.stages.filter((stage) => stage.startedAt <= at).map((stage) => stageAt(stage, at, full));
  const { state, round: currentRound } = full ? { state: run.state, round: Number(run.round) || 1 } : replayState(seen, stages);
  const reached = (kind, round) => full || seen.some((event) => event.kind === kind && event.round === round);
  const decisions = (Array.isArray(run.decisions) ? run.decisions : []).filter((decision) => {
    if (full) return true;
    const decided = parse(decision.decided_at);
    return decided !== null && decided - model.origin <= at;
  });
  const rounds = {};
  // A full view also lists the run's own round and any superseded round, even without their stages.
  const roundNumbers = new Set(stages.map((stage) => stage.round));
  if (full) for (const roundNumber of [currentRound, ...Object.keys(model.rounds).map(Number)]) roundNumbers.add(roundNumber);
  for (const roundNumber of [...roundNumbers].sort((left, right) => left - right)) {
    const documents = model.rounds[roundNumber] || {};
    const inRound = (kind) => seen.filter((event) => event.kind === kind && event.round === roundNumber);
    rounds[roundNumber] = {
      round: roundNumber,
      toolCalls: inRound("tool.call"),
      modelCalls: inRound("model.invocation"),
      modelStarts: inRound("model.started"),
      worker: reached("worker.completed", roundNumber) ? documents.worker || null : null,
      review: reached("review.completed", roundNumber) ? documents.review || null : null,
      correctionNote: roundNumber > 1 ? decisions.find((decision) => Number(decision.round) === roundNumber - 1)?.note || null : null,
    };
  }
  const planReached = full || seen.some((event) => event.kind === "plan.created" || (event.kind === "transition" && event.from === "planning"));
  const actions = full
    ? (Array.isArray(run.available_actions) ? run.available_actions : [])
    : state === "awaiting_human" ? AWAITING_ACTIONS : ACTIVE_WORKFLOW_STATES.has(state) ? ["cancel"] : [];
  const activeStage = [...stages].reverse().find((stage) => stage.status === "running" || stage.status === "waiting") || null;
  return {
    t: at, full, state, round: currentRound, stages, plan: planReached ? run.plan || null : null, rounds, decisions,
    events: seen, actions, activeStage, terminal: isTerminalWorkflow(state),
  };
}

// ---- lanes and relay -----------------------------------------------------------------------

export const LANES = STAGE_ORDER;

function laneIndex(role) { return LANES.indexOf(role); }

/** Positions in percent of the drawing width. The axis grows with time, so the future is never drawn. */
export function laneView(model, snapshot) {
  const now = model.toAxis(snapshot.t);
  const settled = snapshot.terminal && snapshot.full;
  const domain = settled ? Math.max(now, 1) : Math.max(now * AXIS_HEADROOM, MIN_AXIS_MS);
  const x = (real) => round(Math.min(100, Math.max(0, (model.toAxis(real) / domain) * 100)));
  const span = (from, to) => round(Math.max(0, x(to) - x(from)));
  const lanes = LANES.map((role) => {
    const stages = snapshot.stages.filter((stage) => stage.stage === role);
    const current = [...stages].reverse().find((stage) => stage.status === "running" || stage.status === "waiting") || null;
    const latest = stages.at(-1) || null;
    const segments = stages.map((stage) => {
      const finish = stage.completedAt ?? snapshot.t;
      const squeeze = model.squeezes.find((item) => item.from === stage.startedAt && role === "human");
      return {
        key: `segment-${stage.key}`, round: stage.round, status: stage.status, x: x(stage.startedAt), width: span(stage.startedAt, finish),
        durationMs: finish - stage.startedAt, shortened: Boolean(squeeze && finish - stage.startedAt > HUMAN_WAIT_AXIS_MS),
      };
    });
    const models = snapshot.events.filter((event) => event.kind === "model.invocation" && event.role === role).map((event) => ({
      key: `model-${event.id}`, x: x(event.startedAt ?? event.at), width: span(event.startedAt ?? event.at, event.at),
      retry: event.detail.outcome !== "succeeded", outcome: event.detail.outcome || "", model: event.detail.model || "",
      attempt: Number(event.detail.attempt) || 1, durationMs: Number(event.detail.duration_ms) || 0,
    }));
    const tools = role === "worker" ? snapshot.events.filter((event) => event.kind === "tool.call").map((event) => ({
      key: `tool-${event.id}`, x: x(event.at), failed: event.detail.outcome !== "succeeded", tool: event.detail.tool_name || "tool",
      outcome: event.detail.outcome || "", durationMs: Number(event.detail.duration_ms) || 0,
    })) : [];
    return {
      role, status: current?.status || latest?.status || "pending", active: Boolean(current),
      elapsedMs: current ? snapshot.t - current.startedAt : null,
      durationMs: !current && latest && latest.completedAt !== null ? latest.completedAt - latest.startedAt : null,
      detail: !current && latest ? latest.detail : null,
      round: (current || latest)?.round || null, segments, models, tools,
    };
  });
  const handoffs = snapshot.events.filter((event) => event.kind === "agent.handoff" && laneIndex(event.detail.from) >= 0 && laneIndex(event.detail.to) >= 0);
  const batons = handoffs.map((event) => ({
    key: `baton-${event.id}`, x: x(event.at), from: laneIndex(event.detail.from), to: laneIndex(event.detail.to),
    correction: event.detail.from === "human",
  }));
  const secondRound = snapshot.stages.find((stage) => stage.round > 1);
  return {
    lanes, batons,
    roundMark: secondRound ? { x: x(secondRound.startedAt), round: secondRound.round } : null,
    playhead: settled ? null : x(snapshot.t),
  };
}

/** Narrow columns: four stations and where the baton is now. */
export function relayView(snapshot) {
  const stations = LANES.map((role) => {
    const stages = snapshot.stages.filter((stage) => stage.stage === role);
    const stage = [...stages].reverse().find((item) => item.round === snapshot.round) || stages.at(-1) || null;
    const active = stage && (stage.status === "running" || stage.status === "waiting");
    return {
      role, status: stage?.status || "pending",
      elapsedMs: active ? snapshot.t - stage.startedAt : null,
      durationMs: stage && !active && stage.completedAt !== null ? stage.completedAt - stage.startedAt : null,
      detail: stage && !active ? stage.detail : null,
    };
  });
  const latest = snapshot.stages.at(-1);
  const holder = snapshot.activeStage?.stage || (snapshot.decisions.length ? "human" : latest?.stage) || "planner";
  return { stations, baton: Math.max(0, laneIndex(holder)), loop: snapshot.stages.some((stage) => stage.round > 1) };
}

// ---- the "now" line ------------------------------------------------------------------------

function pendingModelCall(snapshot, role, roundNumber) {
  const view = snapshot.rounds[roundNumber];
  if (!view) return null;
  const started = view.modelStarts.filter((event) => event.role === role);
  const finished = view.modelCalls.filter((event) => event.role === role);
  if (started.length > finished.length) return { attempt: Number(started.at(-1).detail.attempt) || started.length };
  const last = finished.at(-1);
  return last && last.detail.outcome !== "succeeded" ? { retryAfter: last.detail.outcome } : null;
}

/** One sentence about what is happening, built only from recorded facts. */
export function nowView(model, snapshot, labels = DEFAULT_MULTI_AGENT_LABELS) {
  if (snapshot.state === "awaiting_human") {
    const since = snapshot.activeStage ? snapshot.t - snapshot.activeStage.startedAt : null;
    return { tone: "you", role: "human", text: snapshot.full ? labels.yourTurn : "Waiting for a person to decide.", sinceMs: since, waiting: false, tools: [] };
  }
  if (snapshot.terminal) {
    const status = workflowStatus(snapshot.state, labels);
    return { tone: "done", role: null, text: `${status.label}. ${status.detail}`.trim(), sinceMs: null, waiting: false, tools: [] };
  }
  const stage = snapshot.activeStage;
  if (!stage) return { tone: "idle", role: null, text: workflowStatus(snapshot.state, labels).detail, sinceMs: null, waiting: true, tools: [] };
  const view = snapshot.rounds[stage.round] || { toolCalls: [] };
  let text;
  if (stage.stage === "planner") text = "The Planner is choosing read-only steps";
  else if (stage.stage === "worker") {
    const steps = snapshot.plan?.steps?.length || 0;
    const calls = view.toolCalls.length;
    text = steps && calls < steps
      ? `The Worker is calling tools (${calls} of ${steps} done)`
      : `The Worker is writing findings from ${calls} tool result${calls === 1 ? "" : "s"}`;
  } else if (stage.stage === "reviewer") text = "The Reviewer is checking the evidence against the template's checks";
  else text = humaniseValue(stage.stage);
  const pending = pendingModelCall(snapshot, stage.stage, stage.round);
  if (pending?.attempt) text += ` · waiting on the model${pending.attempt > 1 ? ` (attempt ${pending.attempt})` : ""}`;
  else if (pending?.retryAfter) text += ` · retrying after ${humaniseValue(pending.retryAfter).toLowerCase()}`;
  const tools = stage.stage === "planner" ? [] : view.toolCalls.map((event) => ({
    key: `pill-${event.id}`, tool: String(event.detail.tool_name || "tool").replace(/\.v\d+$/, ""), ok: event.detail.outcome === "succeeded",
    outcome: event.detail.outcome || "",
  }));
  return { tone: "agent", role: stage.stage, text, sinceMs: snapshot.t - stage.startedAt, waiting: true, tools };
}

// ---- decisions -----------------------------------------------------------------------------

/** Critical and high checks that failed: the template guidance's usual bar for approving. */
export function blockingFailures(review) {
  return groupFindings(review?.findings).failed.filter((finding) => finding.severity === "critical" || finding.severity === "high").length;
}

/** A short name for one check; the message stays one click away. */
export function checkName(finding) {
  if (finding?.source === "model") return `Reviewer: ${finding.message}`;
  return humaniseValue(finding?.check_id || finding?.id || "check");
}

export function decisionLabel(action, roundNumber, labels = DEFAULT_MULTI_AGENT_LABELS) {
  const definition = action === "correct" && roundNumber >= MAX_WORKFLOW_ROUNDS ? labels.finalCorrection : labels.decisionOptions?.[action];
  return definition?.label || humaniseValue(action);
}

// ---- replay --------------------------------------------------------------------------------

/**
 * Advance a replay by `axisMs` of axis time. Agent time plays at real speed; a wait for a person
 * plays shortened. The replay stops at each decision point the first time it reaches one.
 */
export function advanceReplay(model, t, axisMs, pausedAt = new Set()) {
  const target = model.toReal(model.toAxis(t) + Math.max(0, axisMs));
  const point = model.decisionPoints.find((item) => item.at > t && item.at <= target && !pausedAt.has(item.round));
  if (point) return { t: point.at, point, ended: false };
  if (target >= model.end) return { t: model.end, point: null, ended: true };
  return { t: target, point: null, ended: false };
}

/** Distinct recorded moments, for stepping one event at a time. */
export function eventTimes(model) {
  return [...new Set([0, ...model.events.map((event) => event.at), ...model.stages.flatMap((stage) => [stage.startedAt, stage.completedAt]).filter((value) => value !== null), model.end])]
    .sort((left, right) => left - right);
}

export function formatClock(milliseconds) {
  const total = Math.max(0, Math.round(milliseconds / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

/** A plain sentence for one recorded event, for the activity log and replay announcements. */
export function eventSentence(event, labels = DEFAULT_MULTI_AGENT_LABELS) {
  const detail = event?.detail || {};
  const role = ROLE_NAMES[event?.role] || humaniseValue(event?.role);
  switch (event?.kind) {
    case "transition": return `${workflowStatus(event.to, labels).label}. ${event.reason}`.trim();
    case "run.created": return "Run accepted.";
    case "agent.handoff": return `Hand-off from ${ROLE_NAMES[detail.from] || humaniseValue(detail.from)} to ${ROLE_NAMES[detail.to] || humaniseValue(detail.to)}.`;
    case "plan.created": return `Plan created with ${Array.isArray(detail.steps) ? detail.steps.length : Number(detail.steps) || 0} steps.`;
    case "model.started": return `${role} model call started${Number(detail.attempt) > 1 ? ` (attempt ${detail.attempt})` : ""}.`;
    case "model.invocation": return `${role} model call ${humaniseValue(detail.outcome).toLowerCase() || "returned"} after ${formatDuration(detail.duration_ms)}${detail.model ? ` (${detail.model})` : ""}.`;
    case "model.fallback": return `${role} used the deterministic fallback.`;
    case "tool.call": return `Worker called ${detail.tool_name || "a tool"}: ${humaniseValue(detail.outcome).toLowerCase()} in ${formatDuration(detail.duration_ms)}.`;
    case "tool.rejected": return `A call to ${detail.tool_name || "a tool"} was rejected.`;
    case "worker.completed": return `Worker finished with ${Array.isArray(detail.evidence_ids) ? detail.evidence_ids.length : 0} evidence records.`;
    case "review.completed": return `Reviewer finished with ${Number(detail.findings) || 0} checks.`;
    case "decision.recorded": return `${event.actor || "A person"} decided: ${decisionLabel(detail.decision, Number(detail.decision_round) || event.round, labels)}.`;
    case "run.failed": return "The run failed.";
    case "run.cancelled": return "The run was cancelled.";
    default: return humaniseValue(event?.kind);
  }
}
