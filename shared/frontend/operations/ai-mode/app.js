const API_ROOT = "/api/v1";
const ACTIVE_STATUSES = new Set(["queued", "planning", "ready", "acting", "observing", "adapting"]);
const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);

const ui = Object.fromEntries([
  "announcement", "connection-dot", "connection-state", "filters", "feature-filter",
  "status-filter", "model-filter", "clear-filters", "count-active", "count-review",
  "count-failed", "count-complete", "run-list", "refresh-runs", "load-more", "run-detail",
  "empty-detail", "detail-content", "run-status", "stale-state", "run-objective",
  "run-subtitle", "copy-link", "phase-strip", "last-updated", "run-metadata", "execution",
  "event-cursor", "event-list", "raw-projection",
].map((id) => [id, document.getElementById(id)]));

const state = {
  runs: [], nextCursor: null, selectedId: null, detail: null, etag: null, eventCursor: 0,
  eventItems: [], generation: 0, detailTimer: null, listTimer: null, failures: 0,
  detailController: null,
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
function duration(value) {
  if (value === null || value === undefined) return "—";
  if (value < 1000) return `${value} ms`;
  return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} s`;
}

async function requestJson(url, options = {}) {
  const { headers = {}, ...requestOptions } = options;
  const response = await fetch(url, { ...requestOptions, headers: { Accept: "application/json", ...headers } });
  if (response.status === 304) return { response, body: null };
  let body = null;
  try { body = await response.json(); } catch { throw new Error(`${response.status}: response was not JSON`); }
  if (!response.ok) throw new Error(`${response.status}: ${body.detail || body.code || "request failed"}`);
  return { response, body };
}

function setConnection(kind, message) {
  ui["connection-dot"].className = `connection-dot ${kind}`;
  ui["connection-state"].textContent = message;
  ui["stale-state"].hidden = kind !== "disconnected";
}

function filterQuery(cursor = null) {
  const params = new URLSearchParams({ limit: "50" });
  if (ui["feature-filter"].value.trim()) params.set("feature_key", ui["feature-filter"].value.trim());
  if (ui["status-filter"].value) params.append("status", ui["status-filter"].value);
  if (ui["model-filter"].value.trim()) params.set("model_profile", ui["model-filter"].value.trim());
  if (cursor) params.set("cursor", cursor);
  return params;
}

function syncFilterUrl() {
  const url = new URL(window.location.href);
  for (const key of ["feature_key", "status", "model_profile"]) url.searchParams.delete(key);
  const filters = filterQuery();
  filters.delete("limit");
  for (const [key, value] of filters) url.searchParams.append(key, value);
  history.replaceState(null, "", url);
}

async function loadRuns({ append = false } = {}) {
  try {
    const cursor = append ? state.nextCursor : null;
    const { body } = await requestJson(`${API_ROOT}/agent-runs?${filterQuery(cursor)}`);
    const byId = new Map((append ? state.runs : []).map((run) => [run.id, run]));
    for (const run of body.items) byId.set(run.id, run);
    state.runs = [...byId.values()];
    state.nextCursor = body.next_cursor;
    renderRunList();
    setConnection("connected", "Live · persisted state");
    state.failures = 0;
  } catch (error) {
    setConnection("disconnected", `Run index unavailable · ${error.message}`);
    if (!state.runs.length) ui["run-list"].replaceChildren(node("li", "empty", error.message));
  }
}

function renderRunList() {
  const focusedRunId = document.activeElement?.dataset?.runId;
  ui["run-list"].replaceChildren();
  if (!state.runs.length) ui["run-list"].append(node("li", "empty", "No runs match these filters."));
  for (const run of state.runs) {
    const item = node("li", "run-item");
    const button = node("button");
    button.type = "button";
    button.dataset.runId = run.id;
    button.setAttribute("aria-current", String(run.id === state.selectedId));
    const top = node("div", "run-item-top");
    top.append(node("span", `status-badge status-${run.status}`, label(run.status)), node("span", "mono muted", `v${run.version}`));
    const objective = node("p", "run-objective", run.objective_preview || "Objective hidden by policy");
    const facts = node("div", "run-facts");
    facts.append(node("span", "", run.feature_key), node("span", "", label(run.latest_phase || "not started")), node("span", "", duration(run.duration_ms)));
    button.append(top, objective, facts);
    button.addEventListener("click", () => selectRun(run.id));
    item.append(button);
    ui["run-list"].append(item);
  }
  ui["load-more"].hidden = !state.nextCursor;
  ui["count-active"].textContent = String(state.runs.filter((run) => ACTIVE_STATUSES.has(run.status)).length);
  ui["count-review"].textContent = String(state.runs.filter((run) => run.status === "review_required").length);
  ui["count-failed"].textContent = String(state.runs.filter((run) => run.status === "failed").length);
  ui["count-complete"].textContent = String(state.runs.filter((run) => run.status === "succeeded").length);
  if (focusedRunId) ui["run-list"].querySelector(`[data-run-id="${focusedRunId}"]`)?.focus();
}

async function selectRun(runId) {
  state.generation += 1;
  state.detailController?.abort();
  state.detailController = new AbortController();
  state.selectedId = runId;
  state.detail = null;
  state.etag = null;
  state.eventCursor = Number(sessionStorage.getItem(`ai-mode-operations:${runId}:cursor`) || "0");
  state.eventItems = [];
  clearTimeout(state.detailTimer);
  const url = new URL(window.location.href);
  url.searchParams.set("run", runId);
  history.replaceState(null, "", url);
  renderRunList();
  ui["empty-detail"].hidden = true;
  ui["detail-content"].hidden = false;
  ui["run-objective"].textContent = "Loading durable evidence…";
  ui["event-list"].replaceChildren(node("li", "empty", `Reconnecting after cursor #${state.eventCursor}`));
  await refreshSelected(state.generation, true);
}

