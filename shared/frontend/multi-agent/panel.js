/** Feature-agnostic Planner → Worker → Reviewer → human panel over a feature backend proxy. */
import { append, createLatestTask, el } from "../browser/index.js";
import {
  MAX_WORKFLOW_ROUNDS, humaniseValue, isActiveWorkflow, isTerminalWorkflow, mergeLabels, shortRunId,
  workflowStatus,
} from "./definitions.js";
import {
  createRenderContext, renderDecisionLog, renderHistory, renderPlan, renderProblem, renderReview,
  renderSuperseded, renderTimeline, renderWorker, statusBadge,
} from "./components.js";
import { buildDecisionForm, buildStartForm, setFieldError } from "./forms.js";
import { nextWorkflowPollDelay } from "./polling.js";
import {
  availableDecisions, canCancel, fieldProblems, formatTimestamp, historyView, problemView,
  runPresentationKey, stageTimeline, startFields, validateDecision, validateStartInput,
} from "./projections.js";

let panelInstance = 0;

function isAbort(error) { return error?.name === "AbortError"; }

function emptyDraft(actor = "") {
  return { decision: "", note: "", actor: String(actor || ""), acceptedStepIds: [] };
}

function elapsedText(start) {
  const seconds = Math.max(0, Math.floor((Date.now() - Date.parse(start)) / 1000));
  if (!Number.isFinite(seconds)) return "";
  if (seconds < 60) return `${seconds} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ${seconds % 60} s`;
  return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
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
    history: { runId: null, state: null, view: null, loading: false, problem: null },
    elapsed: [],
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
  const refs = { runTitle: null, cancel: null, confirmCancel: null, history: null };

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
      publishStatus(`Review started. ${workflowStatus(body?.state, labels).label}.`);
      focusRunHeading();
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
    state.decisionDraft = emptyDraft(state.decisionDraft.actor || actor);
    state.decisionErrors = {};
    state.decisionProblem = null;
    state.cancelConfirm = false;
    state.cancelProblem = null;
    state.pollFailures = 0;
    state.pollWarning = null;
    state.history = { runId: null, state: null, view: null, loading: false, problem: null };
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
      if (recovered) renderRun({ force: true });
      setRun(body);
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
      setRun(body, { announceChange: false });
      publishStatus(`Opened review run ${shortRunId(body?.id)}. ${workflowStatus(body?.state, labels).label}.`);
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

  // ---- decisions and cancellation ------------------------------------------------------------
  async function submitDecision(form) {
    const run = state.run;
    if (state.destroyed || state.decisionPending || !run) return;
    form.sync();
    const result = validateDecision(state.decisionDraft, run);
    state.decisionErrors = result.errors;
    state.decisionProblem = null;
    if (!result.valid) {
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
      const recorded = labels.decisionOptions?.[result.body.decision]?.label || humaniseValue(result.body.decision);
      state.decisionDraft = emptyDraft(result.body.actor);
      state.decisionErrors = {};
      setRun(body, { announceChange: false });
      renderRun({ force: true });
      publishStatus(`Decision recorded: ${recorded}. ${workflowStatus(body?.state, labels).label}.`);
      focusRunHeading();
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
    } catch (error) {
      if (state.destroyed || isAbort(error)) return;
      state.cancelPending = false;
      state.cancelProblem = problemView(error);
      renderRun({ force: true });
      publishStatus(`Cancellation failed. ${state.cancelProblem.title}`);
      if (state.cancelProblem.status === 409) pollRun();
    }
  }

  // ---- history -------------------------------------------------------------------------------
  async function loadHistory() {
    const run = state.run;
    if (!run || state.destroyed) return;
    const fresh = state.history.runId === run.id && state.history.state === run.state && state.history.view;
    if (fresh || state.history.loading) { renderHistoryContent(); return; }
    const task = historyTask.start();
    state.history = { runId: run.id, state: run.state, view: null, loading: true, problem: null };
    renderHistoryContent();
    try {
      const { body } = await client.getHistory(run.id, { signal: task.signal });
      if (!task.isCurrent() || state.destroyed) return;
      state.history = { ...state.history, view: historyView(body), loading: false };
    } catch (error) {
      if (!task.isCurrent() || state.destroyed || isAbort(error)) return;
      state.history = { ...state.history, loading: false, problem: problemView(error) };
    }
    renderHistoryContent();
  }

  // Always render into the latest disclosure; a poll may have replaced the one that asked.
  function renderHistoryContent() {
    const body = refs.history;
    if (!body) return;
    body.replaceChildren();
    body.setAttribute("aria-busy", String(state.history.loading));
    if (state.history.loading) append(body, el("p", "ps-multi-agent__loading", "Loading history…"));
    else if (state.history.problem) append(body, renderProblem(state.history.problem, { heading: "History could not be loaded" }));
    else if (state.history.view) append(body, renderHistory(state.history.view, labels));
  }

  function historyDisclosure(run) {
    const details = el("details", "ps-multi-agent__history");
    details.dataset.disclosure = "history";
    details.open = Boolean(context.disclosures.get("history"));
    append(details, el("summary", "", labels.history));
    const body = el("div", "ps-multi-agent__history-content");
    refs.history = body;
    append(details, body);
    details.addEventListener("toggle", () => {
      context.disclosures.set("history", details.open);
      if (details.open) loadHistory();
    });
    if (details.open) {
      if (state.history.runId === run.id && state.history.state !== run.state) state.history.view = null;
      loadHistory();
    }
    return details;
  }

  // ---- run rendering -------------------------------------------------------------------------
  function renderRun({ force = false } = {}) {
    const run = state.run;
    if (!run) { runHost.replaceChildren(); return; }
    const key = runPresentationKey(run);
    if (!force && key === state.runKey && runHost.firstChild) return;
    state.runKey = key;
    state.elapsed = [];
    // A poll replaces the run DOM; keep focus on the equivalent control rather than dropping it.
    const active = globalThis.document?.activeElement;
    const focusKey = active && [refs.runTitle, refs.cancel, refs.confirmCancel].includes(active) ? active.dataset.focusKey : "";
    const status = workflowStatus(run.state, labels);
    const article = el("article", `ps-multi-agent__run ps-multi-agent__run--${status.key}`);
    article.dataset.runId = run.id || "";
    article.dataset.state = status.key;
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
    append(badges, statusBadge(run.state, labels), el("span", "ps-multi-agent__round", `Round ${run.round || 1} of ${MAX_WORKFLOW_ROUNDS}`));
    append(head, runTitle, badges);
    append(article, head, el("p", "ps-multi-agent__status-detail", status.detail));
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
    if (run.state === "failed" && run.error) {
      append(article, renderProblem({
        title: "The workflow failed",
        detail: run.error.message || "",
        code: run.error.code || "",
        status: 0,
        requestId: "",
        errors: run.error.stage ? [{ field: "", message: `Stage: ${humaniseValue(run.error.stage)}`, code: "" }] : [],
      }));
    }

    append(article, renderTimeline(stageTimeline(run, labels), { elapsed: state.elapsed }));
    append(article, renderPlan(run.plan, context));
    if (run.worker_output || isActiveWorkflow(run.state)) append(article, renderWorker(run.plan, run.worker_output, context));
    if (run.review || ["working", "reviewing"].includes(run.state)) append(article, renderReview(run.review, context));
    for (const attempt of run.superseded || []) append(article, renderSuperseded(attempt, run.plan, context));
    append(article, renderDecisionLog(run.decisions, context));

    const options = availableDecisions(run, labels);
    let decisionForm = null;
    if (options.length) {
      decisionForm = buildDecisionForm({
        run, options, draft: state.decisionDraft, instanceId, labels,
        guidance: state.descriptor?.template?.human_review_guidance || "",
      });
      decisionForm.form.addEventListener("submit", (event) => {
        event.preventDefault();
        submitDecision(decisionForm);
      });
      decisionForm.form.setAttribute("aria-busy", String(state.decisionPending));
      for (const control of decisionForm.controls) control.disabled = state.decisionPending;
      decisionForm.submit.setAttribute("aria-busy", String(state.decisionPending));
      if (state.decisionPending) decisionForm.submit.textContent = labels.submittingDecision;
      append(article, decisionForm.form);
    }

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
    append(article, footer, historyDisclosure(run));
    runHost.replaceChildren(article);
    if (focusKey) [refs.runTitle, refs.cancel, refs.confirmCancel].find((node) => node?.dataset.focusKey === focusKey)?.focus?.();
    if (decisionForm && (Object.keys(state.decisionErrors).length || state.decisionProblem)) showDecisionErrors(decisionForm);
    updateElapsed();
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

  function updateElapsed() {
    for (const node of state.elapsed) {
      const text = elapsedText(node.dataset.elapsedStart);
      if (text) node.textContent = text;
    }
  }

  const elapsedTimer = setInterval(() => {
    if (!state.destroyed && !globalThis.document?.hidden && state.elapsed.length) updateElapsed();
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
      clearInterval(elapsedTimer);
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
