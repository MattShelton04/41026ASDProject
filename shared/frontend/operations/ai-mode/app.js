import {
  ACTIVE_STATUSES,
  GenerationGuard,
  MAX_HISTORY_PAGES,
  TERMINAL_STATUSES,
  filterForStatuses,
  mergeEventPage,
  nextDetailDelay,
  nextListDelay,
  requestJson,
  restoreCursor,
  shouldRefreshDetail,
  statusesForFilter,
} from "/operations/ai-mode/assets/polling.js";

const API_ROOT = "/api/v1";
const EVENT_LIMIT = 200;
const REQUEST_TIMEOUT_MS = 8000;
const MOBILE_QUERY = "(max-width: 720px)";
function researchAreaLabel(value) {
  const option = [...document.querySelectorAll("#feature-filter option")].find((item) => (
    item.value === value || String(item.dataset.aliases || "").split(" ").includes(value)
  ));
  return option?.textContent || String(value || "Unknown area").replaceAll("_", " ").replaceAll("-", " ");
}

const ui = Object.fromEntries([
  "announcement", "connection-dot", "connection-state", "workspace", "page-summary",
  "quick-filters", "filters", "feature-filter", "status-filter", "model-filter",
  "clear-filters", "count-active", "count-review", "count-failed", "count-complete",
  "run-list", "refresh-runs", "load-more", "run-detail", "empty-detail", "detail-content",
  "back-to-runs", "run-status", "stale-state", "run-objective", "run-objective-full",
  "objective-details", "run-subtitle", "copy-link",
  "current-work", "current-work-symbol", "current-work-phase", "current-work-title",
  "current-work-detail", "live-elapsed", "outcome-summary", "outcome-eyebrow", "outcome-title",
  "outcome-badge", "outcome-content", "cycle-history", "cycle-summary", "run-overview",
  "workload-metrics",
  "correlation-identifiers", "last-updated", "run-metadata", "execution", "event-cursor",
  "event-list", "raw-projection",
].map((id) => [id, document.getElementById(id)]));

const state = {
  runs: [],
  nextCursor: null,
  selectedId: null,
  detail: null,
  etag: null,
  eventCursor: 0,
  restoredCursor: 0,
  eventItems: [],
  quickFilter: "all",
  detailGuard: new GenerationGuard(),
  listGuard: new GenerationGuard(),
  detailTimer: null,
  listTimer: null,
  elapsedTimer: null,
  detailController: null,
  listController: null,
  detailInFlight: false,
  detailRefreshPending: false,
  detailForcePending: false,
  listInFlight: false,
  listRefreshPending: false,
  detailFailures: 0,
  listFailures: 0,
};

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

function label(value) { return String(value ?? "—").replaceAll("_", " "); }
function pretty(value) { return JSON.stringify(value, null, 2); }
function localTime(value) { return value ? new Date(value).toLocaleString() : "—"; }
function shortTime(value) {
  return value ? new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
}

function workloadTitle(objective) {
  const normalized = String(objective || "").replace(/\s+/g, " ").trim();
  if (!normalized) return "Objective hidden by policy";
  const firstSentence = normalized.match(/^.*?[.!?](?:\s|$)/)?.[0]?.trim() || normalized;
  return firstSentence.length <= 150 ? firstSentence : `${firstSentence.slice(0, 149).trimEnd()}…`;
}

function duration(value) {
  if (value === null || value === undefined) return "—";
  if (value < 1000) return `${value} ms`;
  const seconds = value / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.floor(seconds % 60);
  return `${minutes}m ${String(remainder).padStart(2, "0")}s`;
}

function compactNumber(value) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function elapsedSince(value, now = Date.now()) {
  if (!value) return 0;
  return Math.max(0, now - new Date(value).getTime());
}

function statusPresentation(status) {
  const presentations = {
    queued: ["○", "Queued"],
    planning: ["●", "Preparing"],
    ready: ["●", "Ready"],
    acting: ["●", "Checking sources"],
    observing: ["●", "Recording results"],
    adapting: ["●", "Deciding next step"],
    review_required: ["‖", "Needs review"],
    succeeded: ["✓", "Completed"],
    failed: ["!", "Failed"],
    cancelled: ["×", "Cancelled"],
    pending: ["○", "Pending"],
    running: ["●", "Running"],
  };
  return presentations[status] || ["·", label(status)];
}

function statusMark(status, className = "status-mark") {
  const [symbol, text] = statusPresentation(status);
  const mark = node("span", `${className} status-${status}`);
  mark.append(node("span", "status-symbol", symbol), document.createTextNode(text));
  return mark;
}

function setConnection(kind, message) {
  ui["connection-dot"].className = `connection-dot ${kind}`;
  ui["connection-state"].textContent = message;
  ui["stale-state"].hidden = kind !== "disconnected";
}

function selectedStatuses() {
  if (ui["status-filter"].value) return [ui["status-filter"].value];
  return statusesForFilter(state.quickFilter);
}

function filterQuery(cursor = null) {
  const params = new URLSearchParams({ limit: "50" });
  if (ui["feature-filter"].value.trim()) params.set("feature_key", ui["feature-filter"].value.trim());
  for (const status of selectedStatuses()) params.append("status", status);
  if (ui["model-filter"].value.trim()) params.set("model_profile", ui["model-filter"].value.trim());
  if (cursor) params.set("cursor", cursor);
  return params;
}