async function refreshSelected(generation, forceDetail = false) {
  if (!state.selectedId || generation !== state.generation) return;
  try {
    const eventUrl = `${API_ROOT}/agent-runs/${state.selectedId}/events?after=${state.eventCursor}&limit=200`;
    const events = await requestJson(eventUrl, { signal: state.detailController.signal });
    if (generation !== state.generation) return;
    appendEvents(events.body.items);
    if (forceDetail || events.body.items.length || !state.detail) await loadDetail(generation);
    if (events.body.terminal && state.detail) {
      await loadDetail(generation, true);
      setConnection("connected", `Run ${label(state.detail.run.status)} · polling complete`);
      return;
    }
    state.failures = 0;
    setConnection("connected", "Live · cursor polling");
  } catch (error) {
    if (error.name === "AbortError" || generation !== state.generation) return;
    state.failures += 1;
    setConnection("disconnected", `Disconnected · ${error.message}`);
  }
  if (generation !== state.generation) return;
  const base = state.detail?.run.status === "review_required" ? 5000 : state.detail?.run.status === "queued" ? 2000 : 800;
  const backoff = Math.min(15000, base * (2 ** Math.min(state.failures, 4)));
  const hiddenMultiplier = document.hidden ? 4 : 1;
  state.detailTimer = setTimeout(() => refreshSelected(generation), backoff * hiddenMultiplier);
}

async function loadDetail(generation, finalRefresh = false) {
  const headers = {};
  if (state.etag && !finalRefresh) headers["If-None-Match"] = state.etag;
  const { response, body } = await requestJson(`${API_ROOT}/operations/agent-runs/${state.selectedId}`, { headers, signal: state.detailController.signal });
  if (generation !== state.generation || response.status === 304) return;
  state.etag = response.headers.get("ETag");
  state.detail = body;
  renderDetail();
}

function appendEvents(items) {
  if (!items.length) return;
  const known = new Set(state.eventItems.map((item) => item.id));
  for (const item of items) if (!known.has(item.id)) state.eventItems.push(item);
  state.eventItems.sort((a, b) => a.id - b.id);
  state.eventItems = state.eventItems.slice(-200);
  state.eventCursor = Math.max(state.eventCursor, ...items.map((item) => item.id));
  sessionStorage.setItem(`ai-mode-operations:${state.selectedId}:cursor`, String(state.eventCursor));
  renderEvents();
}

