const featureOutput = document.querySelector("#feature-output");
const agentOutput = document.querySelector("#agent-output");
const profileSelect = document.querySelector("#model-profile");
const conversation = document.querySelector("#conversation");
const eventFeed = document.querySelector("#event-feed");
const runMetadata = document.querySelector("#run-metadata");
const runStatus = document.querySelector("#run-status");
const pollState = document.querySelector("#poll-state");
const eventCursor = document.querySelector("#event-cursor");
const startButton = document.querySelector("#start-run");
const cancelButton = document.querySelector("#cancel-run");
const followUpButton = document.querySelector("#follow-up-run");
const historyList = document.querySelector("#run-history");
const historySummary = document.querySelector("#history-summary");
const historyStatus = document.querySelector("#history-status");
const loadMoreRunsButton = document.querySelector("#load-more-runs");
const reviewPanel = document.querySelector("#review-panel");
const reviewTool = document.querySelector("#review-tool");
const reviewIdempotency = document.querySelector("#review-idempotency");
const reviewArguments = document.querySelector("#review-arguments");
const reviewState = document.querySelector("#review-state");
const approveReviewButton = document.querySelector("#approve-review");
const rejectReviewButton = document.querySelector("#reject-review");

const scenarios = {
  "dependency-audit": "Audit Reference record 03. First search for it, then inspect its priority and summary, then inspect every direct dependency. Complete only after reporting the record priority and every dependency title, relationship, and status.",
  "single-lookup": "Search for Reference record 03 and complete when the matching record is observed.",
  "protected-create": () => `Create exactly one integration-test record titled Review checkpoint ${crypto.randomUUID().slice(0, 8)}. Use the protected create tool and complete only after the approved write result is observed.`,
};