function updateQuickFilters() {
  for (const button of ui["quick-filters"].querySelectorAll("button[data-filter]")) {
    button.setAttribute("aria-pressed", String(button.dataset.filter === state.quickFilter && !ui["status-filter"].value));
  }
}

function syncFilterUrl() {
  const url = new URL(window.location.href);
  for (const key of ["feature_key", "status", "model_profile", "view"]) url.searchParams.delete(key);
  if (state.quickFilter !== "all" && !ui["status-filter"].value) url.searchParams.set("view", state.quickFilter);
  const filters = filterQuery();
  filters.delete("limit");
  for (const [key, value] of filters) {
    if (key !== "status" || ui["status-filter"].value) url.searchParams.append(key, value);
  }
  history.replaceState(null, "", url);
}

function scheduleList(delay = nextListDelay(state.runs, state.listFailures, document.hidden)) {
  clearTimeout(state.listTimer);
  state.listTimer = setTimeout(() => loadRuns(), delay);
}

async function loadRuns({ append = false } = {}) {
  if (state.listInFlight) {
    if (!append) state.listRefreshPending = true;
    return;
  }
  state.listInFlight = true;
  state.listRefreshPending = false;
  const generation = state.listGuard.current;
  const cursor = append ? state.nextCursor : null;
  const controller = new AbortController();
  state.listController = controller;
  try {
    const { body } = await requestJson(fetch, `${API_ROOT}/agent-runs?${filterQuery(cursor)}`, {
      signal: controller.signal,
      timeoutMs: REQUEST_TIMEOUT_MS,
    });
    if (!state.listGuard.isCurrent(generation)) return;
    const byId = new Map((append ? state.runs : []).map((run) => [run.id, run]));
    for (const run of body.items) byId.set(run.id, run);
    state.runs = [...byId.values()];
    state.nextCursor = body.next_cursor;
    state.listFailures = 0;
    renderRunList({ removeStale: !append });
    if (!state.selectedId) setConnection("connected", "Persisted state connected");
  } catch (error) {
    if (error.name === "AbortError" || !state.listGuard.isCurrent(generation)) return;
    state.listFailures += 1;
    setConnection("disconnected", `Review history unavailable · ${error.message}`);
    if (!state.runs.length) ui["run-list"].replaceChildren(node("li", "empty", error.message));
  } finally {
    if (state.listController === controller) state.listController = null;
    state.listInFlight = false;
    if (state.listRefreshPending) {
      state.listRefreshPending = false;
      scheduleList(0);
    } else {
      scheduleList();
    }
  }
}

function invalidateRunIndex() {
  state.listGuard.advance();
  state.listController?.abort();
  state.listRefreshPending = true;
  scheduleList(0);
}

function createRunItem(runId) {
  const item = node("li", "run-item");
  item.dataset.runId = runId;
  const button = node("button");
  button.type = "button";
  button.dataset.runId = runId;
  const top = node("div", "run-item-top");
  top.append(node("span", "run-item-status"), node("span", "run-item-time muted"));
  button.append(top, node("p", "run-objective"), node("div", "run-facts"));
  button.addEventListener("click", () => selectRun(runId));
  item.append(button);
  return item;
}

function updateRunItem(item, run) {
  const button = item.querySelector("button");
  button.setAttribute("aria-current", String(run.id === state.selectedId));
  const statusTarget = item.querySelector(".run-item-status");
  statusTarget.replaceChildren(statusMark(run.status));
  const timeTarget = item.querySelector(".run-item-time");
  timeTarget.dataset.runLive = run.id;
  timeTarget.textContent = duration(run.duration_ms);
  item.querySelector(".run-objective").textContent = run.objective_preview || "Objective hidden by policy";
  const facts = item.querySelector(".run-facts");
  facts.replaceChildren(
    node("span", "feature-key", researchAreaLabel(run.feature_key)),
    node("span", "model-profile", run.model_profile),
    node("span", "", `${run.iteration_count} iter · ${run.tool_call_count} tool${run.tool_call_count === 1 ? "" : "s"}`),
  );
  item.className = `run-item run-${run.status}`;
}

function renderRunList({ removeStale = true } = {}) {
  const focusedRunId = document.activeElement?.dataset?.runId;
  const existing = new Map(
    [...ui["run-list"].querySelectorAll(":scope > .run-item")].map((item) => [item.dataset.runId, item]),
  );
  ui["run-list"].querySelector(":scope > .empty")?.remove();
  const renderedIds = new Set();
  for (const run of state.runs) {
    const item = existing.get(run.id) || createRunItem(run.id);
    updateRunItem(item, run);
    ui["run-list"].append(item);
    renderedIds.add(run.id);
  }
  if (removeStale) {
    for (const [runId, item] of existing) if (!renderedIds.has(runId)) item.remove();
  }
  if (!state.runs.length) ui["run-list"].append(node("li", "empty", "No runs match these filters."));
  ui["load-more"].hidden = !state.nextCursor;
  const counts = {
    active: state.runs.filter((run) => ACTIVE_STATUSES.has(run.status)).length,
    review: state.runs.filter((run) => run.status === "review_required").length,
    failed: state.runs.filter((run) => run.status === "failed").length,
    complete: state.runs.filter((run) => run.status === "succeeded").length,
  };
  ui["count-active"].textContent = counts.active;
  ui["count-review"].textContent = counts.review;
  ui["count-failed"].textContent = counts.failed;
  ui["count-complete"].textContent = counts.complete;
  ui["page-summary"].textContent = `${state.runs.length} loaded · ${counts.active ? "refreshing every 2 s" : "idle refresh every 10 s"}`;
  if (focusedRunId) ui["run-list"].querySelector(`[data-run-id="${focusedRunId}"]`)?.focus();
  updateLiveElapsed();
}