function renderEvents() {
  ui["event-list"].replaceChildren();
  if (!state.eventItems.length) ui["event-list"].append(node("li", "empty", "No new events after the restored cursor."));
  for (const event of state.eventItems) {
    const item = node("li");
    item.append(node("span", `event-status status-${event.status}`, label(event.status)), node("strong", "", label(event.event_type)), node("span", "mono muted", `event #${event.id} · run v${event.run_version}`), node("time", "", localTime(event.occurred_at)));
    ui["event-list"].append(item);
  }
  ui["event-cursor"].textContent = `#${state.eventCursor}`;
}

function addDefinition(target, entries) {
  const list = target.tagName === "DL" ? target : node("dl", "metadata-grid");
  for (const [key, value] of entries) {
    const wrapper = node("div");
    wrapper.append(node("dt", "", key), node("dd", "mono", String(value ?? "—")));
    list.append(wrapper);
  }
  if (list !== target) target.append(list);
}

function evidenceBlock(title) {
  const block = node("div", "evidence-block");
  block.append(node("h5", "", title));
  return block;
}

function renderDetail() {
  const { run, objective, limits, cancel_requested: cancelRequested, final_result: finalResult, error, steps, reviews, correlation } = state.detail;
  ui["run-status"].textContent = label(run.status);
  ui["run-status"].className = `status-badge status-${run.status}`;
  ui["run-objective"].textContent = objective || run.objective_preview || "Objective hidden by policy";
  ui["run-subtitle"].textContent = `${run.feature_key} · ${run.id}`;
  ui["last-updated"].textContent = `Updated ${localTime(run.updated_at)}`;
  ui["run-metadata"].replaceChildren();
  addDefinition(ui["run-metadata"], [
    ["Run ID", run.id], ["Request ID", correlation.request_id], ["Trace ID", correlation.trace_id],
    ["Model profile", run.model_profile], ["Prompt set", run.prompt_set], ["Version", run.version],
    ["Iterations", `${run.iteration_count} / ${limits.max_iterations}`],
    ["Tool calls", `${run.tool_call_count} / ${limits.max_tool_calls}`],
    ["Time budget", duration(limits.time_budget_ms)], ["Model repairs", limits.max_model_repairs],
    ["Cancel requested", cancelRequested ? "yes" : "no"],
    ["Created", localTime(run.created_at)], ["Duration", duration(run.duration_ms)],
  ]);
  renderPhases(steps);
  renderExecution(steps, reviews, finalResult, error, run);
  ui["raw-projection"].textContent = pretty(state.detail);
  ui.announcement.textContent = `Run ${run.id} updated to ${label(run.status)}, version ${run.version}.`;
}

function renderPhases(steps) {
  const complete = new Set(steps.filter((step) => step.status === "succeeded").map((step) => step.phase));
  const active = [...steps].reverse().find((step) => ["running", "pending"].includes(step.status))?.phase;
  for (const item of ui["phase-strip"].querySelectorAll("[data-phase]")) {
    item.classList.toggle("complete", complete.has(item.dataset.phase));
    item.classList.toggle("active", active === item.dataset.phase);
  }
}

function renderExecution(steps, reviews, finalResult, error, run) {
  ui.execution.replaceChildren();
  if (!steps.length) ui.execution.append(node("p", "empty", "The run is queued; no phase step is durable yet."));
  for (const step of steps) ui.execution.append(renderStep(step));
  for (const review of reviews) {
    const card = node("article", "step-card source-human");
    const heading = node("div", "step-heading");
    const title = node("div");
    title.append(node("span", "source-label", "human"), node("h4", "", `${label(review.decision)} · ${review.tool_name}`));
    heading.append(title, node("span", "mono muted", localTime(review.reviewed_at)));
    card.append(heading, node("p", "", `${review.reviewer}${review.comment ? ` · ${review.comment}` : ""}`));
    ui.execution.append(card);
  }
  if (finalResult) {
    const card = node("article", "step-card source-orchestration");
    card.append(node("span", "source-label", "orchestration"), node("h4", "", "Final result"), node("pre", "", pretty(finalResult)));
    ui.execution.append(card);
  } else if (error || run.error_code) {
    const card = node("article", "step-card source-orchestration");
    card.append(node("span", "source-label", "safe error"), node("h4", "", label(error?.code || run.error_code)));
    if (error?.message) card.append(node("p", "", error.message));
    ui.execution.append(card);
  }
}