const terminalStatuses = new Set(["succeeded", "failed", "cancelled"]);
let currentRun = null;
let currentLocation = null;
let currentObjective = "";
let cursor = 0;
let pollGeneration = 0;
let lastRenderedDetailSignature = null;
let selectedDetail = null;
let historyItems = [];
let historyNextCursor = null;

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function clear(target) {
  target.replaceChildren();
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

async function jsonRequest(url, options = {}) {
  const response = await fetch(url, options);
  let body;
  try {
    body = await response.json();
  } catch {
    throw new Error(`${response.status}: response was not JSON`);
  }
  if (!response.ok) {
    throw new Error(`${response.status}: ${body.detail || body.code || "request failed"}`);
  }
  return { response, body };
}

function requestHeaders(extra = {}) {
  return {
    "Content-Type": "application/json",
    "X-Request-ID": `integration-console-${crypto.randomUUID()}`,
    ...extra,
  };
}

function randomHex(byteLength) {
  return Array.from(crypto.getRandomValues(new Uint8Array(byteLength)))
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
}

function newTraceparent() {
  return `00-${randomHex(16)}-${randomHex(8)}-01`;
}

function renderFeatureMessage(title, description, tone = "neutral") {
  clear(featureOutput);
  const card = element("article", `result-card ${tone}`);
  card.append(element("h3", "", title), element("p", "muted", description));
  featureOutput.append(card);
}

function renderRecords(items, query) {
  clear(featureOutput);
  const heading = element("div", "result-summary");
  heading.append(
    element("strong", "", `${items.length} match${items.length === 1 ? "" : "es"}`),
    element("span", "muted", `Query: ${query}`),
  );
  featureOutput.append(heading);
  const grid = element("div", "record-grid");
  for (const item of items) {
    const card = element("article", "record-card");
    card.append(
      element("span", `status-dot ${item.status}`, item.status),
      element("h3", "", item.title),
      element("p", "mono muted", `record ${item.id}`),
    );
    grid.append(card);
  }
  featureOutput.append(grid);
}

function appendDefinitionList(target, entries) {
  const list = element("dl", "key-values");
  for (const [key, value] of entries) {
    list.append(element("dt", "", key), element("dd", "", String(value)));
  }
  target.append(list);
}

function renderObjectSummary(target, value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return;
  const entries = Object.entries(value)
    .filter(([, item]) => ["string", "number", "boolean"].includes(typeof item))
    .map(([key, item]) => [statusLabel(key), item]);
  if (entries.length) appendDefinitionList(target, entries);
}

function renderDependencyEvidence(detail, dependencies) {
  clear(featureOutput);
  const record = detail.record;
  const card = element("article", "result-card success");
  card.append(element("h3", "", record.title));
  appendDefinitionList(card, [
    ["Status", record.status],
    ["Priority", `${record.priority} / 5`],
    ["Summary", record.summary],
  ]);
  featureOutput.append(card);

  const heading = element("div", "result-summary");
  heading.append(
    element("strong", "", `${dependencies.count} direct dependencies`),
    element("span", dependencies.all_active ? "badge success" : "badge warning", dependencies.all_active ? "All active" : "Attention required"),
  );
  featureOutput.append(heading);
  const grid = element("div", "record-grid");
  for (const item of dependencies.items) {
    const dependency = element("article", "record-card");
    dependency.append(element("span", `status-dot ${item.status}`, item.status), element("h3", "", item.title));
    appendDefinitionList(dependency, [["Relationship", item.relationship], ["Priority", `${item.priority} / 5`]]);
    grid.append(dependency);
  }
  featureOutput.append(grid);
}

function statusLabel(value) {
  return value.replaceAll("_", " ");
}

function setRunStatus(status) {
  runStatus.textContent = statusLabel(status);
  runStatus.className = `badge status-${status}`;
  cancelButton.disabled = status === "idle" || terminalStatuses.has(status);
  startButton.disabled = !terminalStatuses.has(status) && status !== "idle";
}

function pendingReviewCall(detail) {
  if (detail.run.status !== "review_required") return null;
  const pending = detail.steps.find((step) => (
    step.phase === "act"
    && step.status === "pending"
    && step.input?.tool_call?.approval_status === "pending"
  ));
  return pending?.input.tool_call || null;
}

function renderReviewPanel(detail) {
  const call = pendingReviewCall(detail);
  reviewPanel.hidden = !call;
  if (!call) {
    reviewState.textContent = "";
    return;
  }
  reviewTool.textContent = `${call.tool_name}@${call.tool_version}`;
  reviewIdempotency.textContent = call.idempotency_key || "not supplied";
  reviewArguments.textContent = pretty(call.arguments);
  reviewState.textContent = "Awaiting a human decision.";
  approveReviewButton.disabled = false;
  rejectReviewButton.disabled = false;
}

function formatDuration(milliseconds) {
  if (milliseconds < 1000) return `${milliseconds} ms`;
  if (milliseconds < 60000) return `${(milliseconds / 1000).toFixed(1)} s`;
  return `${Math.floor(milliseconds / 60000)}m ${Math.round((milliseconds % 60000) / 1000)}s`;
}

function renderHistory() {
  clear(historyList);
  historySummary.textContent = `${historyItems.length} recent durable run${historyItems.length === 1 ? "" : "s"}`;
  if (!historyItems.length) {
    historyList.append(element("div", "empty-state compact-empty", "No matching runs yet."));
  }
  for (const run of historyItems) {
    const card = element("button", "run-history-card");
    card.type = "button";
    card.dataset.runId = run.id;
    card.classList.toggle("active", run.id === currentRun?.id);
    card.setAttribute("aria-pressed", String(run.id === currentRun?.id));
    const heading = element("span", "history-card-heading");
    heading.append(
      element("span", `badge status-${run.status}`, statusLabel(run.status)),
      element("time", "muted", new Date(run.created_at).toLocaleString()),
    );
    card.append(
      heading,
      element("strong", "history-objective", run.objective_preview || "Objective hidden by evidence policy"),
      element("span", "history-meta", `${run.tool_call_count} tools · ${run.iteration_count} iterations · ${formatDuration(run.duration_ms)}`),
    );
    card.addEventListener("click", () => loadHistoricalRun(run.id));
    historyList.append(card);
  }
  loadMoreRunsButton.hidden = !historyNextCursor;
}

async function loadHistory({ append = false } = {}) {
  if (!append) {
    historyItems = [];
    historyNextCursor = null;
    historySummary.textContent = "Loading durable runs…";
  }
  loadMoreRunsButton.disabled = true;
  const query = new URLSearchParams({
    feature_key: "student-1-integration-test",
    limit: "8",
  });
  if (historyStatus.value) query.append("status", historyStatus.value);
  if (append && historyNextCursor) query.set("cursor", historyNextCursor);
  try {
    const { body } = await jsonRequest(`/api/ai/agent-runs?${query}`);
    historyItems = append ? historyItems.concat(body.items) : body.items;
    historyNextCursor = body.next_cursor;
    renderHistory();
  } catch (error) {
    historySummary.textContent = `History unavailable: ${error.message}`;
    clear(historyList);
    historyList.append(element("div", "empty-state compact-empty", "Enable the local operations projection to browse runs."));
  } finally {
    loadMoreRunsButton.disabled = false;
  }
}

function resetEventFeed(message) {
  cursor = 0;
  clear(eventFeed);
  eventFeed.append(element("li", "empty-state", message));
  eventCursor.textContent = "cursor 0";
}

async function loadHistoricalRun(runId) {
  pollGeneration += 1;
  const generation = pollGeneration;
  currentLocation = `/api/ai/agent-runs/${runId}`;
  currentObjective = "";
  currentRun = null;
  selectedDetail = null;
  lastRenderedDetailSignature = null;
  followUpButton.disabled = true;
  resetEventFeed("Loading persisted events…");
  pollState.textContent = "Loading durable run evidence…";
  try {
    const [detail, events] = await Promise.all([
      jsonRequest(currentLocation),
      jsonRequest(`${currentLocation}/events?after=0&limit=200`),
    ]);
    selectedDetail = detail.body;
    renderRun(detail.body);
    appendEvents(events.body.items);
    followUpButton.disabled = false;
    pollState.textContent = terminalStatuses.has(detail.body.run.status)
      ? `Loaded durable ${statusLabel(detail.body.run.status)} run.`
      : "Resuming live event polling for this durable run…";
    renderHistory();
    if (!events.body.terminal) pollRun(generation);
  } catch (error) {
    pollState.textContent = `Could not load run: ${error.message}`;
  }
}

async function loadHealth() {
  const checks = [
    ["#ai-health", "/api/health/ai", "AI-mode"],
    ["#feature-health", "/api/health/feature", "Feature boundary"],
  ];
  await Promise.all(checks.map(async ([selector, url, label]) => {
    const target = document.querySelector(selector);
    target.className = "service-pill checking";
    target.lastChild.textContent = `${label} checking`;
    try {
      const { body } = await jsonRequest(url);
      const healthy = body.status === "healthy";
      target.className = `service-pill ${healthy ? "healthy" : "degraded"}`;
      target.lastChild.textContent = `${label} ${body.status}`;
    } catch {
      target.className = "service-pill offline";
      target.lastChild.textContent = `${label} unavailable`;
    }
  }));
}

function renderMetadata(run) {
  runMetadata.hidden = false;
  clear(runMetadata);
  const fields = [
    ["Run ID", run.id],
    ["Request ID", run.request_id],
    ["Traceparent", run.traceparent || "not supplied"],
    ["Model profile", run.model_profile],
    ["Prompt set", run.prompt_set],
    ["Iterations", `${run.iteration_count} / ${run.limits.max_iterations}`],
    ["Tool calls", `${run.tool_call_count} / ${run.limits.max_tool_calls}`],
    ["Version", run.version],
  ];
  for (const [label, value] of fields) {
    const item = element("div", "metadata-item");
    item.append(element("span", "", label), element("strong", "mono", String(value)));
    runMetadata.append(item);
  }
}

function addRawDetails(target, label, value, stateKey = label) {
  const details = element("details", "step-raw");
  details.dataset.stateKey = stateKey;
  details.append(element("summary", "", label), element("pre", "", pretty(value)));
  target.append(details);
}

function renderPlan(target, plan) {
  target.append(element("p", "step-lead", plan.goal));
  const actions = element("ol", "action-list");
  for (const action of plan.actions) {
    const item = element("li", "");
    item.append(element("strong", "mono", action.tool_name), element("span", "", action.purpose));
    actions.append(item);
  }
  target.append(actions);
  const criteria = element("ul", "criteria-list");
  for (const criterion of plan.success_criteria) criteria.append(element("li", "", criterion));
  target.append(element("h5", "", "Success criteria"), criteria);
}

function renderAct(target, step) {
  const call = step.input.tool_call;
  const result = step.output.tool_result;
  if (call) {
    target.append(element("p", "step-lead mono", call.tool_name));
    appendDefinitionList(target, [
      ["Call ID", call.id],
      ["Approval", statusLabel(call.approval_status)],
      ["Idempotency", call.idempotency_key || "read-only / not required"],
    ]);
    addRawDetails(target, "Tool arguments", call.arguments, `${step.id}:arguments`);
  }
  if (result) {
    const resultLine = element("p", `tool-outcome ${result.outcome}`, `${statusLabel(result.outcome)} · ${result.duration_ms} ms`);
    target.append(resultLine);
    if (result.error) target.append(element("p", "error-text", `${result.error.code}: ${result.error.message}`));
    if (result.content.record) renderObjectSummary(target, result.content.record);
    if (Number.isInteger(result.content.count)) {
      const active = typeof result.content.all_active === "boolean"
        ? ` · all active: ${result.content.all_active ? "yes" : "no"}`
        : "";
      target.append(element("p", "step-lead", `${result.content.count} item${result.content.count === 1 ? "" : "s"} returned${active}.`));
    }
    addRawDetails(target, "Tool result", result.content, `${step.id}:result`);
    if (result.evidence_references?.length) {
      target.append(element("p", "mono muted", result.evidence_references.join(" · ")));
    }
  }
}

function renderObserve(target, observation) {
  const facts = element("ul", "criteria-list");
  for (const fact of observation.facts) facts.append(element("li", "", fact));
  target.append(facts);
  if (observation.unassessed_criteria?.length) {
    target.append(element("p", "muted", `${observation.unassessed_criteria.length} success criteria remain model-assessed.`));
  }
}

function renderAdapt(target, adaptation, stepId) {
  target.append(
    element("p", `decision decision-${adaptation.decision}`, statusLabel(adaptation.decision)),
    element("p", "step-lead", adaptation.justification),
  );
  if (adaptation.final_result) {
    addRawDetails(target, "Final result", adaptation.final_result, `${stepId}:final-result`);
  }
}

function renderInvocation(target, invocation) {
  if (!invocation) return;
  const metrics = invocation.metrics || {};
  const summary = element("div", "invocation-summary");
  appendDefinitionList(summary, [
    ["Model", `${invocation.provider} / ${invocation.model}`],
    ["Prompt", `${invocation.prompt_id}@${invocation.prompt_version}`],
    ["Duration", `${metrics.total_duration_ms ?? 0} ms`],
    ["Tokens", `${metrics.prompt_tokens ?? "?"} in / ${metrics.output_tokens ?? "?"} out`],
    ["Repairs", invocation.repair_count],
  ]);
  target.append(summary);
}

function renderStep(step) {
  const article = element("article", `trace-step phase-${step.phase} status-${step.status}`);
  const heading = element("header", "trace-step-heading");
  const title = element("div", "");
  title.append(element("span", "step-sequence", String(step.sequence)), element("h4", "", statusLabel(step.phase)));
  heading.append(title, element("span", `badge status-${step.status}`, statusLabel(step.status)));
  article.append(heading);

  if (step.phase === "plan" && step.output.plan) renderPlan(article, step.output.plan);
  if (step.phase === "act") renderAct(article, step);
  if (step.phase === "observe" && step.output.observation) renderObserve(article, step.output.observation);
  if (step.phase === "adapt" && step.output.adaptation) {
    renderAdapt(article, step.output.adaptation, step.id);
  }
  renderInvocation(article, step.output.model_invocation);
  if (step.error) article.append(element("p", "error-text", `${step.error.code}: ${step.error.message}`));
  if (step.started_at) {
    const completed = step.completed_at ? ` → ${new Date(step.completed_at).toLocaleTimeString()}` : " → running";
    article.append(element("p", "timestamp", `${new Date(step.started_at).toLocaleTimeString()}${completed}`));
  }
  addRawDetails(article, "Persisted step envelope", step, `${step.id}:envelope`);
  return article;
}

function renderRun(detail) {
  const signature = JSON.stringify(detail);
  currentRun = detail.run;
  setRunStatus(detail.run.status);
  if (signature === lastRenderedDetailSignature) return;
  const expandedDetails = new Set(
    Array.from(conversation.querySelectorAll("details[open][data-state-key]"))
      .map((item) => item.dataset.stateKey),
  );
  lastRenderedDetailSignature = signature;
  selectedDetail = detail;
  followUpButton.disabled = false;
  renderReviewPanel(detail);
  renderMetadata(detail.run);
  agentOutput.textContent = pretty(detail);
  clear(conversation);

  const userMessage = element("article", "message user-message");
  userMessage.append(element("span", "message-role", "User objective"), element("p", "", currentObjective || detail.run.objective));
  conversation.append(userMessage);

  for (const step of detail.steps) conversation.append(renderStep(step));

  for (const review of detail.reviews) {
    const reviewMessage = element("article", "message review-message");
    reviewMessage.append(
      element("span", "message-role", "Human review decision"),
      element("p", "step-lead", `${review.reviewer} ${review.decision}d ${review.tool_call.tool_name}.`),
    );
    if (review.comment) reviewMessage.append(element("p", "muted", review.comment));
    addRawDetails(reviewMessage, "Immutable review record", review, `${review.id}:review`);
    conversation.append(reviewMessage);
  }

  if (detail.run.status === "succeeded") {
    const assistant = element("article", "message assistant-message");
    assistant.append(element("span", "message-role", "Agent result"));
    renderObjectSummary(assistant, detail.run.final_result || {});
    addRawDetails(
      assistant,
      "Grounded final response",
      detail.run.final_result || {},
      `${detail.run.id}:final-response`,
    );
    conversation.append(assistant);
  } else if (detail.run.error) {
    const error = element("article", "message error-message");
    error.append(element("span", "message-role", "Run failed"), element("p", "", `${detail.run.error.code}: ${detail.run.error.message}`));
    conversation.append(error);
  } else if (detail.run.status === "review_required") {
    const review = element("article", "message review-message");
    review.append(element("span", "message-role", "Human review required"), element("p", "", "A protected or uncertain action is paused. Use the run API to approve or reject it."));
    conversation.append(review);
  }

  const completedPhases = new Set(detail.steps.filter((step) => step.status === "succeeded").map((step) => step.phase));
  const activePhase = detail.steps.findLast((step) => step.status === "running" || step.status === "pending")?.phase;
  for (const item of document.querySelectorAll(".phase-strip [data-phase]")) {
    item.classList.toggle("complete", completedPhases.has(item.dataset.phase));
    item.classList.toggle("active", item.dataset.phase === activePhase);
  }
  for (const details of conversation.querySelectorAll("details[data-state-key]")) {
    details.open = expandedDetails.has(details.dataset.stateKey);
  }
}

function appendEvents(events) {
  if (!events.length) return;
  if (eventFeed.querySelector(".empty-state")) clear(eventFeed);
  for (const event of events) {
    const item = element("li", `event-item status-${event.status}`);
    const header = element("div", "event-heading");
    header.append(element("strong", "", statusLabel(event.event_type)), element("span", "mono", `#${event.id}`));
    item.append(header, element("p", "", `${statusLabel(event.status)}${event.step_phase ? ` · ${statusLabel(event.step_phase)}` : ""}`));
    item.append(element("time", "muted", new Date(event.occurred_at).toLocaleTimeString()));
    eventFeed.append(item);
    cursor = event.id;
  }
  eventCursor.textContent = `cursor ${cursor}`;
  eventFeed.scrollTop = eventFeed.scrollHeight;
}

async function pollRun(generation) {
  if (!currentLocation) return;
  for (let attempt = 0; attempt < 450 && generation === pollGeneration; attempt += 1) {
    try {
      pollState.textContent = "Waiting for persisted events…";
      const events = await jsonRequest(`${currentLocation}/events?after=${cursor}&limit=200`);
      appendEvents(events.body.items);
      if (events.body.items.length > 0 || !currentRun) {
        const detail = await jsonRequest(currentLocation);
        renderRun(detail.body);
      }
      if (events.body.terminal && currentRun) {
        pollState.textContent = `Run reached ${statusLabel(currentRun.status)}.`;
        loadHistory();
        return;
      }
      if (currentRun?.status === "review_required") {
        pollState.textContent = "Protected action paused for human review.";
        loadHistory();
        return;
      }
    } catch (error) {
      pollState.textContent = `Polling error: ${error.message}`;
    }
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
  if (generation === pollGeneration) {
    pollState.textContent = "Polling stopped after six minutes; the run remains durable and can be reloaded by ID.";
    startButton.disabled = false;
  }
}

async function loadProfiles() {
  try {
    const { body } = await jsonRequest("/api/ai/model-profiles");
    for (const profile of body.profiles) {
      const modelRoutes = Object.entries(profile.role_models).map(([role, modelKey]) => {
        const model = body.models.find((item) => item.key === modelKey);
        return `${role}: ${model?.model_id ?? modelKey}`;
      });
      const option = document.createElement("option");
      const supportsAgentRun = ["planner", "adapter"].every((role) => role in profile.role_models);
      const supportsPlannerOutput = profile.maximum_output_tokens >= 1024;
      const selectable = supportsAgentRun && supportsPlannerOutput;
      option.value = profile.key;
      option.disabled = !selectable;
      option.selected = selectable && profile.key === body.default_profile;
      const restriction = !supportsAgentRun
        ? " — reviewer only"
        : !supportsPlannerOutput
          ? " — smoke diagnostic only"
          : "";
      option.textContent = `${profile.key} — ${modelRoutes.join(", ")} (${profile.context_tokens} ctx)${restriction}`;
      profileSelect.append(option);
    }
    agentOutput.textContent = `Ready. Default profile: ${body.default_profile}`;
    pollState.textContent = "Ready to create a durable agent run.";
  } catch (error) {
    agentOutput.textContent = `Could not load model registry: ${error.message}`;
    pollState.textContent = "Model registry unavailable.";
  }
}

document.querySelector("#scenario").addEventListener("change", (event) => {
  const preset = scenarios[event.target.value];
  const objective = typeof preset === "function" ? preset() : preset;
  if (objective) document.querySelector("#objective").value = objective;
  if (event.target.value === "custom") document.querySelector("#objective").focus();
});

document.querySelector("#search-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const query = document.querySelector("#search-query").value;
  renderFeatureMessage("Searching…", "Calling the backend tool and its database service.");
  try {
    const { body } = await jsonRequest("/api/feature/records.search.v1", {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({ query }),
    });
    renderRecords(body.items, query);
  } catch (error) {
    renderFeatureMessage("Search failed", error.message, "error");
  }
});

document.querySelector("#create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = document.querySelector("#record-title").value;
  const idempotencyKey = `${crypto.randomUUID()}:call:${crypto.randomUUID()}`;
  renderFeatureMessage("Creating…", "Applying one idempotent database mutation.");
  try {
    const { body } = await jsonRequest("/api/feature/records.create.v1", {
      method: "POST",
      headers: requestHeaders({ "Idempotency-Key": idempotencyKey }),
      body: JSON.stringify({ title }),
    });
    renderFeatureMessage(
      body.created ? "Record created" : "Idempotent replay",
      `${body.record.title} is ${body.record.status} with ID ${body.record.id}.`,
      "success",
    );
  } catch (error) {
    renderFeatureMessage("Create failed", error.message, "error");
  }
});