async function selectRun(runId) {
  const generation = state.detailGuard.advance();
  state.detailController?.abort();
  state.selectedId = runId;
  state.detail = null;
  state.etag = null;
  state.eventItems = [];
  state.eventCursor = 0;
  state.restoredCursor = restoreCursor(sessionStorage.getItem(`ai-mode-operations:${runId}:cursor`));
  state.detailFailures = 0;
  state.detailRefreshPending = false;
  clearTimeout(state.detailTimer);
  const url = new URL(window.location.href);
  url.searchParams.set("run", runId);
  history.replaceState(null, "", url);
  ui.workspace.classList.add("show-detail");
  renderRunList();
  ui["empty-detail"].hidden = true;
  ui["detail-content"].hidden = false;
  ui["run-objective"].textContent = "Loading recorded activity…";
  ui["run-objective-full"].textContent = "";
  ui["run-subtitle"].textContent = runId;
  ui["current-work-title"].textContent = "Loading current work…";
  ui["event-list"].replaceChildren(node("li", "empty", "Loading event history…"));
  await refreshSelected(generation, { forceDetail: true, hydrate: true });
}

async function fetchEventPage(after, controller) {
  return requestJson(
    fetch,
    `${API_ROOT}/agent-runs/${state.selectedId}/events?after=${after}&limit=${EVENT_LIMIT}`,
    { signal: controller.signal, timeoutMs: REQUEST_TIMEOUT_MS },
  );
}

function acceptEvents(items) {
  const merged = mergeEventPage(state.eventItems, items);
  state.eventItems = merged.items;
  state.eventCursor = Math.max(state.eventCursor, merged.cursor);
  if (state.selectedId) {
    sessionStorage.setItem(`ai-mode-operations:${state.selectedId}:cursor`, String(state.eventCursor));
  }
  renderEvents();
}

async function hydrateEventHistory(controller, generation) {
  let after = 0;
  let eventCount = 0;
  let terminal = false;
  for (let pageNumber = 0; pageNumber < MAX_HISTORY_PAGES; pageNumber += 1) {
    const { body } = await fetchEventPage(after, controller);
    if (!state.detailGuard.isCurrent(generation)) return { eventCount: 0, terminal: false };
    acceptEvents(body.items);
    eventCount += body.items.length;
    terminal = body.terminal;
    const advanced = body.next_cursor > after;
    after = body.next_cursor;
    if (!advanced || body.items.length < EVENT_LIMIT || terminal || after >= state.restoredCursor) break;
  }
  state.eventCursor = Math.max(state.eventCursor, state.restoredCursor);
  sessionStorage.setItem(`ai-mode-operations:${state.selectedId}:cursor`, String(state.eventCursor));
  renderEvents();
  return { eventCount, terminal };
}

function scheduleDetail(generation, delay) {
  clearTimeout(state.detailTimer);
  if (delay === null) return;
  state.detailTimer = setTimeout(() => refreshSelected(generation), delay);
}

async function refreshSelected(generation, { forceDetail = false, hydrate = false } = {}) {
  if (!state.selectedId || !state.detailGuard.isCurrent(generation)) return;
  if (state.detailInFlight) {
    state.detailRefreshPending = true;
    state.detailForcePending ||= forceDetail;
    return;
  }
  state.detailInFlight = true;
  const controller = new AbortController();
  state.detailController = controller;
  try {
    let eventCount;
    let terminal;
    if (hydrate) {
      ({ eventCount, terminal } = await hydrateEventHistory(controller, generation));
    } else {
      const { body } = await fetchEventPage(state.eventCursor, controller);
      if (!state.detailGuard.isCurrent(generation)) return;
      acceptEvents(body.items);
      eventCount = body.items.length;
      terminal = body.terminal;
    }
    if (shouldRefreshDetail({ force: forceDetail, eventCount, hasDetail: Boolean(state.detail) })) {
      await loadDetail(generation, controller);
    }
    if (!state.detailGuard.isCurrent(generation)) return;
    if (state.detail && (terminal || TERMINAL_STATUSES.has(state.detail.run.status))) {
      state.detailFailures = 0;
      setConnection("connected", `Review ${statusPresentation(state.detail.run.status)[1].toLowerCase()} · up to date`);
      scheduleDetail(generation, null);
      return;
    }
    state.detailFailures = 0;
    setConnection("connected", "Activity is up to date");
  } catch (error) {
    if (error.name === "AbortError" || !state.detailGuard.isCurrent(generation)) return;
    state.detailFailures += 1;
    setConnection("disconnected", `Disconnected · ${error.message}`);
  } finally {
    if (state.detailController === controller) state.detailController = null;
    state.detailInFlight = false;
  }
  if (!state.detailGuard.isCurrent(generation)) return;
  if (state.detailRefreshPending) {
    const pendingForce = state.detailForcePending;
    state.detailRefreshPending = false;
    state.detailForcePending = false;
    clearTimeout(state.detailTimer);
    state.detailTimer = setTimeout(
      () => refreshSelected(generation, { forceDetail: pendingForce }),
      0,
    );
    return;
  }
  scheduleDetail(
    generation,
    nextDetailDelay(state.detail?.run.status, state.detailFailures, document.hidden),
  );
}