function renderStep(step) {
  const card = node("article", `step-card source-${step.source}`);
  const heading = node("div", "step-heading");
  const title = node("div");
  title.append(node("span", "source-label", `${step.source} · step ${step.sequence}`), node("h4", "", `${label(step.phase)} · ${label(step.status)}`));
  heading.append(title, node("span", "mono muted", duration(step.duration_ms)));
  card.append(heading, node("p", "muted", step.summary));
  if (step.plan) {
    const block = evidenceBlock("Plan");
    block.append(node("p", "", step.plan.goal));
    const actions = node("ol", "compact-list");
    for (const action of step.plan.actions) actions.append(node("li", "", `${action.tool_name} — ${action.purpose}`));
    block.append(actions);
    card.append(block);
  }
  if (step.tool) {
    const block = evidenceBlock(`Tool · ${step.tool.tool_name}@${step.tool.tool_version}`);
    addDefinition(block, [["Call ID", step.tool.call_id], ["Approval", label(step.tool.approval_status)], ["Outcome", label(step.tool.outcome)], ["Duration", duration(step.tool.duration_ms)], ["Retryable", step.tool.retryable]]);
    if (step.tool.redacted_arguments) block.append(node("pre", "", pretty(step.tool.redacted_arguments)));
    if (step.tool.redacted_result) block.append(node("pre", "", pretty(step.tool.redacted_result)));
    card.append(block);
  }
  if (step.observation) {
    const block = evidenceBlock("Observation");
    const facts = node("ul", "compact-list");
    for (const fact of step.observation.facts) facts.append(node("li", "", fact));
    block.append(facts);
    card.append(block);
  }
  if (step.adaptation) {
    const block = evidenceBlock(`Adaptation · ${label(step.adaptation.decision)}`);
    block.append(node("p", "", step.adaptation.justification));
    if (step.adaptation.redacted_final_result) block.append(node("pre", "", pretty(step.adaptation.redacted_final_result)));
    card.append(block);
  }
  if (step.model_invocation) {
    const model = step.model_invocation;
    const block = evidenceBlock("Model invocation");
    const metrics = node("div", "metrics");
    metrics.append(node("span", "", `${model.provider} · ${model.model}`), node("span", "", `${model.prompt_id}@${model.prompt_version}`), node("span", "", duration(model.metrics.total_duration_ms)), node("span", "", `${model.metrics.prompt_tokens ?? "?"} input tokens`), node("span", "", `${model.metrics.output_tokens ?? "?"} output tokens`), node("span", "", `${model.repair_count} repairs`));
    block.append(metrics);
    card.append(block);
  }
  if (step.error) card.append(node("p", "status-failed", `${step.error.code}: ${step.error.message}`));
  return card;
}

ui.filters.addEventListener("submit", (event) => { event.preventDefault(); syncFilterUrl(); loadRuns(); });
ui["clear-filters"].addEventListener("click", () => { ui.filters.reset(); syncFilterUrl(); loadRuns(); });
ui["refresh-runs"].addEventListener("click", () => loadRuns());
ui["load-more"].addEventListener("click", () => loadRuns({ append: true }));
ui["copy-link"].addEventListener("click", async () => {
  await navigator.clipboard.writeText(window.location.href);
  ui.announcement.textContent = "Run deep link copied.";
});
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) {
    loadRuns();
    if (state.selectedId) { clearTimeout(state.detailTimer); refreshSelected(state.generation, true); }
  }
});

async function start() {
  const initial = new URL(window.location.href).searchParams;
  ui["feature-filter"].value = initial.get("feature_key") || "";
  ui["status-filter"].value = initial.get("status") || "";
  ui["model-filter"].value = initial.get("model_profile") || "";
  await loadRuns();
  const runId = new URL(window.location.href).searchParams.get("run");
  if (runId && /^[0-9a-f-]{36}$/i.test(runId)) await selectRun(runId);
  state.listTimer = setInterval(() => { if (!document.hidden) loadRuns(); }, 5000);
}

start();
