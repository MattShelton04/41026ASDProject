/** Feature-agnostic Planner → Worker → Reviewer → human panel over a feature backend proxy. */
import { append, createLatestTask, el } from "../browser/index.js";
import {
  MAX_WORKFLOW_ROUNDS, humaniseValue, isActiveWorkflow, isTerminalWorkflow, mergeLabels, shortRunId,
  workflowStatus,
} from "./definitions.js";
import {
  createRenderContext, drawer, renderDecisionLog, renderHistory, renderOutcome, renderPlan, renderProblem,
  renderRecordedDecision, renderReview, renderSuperseded, renderWorker, statusBadge,
} from "./components.js";
import { buildDecisionForm, buildStartForm, setFieldError } from "./forms.js";
import { nextWorkflowPollDelay } from "./polling.js";
import {
  availableDecisions, canCancel, fieldProblems, formatTimestamp, groupFindings, historyView, problemView,
  runPresentationKey, startFields, validateDecision, validateStartInput,
} from "./projections.js";
import { createLaneBoard, createNowLine, createRelayStrip, createReplayBar, renderReviewerSide } from "./relay.js";
import {
  advanceReplay, blockingFailures, buildTimeline, decisionLabel, emptyHistory, eventSentence, eventTimes,
  formatClock, laneView, mergeHistory, nowView, relayView, snapshotAt,
} from "./timeline.js";

let panelInstance = 0;
// Under reduced motion a replay steps from one recorded moment to the next instead of gliding.
const REDUCED_STEP_MS = 900;

function isAbort(error) { return error?.name === "AbortError"; }

function emptyDraft(actor = "") {
  return { decision: "", note: "", actor: String(actor || ""), acceptedStepIds: [] };
}

function reducedMotion() {
  try { return Boolean(globalThis.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches); } catch { return false; }
}

const clock = () => globalThis.performance?.now?.() ?? Date.now();
const requestFrame = (callback) => (typeof globalThis.requestAnimationFrame === "function"
  ? globalThis.requestAnimationFrame(callback)
  : setTimeout(() => callback(clock()), 16));
const cancelFrame = (handle) => {
  if (typeof globalThis.cancelAnimationFrame === "function") globalThis.cancelAnimationFrame(handle);
  clearTimeout(handle);
};

function findDisclosure(node, key) {
  if (!node || !key) return null;
  if (node.dataset?.disclosure === key) return node;
  for (const child of node.children || []) {
    const match = findDisclosure(child, key);
    if (match) return match;
  }
  return null;
}

function findById(node, id) {
  if (!node || !id) return null;
  if (node.id === id) return node;
  for (const child of node.children || []) {
    const match = findById(child, id);
    if (match) return match;
  }
  return null;
}