async function loadDetail(generation, controller) {
  const headers = {};
  if (state.etag) headers["If-None-Match"] = state.etag;
  const { response, body } = await requestJson(
    fetch,
    `${API_ROOT}/operations/agent-runs/${state.selectedId}`,
    { headers, signal: controller.signal, timeoutMs: REQUEST_TIMEOUT_MS },
  );
  if (!state.detailGuard.isCurrent(generation) || response.status === 304) return;
  const previousStatus = state.detail?.run.status || state.runs.find((run) => run.id === state.selectedId)?.status;
  state.etag = response.headers.get("ETag");
  state.detail = body;
  const runIndex = state.runs.findIndex((run) => run.id === body.run.id);
  if (runIndex >= 0) state.runs[runIndex] = body.run;
  else state.runs.unshift(body.run);
  renderRunList();
  renderDetail();
  if (previousStatus && previousStatus !== body.run.status) {
    state.listRefreshPending = true;
    scheduleList(0);
  }
}

function addDefinition(target, entries) {
  for (const [key, value, className = ""] of entries) {
    const wrapper = node("div", className);
    wrapper.append(node("dt", "", key), node("dd", "", String(value ?? "—")));
    target.append(wrapper);
  }
}

function currentStep(steps) {
  return [...steps].reverse().find((step) => ["running", "pending"].includes(step.status)) || steps.at(-1) || null;
}

function waitingCopy(run, step) {
  if (run.status === "queued") return ["Waiting to start.", "No work has been recorded yet."];
  if (run.status === "review_required") return ["Waiting for authorized review.", "No operation will resume without a valid review decision."];
  if (TERMINAL_STATUSES.has(run.status)) {
    const outcome = run.status === "succeeded" ? "Review completed successfully." : run.status === "failed" ? "Review stopped after a recorded failure." : "Review was cancelled.";
    return [outcome, `Recorded workflow version ${run.version}.`];
  }
  const copy = {
    plan: ["Preparing the review plan.", "Waiting for the next recorded step."],
    act: ["Checking a source.", "Waiting for the source response."],
    observe: ["Recording source results.", "Review details are being saved."],
    adapt: ["Deciding the next step.", "The review is using the recorded source results."],
  };
  return copy[step?.phase] || ["Preparing the next action.", "The review is active."];
}

function renderCurrentWork(run, steps) {
  const step = currentStep(steps);
  const [title, detail] = waitingCopy(run, step);
  const phase = step?.phase || run.latest_phase || run.status;
  const [symbol] = statusPresentation(run.status);
  ui["current-work-symbol"].textContent = symbol;
  ui["current-work-phase"].textContent = label(phase);
  ui["current-work-title"].textContent = title;
  ui["current-work-detail"].replaceChildren(document.createTextNode(detail));
  if (step?.started_at && ["running", "pending"].includes(step.status)) {
    const elapsed = node("span", "step-live-elapsed");
    elapsed.dataset.stepStarted = step.started_at;
    ui["current-work-detail"].append(document.createTextNode(" · "), elapsed);
  }
  ui["current-work"].className = `current-work current-${run.status}`;
}

function groupCycles(steps) {
  const groups = [];
  let planNumber = 0;
  let iterationNumber = 0;
  let currentIteration = null;
  for (const step of steps) {
    if (step.phase === "plan") {
      planNumber += 1;
      currentIteration = null;
      groups.push({ kind: "plan", number: planNumber, steps: [step] });
    } else if (step.phase === "act") {
      iterationNumber += 1;
      currentIteration = { kind: "iteration", number: iterationNumber, steps: [step] };
      groups.push(currentIteration);
    } else if (currentIteration) {
      currentIteration.steps.push(step);
    } else {
      groups.push({ kind: "phase", number: groups.length + 1, steps: [step] });
    }
  }
  return { groups, planNumber, iterationNumber };
}

function renderCycles(steps) {
  ui["cycle-history"].replaceChildren();
  const { groups, planNumber, iterationNumber } = groupCycles(steps);
  if (!groups.length) ui["cycle-history"].append(node("li", "cycle-empty", "No recorded step yet"));
  for (const group of groups) {
    const item = node("li", `cycle-group cycle-${group.kind}`);
    item.append(node("span", "cycle-label", group.kind === "plan" ? `Plan ${group.number}` : group.kind === "iteration" ? `Iteration ${group.number}` : "Phase"));
    const phases = node("span", "cycle-phases");
    for (const step of group.steps) {
      const [symbol] = statusPresentation(step.status);
      const phase = node("span", `cycle-phase status-${step.status}`, `${symbol} ${label(step.phase)}`);
      if (["running", "pending"].includes(step.status)) phase.setAttribute("aria-current", "step");
      phases.append(phase);
    }
    item.append(phases);
    ui["cycle-history"].append(item);
  }
  const replans = Math.max(0, planNumber - 1);
  ui["cycle-summary"].textContent = `${planNumber} plan${planNumber === 1 ? "" : "s"} · ${iterationNumber} iteration${iterationNumber === 1 ? "" : "s"}${replans ? ` · ${replans} replan${replans === 1 ? "" : "s"}` : ""}`;
}