document.querySelector("#explore-record").addEventListener("click", async () => {
  renderFeatureMessage("Inspecting…", "Collecting record detail and dependency evidence.");
  const options = {
    method: "POST",
    headers: requestHeaders(),
    body: JSON.stringify({ title: "Reference record 03" }),
  };
  try {
    const [detail, dependencies] = await Promise.all([
      jsonRequest("/api/feature/records.inspect.v1", options),
      jsonRequest("/api/feature/records.dependencies.v1", { ...options, headers: requestHeaders() }),
    ]);
    renderDependencyEvidence(detail.body, dependencies.body);
  } catch (error) {
    renderFeatureMessage("Inspection failed", error.message, "error");
  }
});

document.querySelector("#agent-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  pollGeneration += 1;
  const generation = pollGeneration;
  currentObjective = document.querySelector("#objective").value.trim();
  currentRun = null;
  selectedDetail = null;
  currentLocation = null;
  lastRenderedDetailSignature = null;
  followUpButton.disabled = true;
  resetEventFeed("Waiting for the first persisted event…");
  setRunStatus("queued");
  pollState.textContent = "Submitting a validated, idempotent run request…";
  try {
    const { response, body } = await jsonRequest("/api/ai/agent-runs", {
      method: "POST",
      headers: requestHeaders({
        "Idempotency-Key": crypto.randomUUID(),
        traceparent: newTraceparent(),
      }),
      body: JSON.stringify({
        feature_key: "student-1-integration-test",
        objective: currentObjective,
        prompt_set: "default.v3",
        model_profile: profileSelect.value,
        limits: { max_iterations: 8, max_tool_calls: 12, time_budget_ms: 360000, max_model_repairs: 1 },
      }),
    });
    const location = response.headers.get("Location") || `/api/v1/agent-runs/${body.id}`;
    currentLocation = location.replace(/^\/api\/v1\//, "/api/ai/");
    renderRun({ run: body, steps: [], reviews: [] });
    pollRun(generation);
  } catch (error) {
    setRunStatus("failed");
    pollState.textContent = `Could not create run: ${error.message}`;
    agentOutput.textContent = error.message;
    startButton.disabled = false;
  }
});