export function createMultiAgentPanel({
  root,
  client,
  initialInput = {},
  hiddenInputs = [],
  runId = null,
  actor = "",
  requestedBy = "",
  announce = null,
  labels: labelOverrides = {},
  title = "",
  description = "",
  historyHref = null,
  onRunChange = null,
  pollDelay = nextWorkflowPollDelay,
} = {}) {
  if (!root || !client) throw new TypeError("createMultiAgentPanel requires root and client");
  const labels = mergeLabels(labelOverrides);
  const instanceId = `ps-multi-agent-${++panelInstance}`;
  const context = createRenderContext(labels);
  const runTask = createLatestTask();
  const templateTask = createLatestTask();
  const historyTask = createLatestTask();
  const state = {
    descriptor: null,
    fields: [],
    templateProblem: null,
    run: null,
    runKey: "",
    runProblem: null,
    pollTimer: null,
    pollFailures: 0,
    pollWarning: null,
    startVisible: !runId,
    startPending: false,
    decisionDraft: emptyDraft(actor),
    decisionPending: false,
    decisionProblem: null,
    decisionErrors: {},
    cancelConfirm: false,
    cancelPending: false,
    cancelProblem: null,
    history: { data: emptyHistory(), loaded: false, loading: false, problem: null },
    frame: null,
    replay: null,
    drawerCounts: new Map(),
    // New lane marks animate only once a run has been drawn, never when a run is first opened.
    animate: false,
    destroyed: false,
  };

  // Layout follows the mounting column, not the viewport (see styles.css container queries).
  root.classList.add("ps-multi-agent-container");
  const shell = el("section", "ps-multi-agent");
  const header = el("header", "ps-multi-agent__header");
  const heading = el("h2", "ps-multi-agent__title", title || labels.title || labels.eyebrow);
  heading.id = `${instanceId}-title`;
  heading.tabIndex = -1;
  shell.setAttribute("aria-labelledby", heading.id);
  const objective = el("p", "ps-multi-agent__objective", description);
  const toolNote = el("p", "ps-multi-agent__tool-note", labels.unavailableTool);
  toolNote.hidden = true;
  append(header, el("p", "ps-eyebrow", labels.eyebrow), heading, objective, toolNote);
  const templateHost = el("div", "ps-multi-agent__template-status");
  const startHost = el("div", "ps-multi-agent__start-host");
  const runHost = el("div", "ps-multi-agent__run-host");
  const liveRegion = el("div", "ps-multi-agent__sr-only");
  liveRegion.setAttribute("role", "status");
  liveRegion.setAttribute("aria-live", "polite");
  append(shell, header, templateHost, startHost, runHost, liveRegion);
  root.replaceChildren(shell);
  let startForm = null;
  // Nodes from the latest run render that later actions move focus to.
  const refs = { runTitle: null, cancel: null, confirmCancel: null, article: null };

  const publishStatus = (message) => {
    if (!message || state.destroyed) return;
    if (typeof announce === "function") announce(message);
    else liveRegion.textContent = message;
  };

  // ---- template and start form -------------------------------------------------------------
  function renderTemplateStatus() {
    templateHost.replaceChildren();
    if (state.templateProblem) {
      const problem = renderProblem(state.templateProblem, { heading: "The workflow could not be loaded" });
      const retry = el("button", "ps-button ps-button--small", "Try again");
      retry.type = "button";
      retry.dataset.action = "reload-template";
      retry.addEventListener("click", () => loadTemplate());
      append(problem, retry);
      append(templateHost, problem);
    } else if (!state.descriptor) {
      append(templateHost, el("p", "ps-multi-agent__loading", labels.loadingTemplate));
    }
  }

  function renderStartForm() {
    startHost.replaceChildren();
    startForm = null;
    if (!state.descriptor || !state.startVisible) return;
    startForm = buildStartForm({ fields: state.fields, instanceId, initialInput, labels });
    if (state.run && isTerminalWorkflow(state.run.state)) startForm.heading.textContent = labels.startAgain;
    startForm.form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitStart();
    });
    setStartPending(state.startPending);
    append(startHost, startForm.form);
  }

  function setStartPending(pending) {
    state.startPending = pending;
    if (!startForm) return;
    startForm.form.setAttribute("aria-busy", String(pending));
    startForm.submit.disabled = pending;
    startForm.submit.setAttribute("aria-busy", String(pending));
    startForm.submit.textContent = pending ? labels.starting : labels.start;
  }

  async function loadTemplate() {
    const task = templateTask.start();
    state.templateProblem = null;
    renderTemplateStatus();
    try {
      const { body } = await client.getTemplate({ signal: task.signal });
      if (!task.isCurrent() || state.destroyed) return;
      state.descriptor = body;
      state.fields = startFields(body, { hiddenInputs, initialInput });
      const template = body?.template || {};
      if (!title) heading.textContent = template.title || labels.eyebrow;
      if (!description) objective.textContent = template.objective || "";
      toolNote.hidden = !(body?.tools || []).some((tool) => tool.available === false);
      renderTemplateStatus();
      renderStartForm();
      if (state.run) renderRun({ force: true });
    } catch (error) {
      if (!task.isCurrent() || state.destroyed || isAbort(error)) return;
      state.templateProblem = problemView(error);
      renderTemplateStatus();
    }
  }

  function showStartErrors(errors, problem = null) {
    if (!startForm) return;
    let first = null;
    for (const [name, ref] of startForm.refs) {
      setFieldError(ref, errors[name]);
      if (errors[name] && !first) first = ref.control;
    }
    startForm.problem.replaceChildren();
    const hidden = state.fields.filter((field) => field.hidden && errors[field.name]);
    if (problem) append(startForm.problem, renderProblem(problem, { heading: "The review could not start" }));
    else if (hidden.length) {
      append(startForm.problem, renderProblem({
        title: "This page supplied an invalid workflow input",
        detail: hidden.map((field) => `${field.title}: ${errors[field.name]}`).join(" "),
        code: "", status: 0, requestId: "", errors: [],
      }));
    }
    if (first) first.focus();
    else if (problem || hidden.length) startForm.problem.firstChild?.focus?.();
  }

  async function submitStart(override = undefined) {
    if (state.destroyed || state.startPending) return null;
    let input = override;
    if (input === undefined) {
      const result = validateStartInput(state.fields, startForm ? startForm.values() : initialInput);
      if (!result.valid) {
        showStartErrors(result.errors);
        publishStatus("Check the highlighted fields.");
        return null;
      }
      input = result.input;
    }
    showStartErrors({});
    setStartPending(true);
    try {
      const { body } = await client.startRun(input, { requestedBy: requestedBy || state.decisionDraft.actor || actor });
      if (state.destroyed) return null;
      setStartPending(false);
      state.startVisible = false;
      renderStartForm();
      resetRunScopedState();
      setRun(body, { announceChange: false });
      state.animate = true;
      publishStatus(`Review started. ${workflowStatus(body?.state, labels).label}.`);
      focusRunHeading();
      fetchHistory({ force: true });
      return body;
    } catch (error) {
      if (state.destroyed || isAbort(error)) return null;
      setStartPending(false);
      const problem = problemView(error);
      showStartErrors(fieldProblems(problem, state.fields.map((field) => field.name)), problem);
      publishStatus(`The review could not start. ${problem.title}`);
      return null;
    }
  }

  // ---- run lifecycle -------------------------------------------------------------------------
  function resetRunScopedState() {
    stopReplay();
    state.decisionDraft = emptyDraft(state.decisionDraft.actor || actor);
    state.decisionErrors = {};
    state.decisionProblem = null;
    state.cancelConfirm = false;
    state.cancelProblem = null;
    state.pollFailures = 0;
    state.pollWarning = null;
    historyTask.cancel();
    state.history = { data: emptyHistory(), loaded: false, loading: false, problem: null };
    state.frame = null;
    state.replay = null;
    state.drawerCounts.clear();
    state.animate = false;
    context.disclosures.clear();
  }

  function setRun(run, { announceChange = true } = {}) {
    if (state.destroyed || !run) return;
    const previous = state.run;
    if (previous && previous.id !== run.id) resetRunScopedState();
    state.run = run;
    state.runProblem = null;
    renderRun();
    if (announceChange && previous?.state !== run.state) {
      const status = workflowStatus(run.state, labels);
      publishStatus(`${status.label}. ${status.detail}`);
    }
    if (previous?.state !== run.state || previous?.id !== run.id) onRunChange?.(run);
    schedulePoll();
  }

  function schedulePoll() {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
    if (state.destroyed || !state.run?.id) return;
    const delay = pollDelay(state.run.state, state.pollFailures, Boolean(globalThis.document?.hidden));
    if (delay === null || delay === undefined) return;
    state.pollTimer = setTimeout(pollRun, delay);
  }

  async function pollRun() {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
    const id = state.run?.id;
    if (state.destroyed || !id) return;
    const task = runTask.start();
    try {
      const { body } = await client.getRun(id, { signal: task.signal });
      if (!task.isCurrent() || state.destroyed) return;
      state.pollFailures = 0;
      const recovered = Boolean(state.pollWarning);
      state.pollWarning = null;
      const changed = state.run?.state !== body?.state || state.run?.round !== body?.round;
      if (recovered) renderRun({ force: true });
      setRun(body);
      // History is read alongside the run; a state change always catches up immediately.
      fetchHistory({ force: changed });
    } catch (error) {
      if (!task.isCurrent() || state.destroyed || isAbort(error)) return;
      state.pollFailures += 1;
      state.pollWarning = problemView(error);
      renderRun({ force: true });
      schedulePoll();
    }
  }

  async function openRun(id) {
    if (state.destroyed || !id) return null;
    clearTimeout(state.pollTimer);
    const task = runTask.start();
    state.startVisible = false;
    renderStartForm();
    stopReplay();
    runHost.replaceChildren(el("p", "ps-multi-agent__loading", "Loading the review run…"));
    runHost.setAttribute("aria-busy", "true");
    try {
      const { body } = await client.getRun(id, { signal: task.signal });
      if (!task.isCurrent() || state.destroyed) return null;
      runHost.removeAttribute("aria-busy");
      if (state.run?.id !== body?.id) resetRunScopedState();
      // The loading message replaced the run DOM, so the reopened run must render even if unchanged.
      state.run = null;
      state.runKey = "";
      state.frame = null;
      setRun(body, { announceChange: false });
      publishStatus(`Opened review run ${shortRunId(body?.id)}. ${workflowStatus(body?.state, labels).label}.`);
      fetchHistory({ force: true });
      return body;
    } catch (error) {
      if (!task.isCurrent() || state.destroyed || isAbort(error)) return null;
      runHost.removeAttribute("aria-busy");
      state.runProblem = problemView(error);
      runHost.replaceChildren(renderProblem(state.runProblem, { heading: "The review run could not be loaded" }));
      const retry = el("button", "ps-button ps-button--small", "Try again");
      retry.type = "button";
      retry.dataset.action = "reload-run";
      retry.addEventListener("click", () => openRun(id));
      append(runHost.firstChild, retry);
      return null;
    }
  }

  function focusRunHeading() { refs.runTitle?.focus?.(); }

  // ---- history -------------------------------------------------------------------------------
  /**
   * Read new transitions and audit events after the known cursors. While one read is in flight a
   * routine poll skips; a forced read (open, start, decision, state change) replaces it.
   */
  async function fetchHistory({ force = false } = {}) {
    const run = state.run;
    if (!run || state.destroyed || (state.history.loading && !force)) return;
    const current = state.history.data.runId === run.id ? state.history.data : emptyHistory(run.id);
    const task = historyTask.start();
    state.history.loading = true;
    try {
      const { body } = await client.getHistory(run.id, { afterHistory: current.afterHistory, afterAudit: current.afterAudit, signal: task.signal });
      if (!task.isCurrent() || state.destroyed || state.run?.id !== run.id) return;
      state.history = { data: mergeHistory(current, { ...body, run_id: run.id }), loaded: true, loading: false, problem: null };
    } catch (error) {
      if (!task.isCurrent() || state.destroyed || isAbort(error)) return;
      state.history = { ...state.history, loading: false, problem: problemView(error) };
    }
    renderRun();
    // From here on, marks that arrive with later polls are new and may animate.
    if (!isTerminalWorkflow(state.run?.state)) state.animate = true;
  }

  // ---- decisions and cancellation ------------------------------------------------------------
  async function submitDecision(form) {
    const run = state.run;
    if (state.destroyed || state.decisionPending || !run) return;
    form.sync();
    const result = validateDecision(state.decisionDraft, run);
    // Until a choice is made only the choice can be wrong; the other fields are still hidden.
    state.decisionErrors = state.decisionDraft.decision ? result.errors : { decision: labels.chooseFirst };
    state.decisionProblem = null;
    if (!state.decisionDraft.decision || !result.valid) {
      showDecisionErrors(form);
      publishStatus("Check the highlighted decision fields.");
      return;
    }
    state.decisionPending = true;
    renderRun({ force: true });
    try {
      const { body } = await client.decide(run.id, result.body);
      if (state.destroyed) return;
      state.decisionPending = false;
      const recorded = decisionLabel(result.body.decision, Number(run.round) || 1, labels);
      state.decisionDraft = emptyDraft(result.body.actor);
      state.decisionErrors = {};
      setRun(body, { announceChange: false });
      renderRun({ force: true });
      publishStatus(`Decision recorded: ${recorded}. ${workflowStatus(body?.state, labels).label}.`);
      focusRunHeading();
      fetchHistory({ force: true });
    } catch (error) {
      if (state.destroyed || isAbort(error)) return;
      state.decisionPending = false;
      state.decisionProblem = problemView(error);
      state.decisionErrors = fieldProblems(state.decisionProblem, ["decision", "note", "actor", "accepted_step_ids"]);
      renderRun({ force: true });
      publishStatus(`The decision was not recorded. ${state.decisionProblem.title}`);
      // A 409 means the run moved on (another reviewer, or a cancel); show its current state.
      if (state.decisionProblem.status === 409) pollRun();
    }
  }

  function showDecisionErrors(form) {
    let first = null;
    for (const [name, ref] of Object.entries(form.refs)) {
      setFieldError(ref, state.decisionErrors[name]);
      if (state.decisionErrors[name] && !first) first = ref.focus;
    }
    form.problem.replaceChildren();
    if (state.decisionProblem) append(form.problem, renderProblem(state.decisionProblem, { heading: "The decision was not recorded" }));
    (first || form.problem.firstChild)?.focus?.();
  }

  async function cancelRun() {
    const run = state.run;
    if (state.destroyed || state.cancelPending || !run || !canCancel(run)) return;
    state.cancelPending = true;
    state.cancelProblem = null;
    renderRun({ force: true });
    try {
      const { body } = await client.cancel(run.id, { actor: state.decisionDraft.actor || actor });
      if (state.destroyed) return;
      state.cancelPending = false;
      state.cancelConfirm = false;
      setRun(body, { announceChange: false });
      renderRun({ force: true });
      publishStatus(`${workflowStatus(body?.state, labels).label}.`);
      focusRunHeading();
      fetchHistory({ force: true });
    } catch (error) {
      if (state.destroyed || isAbort(error)) return;
      state.cancelPending = false;
      state.cancelProblem = problemView(error);
      renderRun({ force: true });
      publishStatus(`Cancellation failed. ${state.cancelProblem.title}`);
      if (state.cancelProblem.status === 409) pollRun();
    }
  }

  // ---- timeline, frame and replay ------------------------------------------------------------
  let terminalModel = { key: "", model: null };
  function currentModel() {
    const run = state.run;
    if (!isTerminalWorkflow(run?.state)) return buildTimeline(run, state.history.data, { now: Date.now() });
    // A finished run never changes, so its model is built once per run and history.
    const key = `${run.id}|${run.updated_at}|${state.history.data.afterHistory}|${state.history.data.afterAudit}`;
    if (terminalModel.key !== key) terminalModel = { key, model: buildTimeline(run, state.history.data) };
    return terminalModel.model;
  }

  function replaying(model) { return Boolean(state.replay) && state.replay.t < model.end; }

  function currentSnapshot(model) {
    return snapshotAt(model, replaying(model) ? state.replay.t : model.end);
  }

  function ensureFrame(run, model) {
    if (!state.frame || state.frame.runId !== run.id) {
      state.frame = { runId: run.id, board: createLaneBoard(labels), relay: createRelayStrip(labels), now: createNowLine(), replay: null, replayKey: "" };
    }
    // A replay needs recorded events, so it is offered only for finished runs with history.
    const replayKey = isTerminalWorkflow(run.state) && model.hasHistory ? terminalModel.key : "";
    if (replayKey !== state.frame.replayKey) {
      state.frame.replayKey = replayKey;
      state.frame.replay = replayKey ? createReplayBar({ model, labels, onCommand: replayCommand }) : null;
    }
    return state.frame;
  }

  function describe(model, snapshot) {
    const status = workflowStatus(snapshot.state, labels);
    return `${formatClock(model.toAxis(snapshot.t))} of ${formatClock(model.axisEnd)}. Round ${snapshot.round}. ${status.label}.`;
  }

  function renderFrame(model = currentModel(), snapshot = currentSnapshot(model)) {
    const frame = state.frame;
    if (!frame || !state.run) return;
    const animate = state.replay ? Boolean(state.replay.playing || state.replay.stepping) : state.animate;
    frame.board.update(laneView(model, snapshot), { animate, live: snapshot.full });
    frame.relay.update(relayView(snapshot), { live: snapshot.full });
    frame.now.update(nowView(model, snapshot, labels), { animate });
    frame.replay?.update({
      t: snapshot.t, playing: Boolean(state.replay?.playing), speed: state.replay?.speed || 2, description: describe(model, snapshot),
    });
  }

  function replayState(model) {
    if (!state.replay) state.replay = { t: model.end, playing: false, stepping: false, speed: 2, pausedAt: new Set(), handle: null, last: 0, lastState: "" };
    return state.replay;
  }

  function stopReplay() {
    if (!state.replay) return;
    state.replay.playing = false;
    cancelFrame(state.replay.handle);
    clearTimeout(state.replay.handle);
    state.replay.handle = null;
  }

  function replayCommand(command) {
    if (state.destroyed || !state.run) return;
    const model = currentModel();
    const replay = replayState(model);
    const pause = () => { stopReplay(); };
    if (command.type === "toggle") {
      if (replay.playing) pause();
      else {
        if (replay.t >= model.end) { replay.t = 0; replay.pausedAt.clear(); }
        replay.playing = true;
        replay.last = clock();
        scheduleReplay();
        publishStatus(`Replaying the recorded run. ${describe(model, snapshotAt(model, replay.t))}`);
      }
    } else if (command.type === "step") {
      pause();
      const times = eventTimes(model);
      const target = command.direction > 0 ? times.find((time) => time > replay.t + 0.5) : [...times].reverse().find((time) => time < replay.t - 0.5);
      replay.t = target ?? (command.direction > 0 ? model.end : 0);
      replay.stepping = command.direction > 0;
      const snapshot = snapshotAt(model, replay.t);
      const last = snapshot.events.at(-1);
      publishStatus(last && last.at === replay.t ? eventSentence(last, labels) : describe(model, snapshot));
    } else if (command.type === "seek") {
      pause();
      replay.t = command.atEnd ? model.end : Math.min(model.end, model.toReal(command.axis));
    } else if (command.type === "speed") {
      replay.speed = command.value;
    } else if (command.type === "jump") {
      pause();
      const point = model.decisionPoints.find((item) => item.round === command.round);
      if (point) {
        replay.t = point.at;
        replay.pausedAt.add(point.round);
        publishStatus(`Replay at the round ${point.round} decision.`);
      }
    } else if (command.type === "end") {
      pause();
      replay.t = model.end;
    } else if (command.type === "continue") {
      const point = model.decisionPoints.find((item) => item.at <= replay.t && (item.decidedAt === null || item.decidedAt > replay.t));
      if (point?.decidedAt !== null && point?.decidedAt !== undefined) replay.t = point.decidedAt;
      replay.playing = true;
      replay.last = clock();
      scheduleReplay();
    }
    renderRun();
    renderFrame(model);
    replay.stepping = false;
  }

  function scheduleReplay() {
    const replay = state.replay;
    if (!replay?.playing || state.destroyed) return;
    if (reducedMotion()) replay.handle = setTimeout(() => tickReplay(clock(), true), REDUCED_STEP_MS / replay.speed);
    else replay.handle = requestFrame((timestamp) => tickReplay(timestamp, false));
  }

  function tickReplay(timestamp, discrete) {
    const replay = state.replay;
    if (!replay?.playing || state.destroyed || !state.run) return;
    const model = currentModel();
    let result;
    if (discrete) {
      // Jump to the next recorded moment; a decision point still stops the replay.
      const next = eventTimes(model).find((time) => time > replay.t + 0.5) ?? model.end;
      const point = model.decisionPoints.find((item) => item.at > replay.t && item.at <= next && !replay.pausedAt.has(item.round));
      result = point ? { t: point.at, point, ended: false } : { t: next, point: null, ended: next >= model.end };
    } else {
      const elapsed = Math.min(100, Math.max(0, timestamp - replay.last)) * replay.speed;
      result = advanceReplay(model, replay.t, elapsed, replay.pausedAt);
    }
    replay.last = timestamp;
    replay.t = result.t;
    replay.stepping = true;
    if (result.point) {
      replay.pausedAt.add(result.point.round);
      replay.playing = false;
      publishStatus(`Replay paused at the round ${result.point.round} decision. Continue when you are ready.`);
    } else if (result.ended) {
      replay.playing = false;
      publishStatus("Replay finished. The recorded outcome is shown.");
    }
    const snapshot = snapshotAt(model, replay.t);
    if (replay.playing && replay.lastState && replay.lastState !== snapshot.state) {
      publishStatus(`Replay: ${workflowStatus(snapshot.state, labels).label}. Round ${snapshot.round}.`);
    }
    replay.lastState = snapshot.state;
    renderRun();
    renderFrame(model);
    replay.stepping = false;
    scheduleReplay();
  }

  // ---- run rendering -------------------------------------------------------------------------
  function structureKey(snapshot) {
    const rounds = Object.values(snapshot.rounds).map((view) => [view.round, view.toolCalls.length, Boolean(view.worker), Boolean(view.review)]);
    return [snapshot.state, snapshot.round, snapshot.full, Boolean(snapshot.plan), rounds, snapshot.decisions.length, snapshot.events.length];
  }

  function renderRun({ force = false } = {}) {
    const run = state.run;
    if (!run) { runHost.replaceChildren(); return; }
    const model = currentModel();
    const snapshot = currentSnapshot(model);
    const key = JSON.stringify([
      runPresentationKey(run), structureKey(snapshot), state.history.loaded, Boolean(state.history.problem),
      Boolean(state.pollWarning), state.decisionPending, state.cancelConfirm, state.cancelPending, state.startVisible,
    ]);
    if (!force && key === state.runKey && runHost.firstChild) { renderFrame(model, snapshot); return; }
    state.runKey = key;
    // A re-render replaces the run DOM; keep focus on the equivalent control rather than dropping it.
    const active = globalThis.document?.activeElement;
    const focusKey = active && [refs.runTitle, refs.cancel, refs.confirmCancel].includes(active) ? active.dataset.focusKey : "";
    const focusId = !focusKey && active?.id && findById(refs.article, active.id) === active ? active.id : "";
    const focusDrawer = !focusKey && !focusId && active?.tagName === "SUMMARY" ? active.parent?.dataset?.disclosure || active.parentElement?.dataset?.disclosure || "" : "";
    const frame = ensureFrame(run, model);
    const inReplay = !snapshot.full;
    const status = workflowStatus(snapshot.state, labels);
    const article = el("article", `ps-multi-agent__run ps-multi-agent__run--${status.key}`);
    article.dataset.runId = run.id || "";
    article.dataset.state = status.key;
    article.dataset.replay = String(inReplay);
    article.setAttribute("aria-busy", String(isActiveWorkflow(run.state)));

    const head = el("header", "ps-multi-agent__run-head");
    const runTitle = el("h3", "ps-multi-agent__run-title", `${labels.runHeading} ${shortRunId(run.id)}`);
    runTitle.id = `${instanceId}-run-title`;
    runTitle.tabIndex = -1;
    refs.runTitle = runTitle;
    runTitle.dataset.focusKey = "run-title";
    refs.cancel = null;
    refs.confirmCancel = null;
    article.setAttribute("aria-labelledby", runTitle.id);
    const badges = el("div", "ps-multi-agent__run-badges");
    if (inReplay) append(badges, el("span", "ps-badge ps-multi-agent__badge ps-multi-agent__badge--replay", labels.replay));
    append(badges, statusBadge(snapshot.state, labels), el("span", "ps-multi-agent__round", `Round ${snapshot.round || 1} of ${MAX_WORKFLOW_ROUNDS}`));
    append(head, runTitle, badges);
    append(article, head);
    const meta = [
      run.template_id && `${run.template_id}${run.template_version ? ` ${run.template_version}` : ""}`,
      run.requested_by && `requested by ${run.requested_by}`,
      run.created_at && formatTimestamp(run.created_at),
      run.provider_mode && `${run.provider_mode} agents`,
    ].filter(Boolean);
    if (meta.length) append(article, el("p", "ps-multi-agent__run-meta", meta.join(" · ")));

    if (state.pollWarning) {
      const warning = el("p", "ps-multi-agent__poll-warning", labels.pollWarning);
      warning.setAttribute("role", "status");
      append(article, warning);
    }
    if (state.history.problem && !state.history.loaded) {
      const warning = el("div", "ps-multi-agent__history-warning");
      warning.setAttribute("role", "status");
      const retry = el("button", "ps-button ps-button--small ps-button--quiet", "Try again");
      retry.type = "button";
      retry.dataset.action = "reload-history";
      retry.addEventListener("click", () => fetchHistory({ force: true }));
      append(warning, el("p", "", labels.historyUnavailable), retry);
      append(article, warning);
    }
    if (run.state === "failed" && run.error && snapshot.full) {
      append(article, renderProblem({
        title: "The workflow failed",
        detail: run.error.message || "",
        code: run.error.code || "",
        status: 0,
        requestId: "",
        errors: run.error.stage ? [{ field: "", message: `Stage: ${humaniseValue(run.error.stage)}`, code: "" }] : [],
      }));
    }

    if (frame.replay) append(article, frame.replay.node);
    const key_ = el("p", "ps-multi-agent__lane-key", labels.laneKey);
    key_.setAttribute("aria-hidden", "true");
    append(article, frame.board.node, key_, frame.relay.node, frame.now.node);

    const main = el("div", "ps-multi-agent__main");
    const decisionForm = renderMain(main, model, snapshot);
    if (main.firstChild) append(article, main);
    append(article, renderDrawers(model, snapshot));

    const footer = el("footer", "ps-multi-agent__run-actions");
    if (canCancel(run)) append(footer, cancelControls());
    if (isTerminalWorkflow(run.state) && !state.startVisible && state.descriptor) {
      const again = el("button", "ps-button", labels.startAgain);
      again.type = "button";
      again.dataset.action = "start-again";
      again.addEventListener("click", () => {
        state.startVisible = true;
        renderStartForm();
        renderRun({ force: true });
        const first = [...(startForm?.refs?.values() || [])][0];
        first?.control?.focus?.();
      });
      append(footer, again);
    }
    if (historyHref && run.id) {
      const link = el("a", "ps-multi-agent__history-link", labels.historyLink);
      link.href = historyHref(run.id);
      link.dataset.action = "history-link";
      append(footer, link);
    }
    append(article, footer);
    refs.article = article;
    runHost.replaceChildren(article);
    if (focusKey) [refs.runTitle, refs.cancel, refs.confirmCancel].find((node) => node?.dataset.focusKey === focusKey)?.focus?.();
    else if (focusId) findById(article, focusId)?.focus?.();
    else if (focusDrawer) findDisclosure(article, focusDrawer)?.children?.[0]?.focus?.();
    if (decisionForm && (Object.keys(state.decisionErrors).length || state.decisionProblem)) showDecisionErrors(decisionForm);
    renderFrame(model, snapshot);
  }

  /** The one thing that needs attention: the decision, a recorded decision in a replay, or the outcome. */
  function renderMain(host, model, snapshot) {
    const run = state.run;
    const roundView = snapshot.rounds[snapshot.round] || {};
    if (snapshot.state === "awaiting_human" && snapshot.full) {
      const options = availableDecisions(run, labels);
      if (!options.length) return null;
      const card = el("section", "ps-multi-agent__decide");
      let form = null;
      // An error clears as soon as the person fixes it; new errors wait for the next submit.
      const clearFixed = (draft) => {
        if (!form || !Object.keys(state.decisionErrors).length) return;
        const remaining = draft.decision ? validateDecision(draft, run).errors : { decision: labels.chooseFirst };
        for (const name of Object.keys(state.decisionErrors)) {
          if (remaining[name]) continue;
          delete state.decisionErrors[name];
          setFieldError(form.refs[name], "");
        }
      };
      form = buildDecisionForm({
        run, options, draft: state.decisionDraft, instanceId, labels, blocking: blockingFailures(run.review),
        guidance: state.descriptor?.template?.human_review_guidance || "", onChange: clearFixed,
      });
      card.setAttribute("aria-labelledby", form.heading.id);
      form.form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitDecision(form);
      });
      form.form.setAttribute("aria-busy", String(state.decisionPending));
      for (const control of form.controls) control.disabled = state.decisionPending;
      form.submit.setAttribute("aria-busy", String(state.decisionPending));
      if (state.decisionPending) form.submit.textContent = labels.submittingDecision;
      append(card, renderReviewerSide(run.review, Number(run.round) || 1, { labels, context }), form.form);
      append(host, card);
      return form;
    }
    if (snapshot.state === "awaiting_human") {
      const point = model.decisionPoints.find((item) => item.round === snapshot.round) || null;
      const card = el("section", "ps-multi-agent__decide ps-multi-agent__decide--recorded");
      card.setAttribute("aria-label", `Round ${snapshot.round} decision (replay)`);
      append(card, renderReviewerSide(roundView.review, snapshot.round, { labels, context, scope: `replay-${snapshot.round}` }),
        renderRecordedDecision(point, labels, () => replayCommand({ type: "continue" })));
      append(host, card);
      return null;
    }
    if (snapshot.terminal && snapshot.full) append(host, renderOutcome(run, labels));
    return null;
  }

  function counted(key, count) {
    const previous = state.drawerCounts.get(key);
    state.drawerCounts.set(key, count);
    const live = state.replay ? Boolean(state.replay.playing || state.replay.stepping) : state.animate;
    return live && previous !== undefined && previous !== count;
  }

  /** Closed by default; each summary says what is inside. */
  function renderDrawers(model, snapshot) {
    const host = el("div", "ps-multi-agent__drawers");
    const run = state.run;
    const view = snapshot.rounds[snapshot.round] || { toolCalls: [], worker: null, review: null };
    const plan = snapshot.plan;
    const planCount = plan ? `${plan.steps?.length || 0} read-only step${plan.steps?.length === 1 ? "" : "s"}` : "Not ready yet";
    const planDrawer = drawer(context, "drawer-plan", labels.plan, planCount, { fresh: counted("plan", planCount) });
    append(planDrawer.body, plan ? renderPlan(plan, context, { titled: false }) : el("p", "ps-multi-agent__empty", "The plan arrives with the hand-off to the Worker."));
    append(host, planDrawer.details);

    const evidence = view.worker?.evidence || [];
    const evidenceCount = view.worker
      ? `${evidence.length} record${evidence.length === 1 ? "" : "s"} · ${evidence.filter((record) => record.outcome === "succeeded").length} succeeded`
      : view.toolCalls.length ? `${view.toolCalls.length} tool call${view.toolCalls.length === 1 ? "" : "s"} so far` : "None yet";
    const evidenceDrawer = drawer(context, "drawer-evidence", labels.worker, evidenceCount, { fresh: counted("evidence", evidenceCount) });
    append(evidenceDrawer.body, renderWorker(run.plan, view.worker, context, "current", { titled: false, toolCalls: view.toolCalls }));
    append(host, evidenceDrawer.details);

    const groups = view.review ? groupFindings(view.review.findings) : null;
    const checksCount = groups ? `${groups.failed.length} failed · ${groups.passed.length} passed` : "Not reviewed yet";
    const checksDrawer = drawer(context, "drawer-checks", labels.review, checksCount, { fresh: counted("checks", checksCount) });
    append(checksDrawer.body, renderReview(view.review, context, "current", { titled: false, round: snapshot.round }));
    append(host, checksDrawer.details);

    for (const [roundNumber, previous] of Object.entries(snapshot.rounds)) {
      if (Number(roundNumber) >= snapshot.round || !previous.review) continue;
      append(host, renderSuperseded({ round: Number(roundNumber), worker_output: previous.worker, review: previous.review }, run.plan, context));
    }

    if (snapshot.decisions.length) {
      const count = `${snapshot.decisions.length} recorded`;
      const decisions = drawer(context, "drawer-decisions", labels.decisions, count, { fresh: counted("decisions", count) });
      append(decisions.body, renderDecisionLog(snapshot.decisions, context, { titled: false }));
      append(host, decisions.details);
    }

    const history = state.history;
    const logCount = history.loaded ? `${snapshot.events.length} event${snapshot.events.length === 1 ? "" : "s"}` : history.problem ? "Unavailable" : "Loading…";
    const log = drawer(context, "history", labels.history, logCount, { className: "ps-multi-agent__history" });
    const body = el("div", "ps-multi-agent__history-content");
    body.setAttribute("aria-busy", String(!history.loaded && !history.problem));
    if (history.loaded) {
      const until = model.origin + snapshot.t;
      const visible = (entry) => snapshot.full || Date.parse(entry.at || "") <= until;
      append(body, renderHistory(historyView({ history: history.data.history.filter(visible), audit: history.data.audit.filter(visible) }), labels, { origin: model.origin }));
    } else if (history.problem) append(body, renderProblem(history.problem, { heading: "History could not be loaded" }));
    else append(body, el("p", "ps-multi-agent__loading", "Loading history…"));
    append(log.body, body);
    append(host, log.details);
    return host;
  }

  function cancelControls() {
    const host = el("div", "ps-multi-agent__cancel");
    if (state.cancelProblem) append(host, renderProblem(state.cancelProblem, { heading: "The run was not cancelled" }));
    if (!state.cancelConfirm) {
      const cancel = el("button", "ps-button ps-button--quiet", labels.cancel);
      cancel.type = "button";
      cancel.dataset.action = "cancel";
      cancel.addEventListener("click", () => {
        state.cancelConfirm = true;
        renderRun({ force: true });
        refs.confirmCancel?.focus?.();
      });
      refs.cancel = cancel;
      cancel.dataset.focusKey = "cancel";
      append(host, cancel);
      return host;
    }
    const prompt = el("p", "ps-multi-agent__cancel-prompt", "Cancel this run? Recorded evidence is kept, but no decision can be recorded afterwards.");
    const confirm = el("button", "ps-button ps-button--danger", state.cancelPending ? labels.cancelling : "Yes, cancel the run");
    confirm.type = "button";
    confirm.dataset.action = "confirm-cancel";
    confirm.disabled = state.cancelPending;
    confirm.setAttribute("aria-busy", String(state.cancelPending));
    confirm.addEventListener("click", () => cancelRun());
    refs.confirmCancel = confirm;
    confirm.dataset.focusKey = "confirm-cancel";
    const keep = el("button", "ps-button ps-button--quiet", "Keep the run");
    keep.type = "button";
    keep.dataset.action = "keep-run";
    keep.disabled = state.cancelPending;
    keep.addEventListener("click", () => {
      state.cancelConfirm = false;
      state.cancelProblem = null;
      renderRun({ force: true });
      refs.cancel?.focus?.();
    });
    append(host, prompt, confirm, keep);
    return host;
  }

  // Open runs redraw once a second so running stages and waits keep growing on the axis.
  const frameTimer = setInterval(() => {
    if (state.destroyed || globalThis.document?.hidden || !state.run || isTerminalWorkflow(state.run.state)) return;
    const model = currentModel();
    if (!replaying(model)) renderFrame(model);
  }, 1000);

  const onVisibility = () => {
    if (state.destroyed || globalThis.document?.hidden || !isActiveWorkflow(state.run?.state)) return;
    pollRun();
  };
  globalThis.document?.addEventListener?.("visibilitychange", onVisibility);

  renderTemplateStatus();
  loadTemplate();
  if (runId) openRun(runId);

  return Object.freeze({
    /** Start a run. With no argument the form values are validated and submitted. */
    start(input = undefined) { return submitStart(input); },
    open(id) { return openRun(id); },
    refresh() {
      if (!state.descriptor) loadTemplate();
      if (state.run?.id) return pollRun();
      return Promise.resolve();
    },
    focus() { (state.run ? refs.runTitle : heading)?.focus?.(); },
    destroy() {
      if (state.destroyed) return;
      state.destroyed = true;
      clearTimeout(state.pollTimer);
      clearInterval(frameTimer);
      stopReplay();
      globalThis.document?.removeEventListener?.("visibilitychange", onVisibility);
      runTask.cancel();
      templateTask.cancel();
      historyTask.cancel();
      client.destroy?.();
    },
    get run() { return state.run; },
    get template() { return state.descriptor; },
  });
}