function outcomeLabel(run, finalResult, error) {
  if (run.status === "succeeded") return finalResult ? "Result available" : "Succeeded";
  if (run.status === "failed") return label(error?.code || run.error_code || "failed");
  if (run.status === "cancelled") return "Cancelled";
  if (run.status === "review_required") return "Review needed";
  return "In progress";
}

function copyButton(labelText, value) {
  const button = node("button", "copy-id quiet-button");
  button.type = "button";
  button.dataset.copyValue = value;
  button.setAttribute("aria-label", `Copy ${labelText}`);
  button.append(node("span", "copy-label", labelText), node("code", "", value), node("span", "copy-action", "Copy"));
  return button;
}

function renderCorrelation(correlation) {
  ui["correlation-identifiers"].replaceChildren(
    copyButton("Run", String(correlation.run_id)),
    copyButton("Request", correlation.request_id),
  );
  if (correlation.trace_id) ui["correlation-identifiers"].append(copyButton("Trace", correlation.trace_id));
  if (correlation.telemetry_url) {
    const link = node("a", "telemetry-link", "Open telemetry");
    link.href = correlation.telemetry_url;
    link.rel = "noreferrer";
    ui["correlation-identifiers"].append(link);
  }
}

function renderDetail() {
  const {
    run, objective, limits, cancel_requested: cancelRequested, final_result: finalResult,
    error, steps, reviews, correlation,
  } = state.detail;
  ui["run-status"].replaceChildren(...statusMark(run.status).childNodes);
  ui["run-status"].className = `status-mark status-${run.status}`;
  const fullObjective = objective || run.objective_preview || "Objective hidden by policy";
  ui["run-objective"].textContent = workloadTitle(fullObjective);
  ui["run-objective-full"].textContent = fullObjective;
  ui["objective-details"].hidden = workloadTitle(fullObjective) === fullObjective;
  ui["run-subtitle"].textContent = `${researchAreaLabel(run.feature_key)} · created ${localTime(run.created_at)}`;
  ui["last-updated"].textContent = `Updated ${localTime(run.updated_at)}`;
  renderCurrentWork(run, steps);
  renderOutcome(run, finalResult, error);
  renderCycles(steps);

  ui["run-overview"].replaceChildren();
  addDefinition(ui["run-overview"], [
    ["Current phase", label(currentStep(steps)?.phase || run.latest_phase || "not started")],
    ["Elapsed", duration(run.duration_ms), "overview-elapsed"],
    ["Research area", researchAreaLabel(run.feature_key)],
    ["Model", run.model_profile],
    ["Iterations", `${run.iteration_count} / ${limits.max_iterations}`],
    ["Tool calls", `${run.tool_call_count} / ${limits.max_tool_calls}`],
    ["Outcome", outcomeLabel(run, finalResult, error), `overview-outcome status-${run.status}`],
  ]);
  ui["run-overview"].querySelector(".overview-elapsed dd").dataset.overviewElapsed = "true";
  renderWorkloadTelemetry(steps);
  renderCorrelation(correlation);

  ui["run-metadata"].replaceChildren();
  addDefinition(ui["run-metadata"], [
    ["Prompt set", run.prompt_set], ["Review version", run.version],
    ["Time budget", duration(limits.time_budget_ms)], ["Model repairs", limits.max_model_repairs],
    ["Cancellation requested", cancelRequested ? "Yes" : "No"],
    ["Created", localTime(run.created_at)], ["Updated", localTime(run.updated_at)],
    ["Terminal duration", TERMINAL_STATUSES.has(run.status) ? duration(run.duration_ms) : "Still running"],
  ]);
  renderExecution(steps, reviews);
  ui["raw-projection"].textContent = pretty(state.detail);
  ui.announcement.textContent = `Review ${run.id} updated to ${label(run.status)}, version ${run.version}.`;
  updateLiveElapsed();
}

function renderValue(value) {
  if (value === null || value === undefined) return node("span", "muted", "None");
  if (Array.isArray(value)) {
    const list = node("ol", "data-array");
    for (const item of value) {
      const listItem = node("li");
      listItem.append(renderValue(item));
      list.append(listItem);
    }
    return list;
  }
  if (typeof value === "object") {
    const list = node("dl", "data-object");
    for (const [key, item] of Object.entries(value)) {
      const wrapper = node("div");
      wrapper.append(node("dt", "", label(key)), node("dd", ""));
      wrapper.querySelector("dd").append(renderValue(item));
      list.append(wrapper);
    }
    return list;
  }
  return node("span", typeof value === "string" ? "" : "mono", String(value));
}