cancelButton.addEventListener("click", async () => {
  if (!currentLocation || !currentRun) return;
  cancelButton.disabled = true;
  pollState.textContent = "Recording cancellation intent…";
  try {
    await jsonRequest(`${currentLocation}/cancel`, { method: "POST", headers: requestHeaders() });
  } catch (error) {
    pollState.textContent = `Cancellation failed: ${error.message}`;
    cancelButton.disabled = false;
  }
});

async function submitReview(decision) {
  if (!currentLocation || currentRun?.status !== "review_required") return;
  const reviewer = document.querySelector("#reviewer").value.trim();
  const comment = document.querySelector("#review-comment").value.trim();
  if (!reviewer) {
    reviewState.textContent = "Reviewer is required.";
    document.querySelector("#reviewer").focus();
    return;
  }
  approveReviewButton.disabled = true;
  rejectReviewButton.disabled = true;
  reviewState.textContent = `${decision === "approve" ? "Approving" : "Rejecting"} protected action…`;
  try {
    const { body } = await jsonRequest(`${currentLocation}/reviews`, {
      method: "POST",
      headers: requestHeaders(),
      body: JSON.stringify({ decision, reviewer, comment: comment || null }),
    });
    renderRun(body);
    await loadHistory();
    if (decision === "approve") {
      pollGeneration += 1;
      pollState.textContent = "Approval persisted; resuming the original idempotent action…";
      pollRun(pollGeneration);
    } else {
      pollState.textContent = "Protected action rejected; the run is cancelled without execution.";
    }
  } catch (error) {
    reviewState.textContent = `Review failed: ${error.message}`;
    approveReviewButton.disabled = false;
    rejectReviewButton.disabled = false;
  }
}

approveReviewButton.addEventListener("click", () => submitReview("approve"));
rejectReviewButton.addEventListener("click", () => submitReview("reject"));

followUpButton.addEventListener("click", () => {
  if (!selectedDetail) return;
  const previousObjective = selectedDetail.run.objective.slice(0, 1200);
  const previousResult = pretty(selectedDetail.run.final_result || { status: selectedDetail.run.status }).slice(0, 1400);
  document.querySelector("#scenario").value = "custom";
  const objective = document.querySelector("#objective");
  objective.value = `Continue from durable run ${selectedDetail.run.id}.\nPrevious objective: ${previousObjective}\nPrevious safe result: ${previousResult}\n\nFollow-up request: `;
  objective.focus();
  objective.setSelectionRange(objective.value.length, objective.value.length);
  objective.scrollIntoView({ behavior: "smooth", block: "center" });
});

document.querySelector("#refresh-history").addEventListener("click", () => loadHistory());
document.querySelector("#refresh-health").addEventListener("click", loadHealth);
historyStatus.addEventListener("change", () => loadHistory());
loadMoreRunsButton.addEventListener("click", () => loadHistory({ append: true }));

setRunStatus("idle");
loadProfiles();
loadHistory();
loadHealth();