function appendList(target, values, className = "plain-list") {
  const list = node("ul", className);
  for (const value of values) list.append(node("li", "", String(value)));
  target.append(list);
}

function renderOutcome(run, finalResult, error) {
  const terminal = TERMINAL_STATUSES.has(run.status);
  ui["outcome-summary"].hidden = !terminal;
  if (!terminal) return;

  ui["outcome-summary"].className = `outcome-summary outcome-${run.status}`;
  ui["outcome-badge"].replaceChildren(statusMark(run.status));
  ui["outcome-content"].replaceChildren();

  if (finalResult) {
    ui["outcome-eyebrow"].textContent = "AI review result";
    ui["outcome-title"].textContent = "Review summary";
    const summary = typeof finalResult.summary === "string" ? finalResult.summary : null;
    if (summary) ui["outcome-content"].append(node("p", "outcome-lede", summary));

    const grid = node("div", "outcome-grid");
    const findings = Array.isArray(finalResult.findings) ? finalResult.findings : [];
    if (findings.length) {
      const section = node("section", "outcome-findings");
      section.append(node("h4", "", "Key findings"));
      appendList(section, findings, "finding-list");
      grid.append(section);
    }
    for (const [key, title, className] of [
      ["recommended_next_step", "Recommended next step", "outcome-next"],
      ["safety_note", "What did not change", "outcome-safety"],
    ]) {
      if (typeof finalResult[key] !== "string") continue;
      const section = node("section", className);
      section.append(node("h4", "", title), node("p", "", finalResult[key]));
      grid.append(section);
    }
    if (grid.childNodes.length) ui["outcome-content"].append(grid);

    if (Array.isArray(finalResult.evidence) && finalResult.evidence.length) {
      const evidence = node("details", "outcome-evidence");
      evidence.append(node("summary", "", `${finalResult.evidence.length} cited evidence reference${finalResult.evidence.length === 1 ? "" : "s"}`));
      appendList(evidence, finalResult.evidence, "evidence-reference-list");
      ui["outcome-content"].append(evidence);
    }
    const knownKeys = new Set(["summary", "findings", "recommended_next_step", "safety_note", "evidence"]);
    if (Object.keys(finalResult).some((key) => !knownKeys.has(key)) || !summary) {
      const details = node("details", "outcome-evidence");
      details.append(node("summary", "", "Structured result"), renderValue(finalResult));
      ui["outcome-content"].append(details);
    }
    return;
  }

  const cancelled = run.status === "cancelled";
  ui["outcome-eyebrow"].textContent = cancelled ? "Review cancelled" : "Review stopped";
  ui["outcome-title"].textContent = cancelled ? "No final result was produced" : label(error?.code || run.error_code || "Review failed");
  ui["outcome-content"].append(node(
    "p",
    "outcome-lede",
    error?.message || (cancelled ? "The review was cancelled before completion." : "The review stopped without returning a final result."),
  ));
}

function workloadTelemetry(steps) {
  const modelInvocations = steps.map((step) => step.model_invocation).filter(Boolean);
  const toolSteps = steps.filter((step) => step.tool);
  const sum = (values) => values.reduce((total, value) => total + (Number(value) || 0), 0);
  return {
    modelCalls: modelInvocations.length,
    models: [...new Set(modelInvocations.map((item) => item.model))],
    promptTokens: sum(modelInvocations.map((item) => item.metrics.prompt_tokens)),
    outputTokens: sum(modelInvocations.map((item) => item.metrics.output_tokens)),
    modelDuration: sum(modelInvocations.map((item) => item.metrics.total_duration_ms)),
    repairs: sum(modelInvocations.map((item) => item.repair_count)),
    providerRetries: sum(modelInvocations.map((item) => item.provider_retry_count)),
    transportRetries: sum(modelInvocations.map((item) => item.metrics.retry_count)),
    toolFailures: toolSteps.filter((step) => step.tool.outcome === "failed").length,
    replans: Math.max(0, steps.filter((step) => step.phase === "plan").length - 1),
  };
}

function renderWorkloadTelemetry(steps) {
  const telemetry = workloadTelemetry(steps);
  const tokensKnown = telemetry.promptTokens > 0 || telemetry.outputTokens > 0;
  ui["workload-metrics"].replaceChildren();
  addDefinition(ui["workload-metrics"], [
    ["Model calls", telemetry.modelCalls],
    ["Models", telemetry.models.join(" · ") || "No model evidence"],
    ["Tokens", tokensKnown ? `${compactNumber(telemetry.promptTokens)} in · ${compactNumber(telemetry.outputTokens)} out` : "Not reported"],
    ["Model time", telemetry.modelCalls ? duration(telemetry.modelDuration) : "—"],
    ["Schema repairs", telemetry.repairs],
    ["Provider retries", telemetry.providerRetries + telemetry.transportRetries],
    ["Tool failures", telemetry.toolFailures],
    ["Replans", telemetry.replans],
  ]);
}

function metric(labelText, value) {
  const item = node("div");
  item.append(node("dt", "", labelText), node("dd", "", value));
  return item;
}

function evidenceSummary(step) {
  if (step.plan) return `${step.plan.actions.length} planned action${step.plan.actions.length === 1 ? "" : "s"}`;
  if (step.tool) return `${step.tool.tool_name} · ${label(step.tool.outcome || step.tool.approval_status)}`;
  if (step.observation) return `${step.observation.facts.length} persisted fact${step.observation.facts.length === 1 ? "" : "s"}`;
  if (step.adaptation) return `Decision: ${label(step.adaptation.decision)}`;
  return step.model_invocation ? "Model call details" : "Step details";
}

function renderStep(step, isLatest) {
  const card = node("article", `step-row source-${step.source} step-${step.status}`);
  const rail = node("div", "step-rail", String(step.sequence));
  const content = node("div", "step-content");
  const heading = node("header", "step-heading");
  const title = node("div");
  title.append(node("span", "source-label", step.source), node("h4", "", `${label(step.phase)} · ${label(step.status)}`));
  const meta = node("div", "step-meta");
  meta.append(node("span", "", duration(step.duration_ms)), copyButton("Step", String(step.id)));
  heading.append(title, meta);
  content.append(heading, node("p", "step-summary", step.summary));

  const details = node("details", "evidence-details");
  details.open = isLatest || ["failed", "running", "pending"].includes(step.status);
  details.append(node("summary", "", evidenceSummary(step)));
  const body = node("div", "evidence-body");
  if (step.plan) {
    body.append(node("h5", "", "Plan goal"), node("p", "", step.plan.goal));
    const actions = node("ol", "action-list");
    for (const action of step.plan.actions) {
      const item = node("li");
      item.append(node("strong", "", action.tool_name), node("span", "", action.purpose));
      actions.append(item);
    }
    body.append(node("h5", "", "Ordered actions"), actions);
    if (step.plan.success_criteria.length) {
      const criteria = node("ul", "plain-list");
      for (const criterion of step.plan.success_criteria) criteria.append(node("li", "", criterion));
      body.append(node("h5", "", "Success criteria"), criteria);
    }
  }
  if (step.tool) {
    const tool = step.tool;
    const toolHeader = node("div", "tool-heading");
    toolHeader.append(node("h5", "", `${tool.tool_name}@${tool.tool_version}`), copyButton("Call", String(tool.call_id)));
    body.append(toolHeader);
    const facts = node("dl", "inline-facts");
    facts.append(
      metric("Approval", label(tool.approval_status)), metric("Outcome", label(tool.outcome)),
      metric("Duration", duration(tool.duration_ms)), metric("Retryable", tool.retryable ?? "—"),
    );
    body.append(facts);
    if (tool.redacted_arguments) body.append(node("h5", "", "Request"), renderValue(tool.redacted_arguments));
    if (tool.redacted_result) body.append(node("h5", "", "Result"), renderValue(tool.redacted_result));
    if (tool.error_code) body.append(node("p", "safe-error", `Error: ${label(tool.error_code)}`));
  }
  if (step.observation) {
    const observation = step.observation;
    const facts = node("ul", "plain-list");
    for (const fact of observation.facts) facts.append(node("li", "", fact));
    body.append(node("h5", "", "Observed facts"), facts);
    const criteria = node("dl", "inline-facts");
    criteria.append(
      metric("Satisfied", observation.satisfied_criteria.length),
      metric("Unsatisfied", observation.unsatisfied_criteria.length),
      metric("Unassessed", observation.unassessed_criteria.length),
    );
    body.append(criteria);
  }
  if (step.adaptation) {
    body.append(node("h5", "", `Decision · ${label(step.adaptation.decision)}`), node("p", "", step.adaptation.justification));
    if (step.adaptation.redacted_final_result) body.append(node("h5", "", "Proposed final result"), renderValue(step.adaptation.redacted_final_result));
  }
  if (step.model_invocation) {
    const model = step.model_invocation;
    const metrics = node("dl", "model-metrics");
    metrics.append(
      metric("Provider / model", `${model.provider} · ${model.model}`),
      metric("Prompt", `${model.prompt_id}@${model.prompt_version}`),
      metric("Total", duration(model.metrics.total_duration_ms)),
      metric("Prompt evaluation", duration(model.metrics.prompt_eval_duration_ms)),
      metric("Generation", duration(model.metrics.eval_duration_ms)),
      metric("Tokens", `${model.metrics.prompt_tokens ?? "?"} in · ${model.metrics.output_tokens ?? "?"} out`),
      metric("Cache", `${model.metrics.cached_prompt_tokens ?? "?"} read · ${model.metrics.cache_write_prompt_tokens ?? "?"} written`),
      metric("Provider request", model.provider_request_id || "Not supplied"),
      metric("Retries", String(model.metrics.retry_count ?? 0)),
      metric("Repairs", String(model.repair_count)),
      metric("Incomplete-response retries", String(model.provider_retry_count ?? 0)),
    );
    body.append(node("h5", "", "Model details"), metrics);
  }
  if (step.error) body.append(node("p", "safe-error", `${step.error.code}: ${step.error.message}`));
  details.append(body);
  content.append(details);
  card.append(rail, content);
  return card;
}

function renderExecution(steps, reviews) {
  ui.execution.replaceChildren();
  if (!steps.length) ui.execution.append(node("p", "empty", "The review is queued; no work has been recorded yet."));
  steps.forEach((step, index) => ui.execution.append(renderStep(step, index === steps.length - 1)));
  for (const review of reviews) {
    const card = node("article", "review-row");
    card.append(
      node("span", "review-symbol", "‖"),
      node("h4", "", `${label(review.decision)} · ${review.tool_name}`),
      node("p", "", `${review.reviewer}${review.comment ? ` · ${review.comment}` : ""}`),
      copyButton("Call", String(review.call_id)),
    );
    ui.execution.append(card);
  }
}

function renderEvents() {
  ui["event-list"].replaceChildren();
  if (!state.eventItems.length) ui["event-list"].append(node("li", "empty", "No retained events are available for this run."));
  for (const event of [...state.eventItems].reverse()) {
    const item = node("li", "event-item");
    item.append(
      statusMark(event.status, "event-status"),
      node("strong", "", label(event.event_type)),
      node("span", "muted", `${shortTime(event.occurred_at)} · run v${event.run_version} · event #${event.id}`),
    );
    ui["event-list"].append(item);
  }
  ui["event-cursor"].textContent = `cursor #${state.eventCursor}`;
}

function updateLiveElapsed() {
  const now = Date.now();
  for (const run of state.runs) {
    const target = ui["run-list"].querySelector(`[data-run-live="${run.id}"]`);
    if (!target) continue;
    target.textContent = ACTIVE_STATUSES.has(run.status) ? duration(elapsedSince(run.created_at, now)) : duration(run.duration_ms);
  }
  if (!state.detail) return;
  const runElapsed = TERMINAL_STATUSES.has(state.detail.run.status)
    ? state.detail.run.duration_ms
    : elapsedSince(state.detail.run.created_at, now);
  ui["live-elapsed"].textContent = duration(runElapsed);
  const overviewElapsed = ui["run-overview"].querySelector("[data-overview-elapsed]");
  if (overviewElapsed) overviewElapsed.textContent = duration(runElapsed);
  const stepElapsed = ui["current-work-detail"].querySelector("[data-step-started]");
  if (stepElapsed) stepElapsed.textContent = `${duration(elapsedSince(stepElapsed.dataset.stepStarted, now))} in this step`;
}

async function copyValue(value, successMessage) {
  await navigator.clipboard.writeText(value);
  ui.announcement.textContent = successMessage;
}

ui.filters.addEventListener("submit", (event) => {
  event.preventDefault();
  if (ui["status-filter"].value) state.quickFilter = "all";
  updateQuickFilters();
  syncFilterUrl();
  invalidateRunIndex();
});
ui["status-filter"].addEventListener("change", () => {
  if (ui["status-filter"].value) state.quickFilter = "all";
  updateQuickFilters();
});
ui["quick-filters"].addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  state.quickFilter = button.dataset.filter;
  ui["status-filter"].value = "";
  updateQuickFilters();
  syncFilterUrl();
  invalidateRunIndex();
});
ui["clear-filters"].addEventListener("click", () => {
  ui.filters.reset();
  state.quickFilter = "all";
  updateQuickFilters();
  syncFilterUrl();
  invalidateRunIndex();
});
ui["refresh-runs"].addEventListener("click", () => {
  state.listRefreshPending = true;
  scheduleList(0);
});
ui["load-more"].addEventListener("click", () => loadRuns({ append: true }));
ui["copy-link"].addEventListener("click", () => copyValue(window.location.href, "Review link copied."));
ui["correlation-identifiers"].addEventListener("click", (event) => {
  const button = event.target.closest("button[data-copy-value]");
  if (button) copyValue(button.dataset.copyValue, `${button.querySelector(".copy-label").textContent} identifier copied.`);
});
ui.execution.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-copy-value]");
  if (button) copyValue(button.dataset.copyValue, `${button.querySelector(".copy-label").textContent} identifier copied.`);
});
ui["back-to-runs"].addEventListener("click", () => {
  ui.workspace.classList.remove("show-detail");
  ui["run-list"].querySelector(`[data-run-id="${state.selectedId}"]`)?.focus();
});
document.addEventListener("visibilitychange", () => {
  scheduleList(document.hidden ? nextListDelay(state.runs, state.listFailures, true) : 0);
  if (!document.hidden && state.selectedId) {
    clearTimeout(state.detailTimer);
    if (state.detailInFlight) {
      state.detailRefreshPending = true;
      state.detailForcePending = true;
    } else {
      refreshSelected(state.detailGuard.current, { forceDetail: true });
    }
  }
});

async function start() {
  const initial = new URL(window.location.href).searchParams;
  ui["feature-filter"].value = initial.get("feature_key") || "";
  ui["model-filter"].value = initial.get("model_profile") || "";
  const initialStatuses = initial.getAll("status");
  const view = initial.get("view");
  state.quickFilter = view && statusesForFilter(view).length ? view : filterForStatuses(initialStatuses);
  ui["status-filter"].value = initialStatuses.length === 1 ? initialStatuses[0] : "";
  updateQuickFilters();
  state.elapsedTimer = setInterval(updateLiveElapsed, 1000);
  await loadRuns();
  const runId = initial.get("run");
  if (runId && /^[0-9a-f-]{36}$/i.test(runId)) await selectRun(runId);
  else if (!window.matchMedia(MOBILE_QUERY).matches && state.runs.length) await selectRun(state.runs[0].id);
}

start();
