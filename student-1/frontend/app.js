import {
  API_BASE,
  ACTIVE_RUN_STATES,
  actionAvailability,
  collection,
  coverageRows,
  entity,
  formatBytes,
  formatDate,
  formatNumber,
  humanise,
  newRequestId,
  nextPollDelay,
  parseJsonField,
  queryString,
  requestJson,
  stateLabel,
  statusTone,
} from "./core.js";

const view = document.querySelector("#view");
const liveRegion = document.querySelector("#live-region");
const serviceState = document.querySelector("#service-state");
const sidebar = document.querySelector("#primary-nav");
const navToggle = document.querySelector("#nav-toggle");
const entityDialog = document.querySelector("#entity-dialog");
const entityForm = document.querySelector("#entity-form");
const actionDialog = document.querySelector("#action-dialog");
const actionForm = document.querySelector("#action-form");
const toast = document.querySelector("#toast");

const state = {
  generation: 0,
  pollTimer: null,
  lastRunStatus: "",
  selectedProperty: null,
  propertyResults: [],
  requests: new Map(),
};

const ROUTES = new Set(["overview", "sources", "jobs", "runs", "releases", "quality", "artifacts", "coverage", "properties", "ai"]);
const RUN_FILTERS = ["", "requested", "queued", "running", "succeeded", "failed", "cancelled", "interrupted"];

function el(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = String(text);
  return node;
}

function append(parent, ...children) {
  for (const child of children.flat()) if (child !== null && child !== undefined) parent.append(child);
  return parent;
}

function link(label, hash, className = "text-button") {
  const node = el("a", className, label);
  node.href = hash;
  return node;
}

function button(label, className = "button secondary", handler = null) {
  const node = el("button", className, label);
  node.type = "button";
  if (handler) node.addEventListener("click", handler);
  return node;
}

function announce(message) {
  liveRegion.textContent = "";
  requestAnimationFrame(() => { liveRegion.textContent = message; });
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => { toast.hidden = true; }, 4500);
  announce(message);
}

function routeParts() {
  const raw = location.hash.replace(/^#/, "") || "overview";
  const path = raw.split("?")[0];
  const [candidate, id, action] = path.split("/").map(decodeURIComponent);
  return { route: ROUTES.has(candidate) ? candidate : "overview", id: id || "", action: action || "" };
}

function setActiveNavigation(route) {
  for (const item of document.querySelectorAll("[data-route]")) {
    if (item.dataset.route === route) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  sidebar.classList.remove("open");
  navToggle.setAttribute("aria-expanded", "false");
}

function clearView() {
  view.replaceChildren();
}

function pageHeading(kicker, title, description, actions = []) {
  const heading = el("header", "page-heading");
  const copy = el("div");
  append(copy, el("p", "eyebrow", kicker), el("h1", "", title), el("p", "lede", description));
  append(heading, copy);
  if (actions.length) {
    const controls = el("div", "heading-actions");
    append(controls, actions);
    append(heading, controls);
  }
  return heading;
}

function panel(title, subtitle = "", body = null, action = null) {
  const section = el("section", "panel");
  const heading = el("div", "panel-heading");
  const copy = el("div");
  append(copy, el("h2", "", title));
  if (subtitle) append(copy, el("p", "", subtitle));
  append(heading, copy, action);
  append(section, heading);
  if (body) {
    if (!body.classList.contains("table-wrap")) body.classList.add("panel-body");
    append(section, body);
  }
  return section;
}

function badge(status) {
  const display = stateLabel(status);
  const node = el("span", `badge ${display.tone}`);
  append(node, el("span", "symbol", display.symbol), document.createTextNode(display.text));
  return node;
}

function loading(title = "Loading evidence") {
  clearView();
  const section = el("section", "loading-state");
  const box = el("div");
  const spinner = el("div", "spinner");
  spinner.setAttribute("aria-hidden", "true");
  append(box, spinner, el("h2", "", title), el("p", "", "Requesting a bounded view from the data platform…"));
  append(section, box);
  append(view, section);
}

function emptyState(title, message, action = null) {
  const section = el("section", "empty-state");
  const box = el("div");
  append(box, el("span", "state-icon", "◇"), el("h2", "", title), el("p", "", message));
  if (action) { action.style.marginTop = ".8rem"; append(box, action); }
  append(section, box);
  return section;
}

function errorState(error, retry) {
  const section = el("section", "error-state");
  const box = el("div");
  append(box, el("span", "state-icon", "!"), el("h2", "", error.status === 503 ? "Service temporarily unavailable" : "We couldn’t load this view"), el("p", "", error.message));
  if (error.requestId) append(box, el("code", "request-id", `Request ID: ${error.requestId}`));
  if (retry) { const retryButton = button("Try again", "button primary", retry); retryButton.style.marginTop = ".9rem"; append(box, retryButton); }
  append(section, box);
  return section;
}

function request(path, options = {}) {
  return requestJson(fetch, path.startsWith("/") ? path : `${API_BASE}/${path}`, options);
}

function makeTable(columns, rows, rowBuilder) {
  const wrap = el("div", "table-wrap");
  const table = el("table");
  const caption = el("caption", "visually-hidden", "Data results");
  const thead = el("thead");
  const headingRow = el("tr");
  for (const column of columns) {
    const cell = el("th", column.className || "", column.label);
    cell.scope = "col";
    append(headingRow, cell);
  }
  append(thead, headingRow);
  const tbody = el("tbody");
  rows.forEach((item, index) => append(tbody, rowBuilder(item, index)));
  append(table, caption, thead, tbody);
  append(wrap, table);
  return wrap;
}

function cell(content, className = "") {
  const node = el("td", className);
  append(node, content instanceof Node ? content : document.createTextNode(String(content ?? "—")));
  return node;
}

function primaryCell(primary, secondary = "") {
  const node = el("span", "primary-cell", primary || "Untitled");
  if (secondary) append(node, el("span", "sub-cell", secondary));
  return node;
}

function technicalDetails(data, label = "Technical details") {
  const details = el("details", "technical");
  append(details, el("summary", "", label), el("pre", "json", JSON.stringify(data, null, 2)));
  return details;
}

function detailList(entries) {
  const list = el("dl", "detail-list");
  for (const [label, value] of entries) {
    const item = el("div");
    append(item, el("dt", "", label));
    const dd = el("dd");
    append(dd, value instanceof Node ? value : document.createTextNode(String(value ?? "Not recorded")));
    append(item, dd);
    append(list, item);
  }
  return list;
}

function filterToolbar({ search = "", status = "", statuses = [], placeholder = "Filter results", onApply }) {
  const form = el("form", "toolbar");
  const fields = el("div", "filter-row");
  const searchLabel = el("label", "field");
  append(searchLabel, el("span", "", "Search"));
  const searchInput = el("input");
  searchInput.type = "search";
  searchInput.name = "q";
  searchInput.placeholder = placeholder;
  searchInput.value = search;
  append(searchLabel, searchInput);
  append(fields, searchLabel);
  if (statuses.length) {
    const statusLabel = el("label", "field");
    append(statusLabel, el("span", "", "Status"));
    const select = el("select");
    select.name = "status";
    for (const value of statuses) {
      const option = el("option", "", value ? humanise(value) : "All statuses");
      option.value = value;
      option.selected = value === status;
      append(select, option);
    }
    append(statusLabel, select);
    append(fields, statusLabel);
  }
  append(form, fields, button("Apply filters", "button secondary"));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    onApply(Object.fromEntries(new FormData(form)));
  });
  return form;
}

function formField(definition, value = "") {
  const label = el("label", definition.wide ? "wide" : "");
  const title = el("span", "", definition.label);
  if (definition.help) append(title, document.createTextNode(" "), el("small", "", definition.help));
  let input;
  if (["textarea", "json", "json_array"].includes(definition.type)) input = el("textarea");
  else if (definition.options) {
    input = el("select");
    for (const optionValue of definition.options) {
      const option = el("option", "", humanise(optionValue));
      option.value = optionValue;
      append(input, option);
    }
  } else {
    input = el("input");
    input.type = definition.type || "text";
  }
  input.name = definition.name;
  input.required = Boolean(definition.required);
  if (definition.min !== undefined) input.min = definition.min;
  if (definition.max !== undefined) input.max = definition.max;
  if (definition.type === "json") input.value = JSON.stringify(value || {}, null, 2);
  else if (definition.type === "json_array") input.value = JSON.stringify(value || [], null, 2);
  else input.value = value ?? "";
  append(label, title, input);
  return label;
}

const SOURCE_FIELDS = [
  { name: "name", label: "Source name", required: true },
  { name: "publisher", label: "Publisher", required: true },
  { name: "source_url", label: "Attribution URL", type: "url", required: true, wide: true, help: "Metadata only; acquisition remains allowlisted" },
  { name: "adapter_key", label: "Registered adapter", required: true },
  { name: "cadence", label: "Update cadence", required: true },
  { name: "licence_id", label: "Licence", required: true },
  { name: "licence_url", label: "Licence URL", type: "url", required: true },
  { name: "redistribution_policy", label: "Redistribution policy", required: true, wide: true },
  { name: "target_features", label: "Target features", type: "json_array", wide: true, required: true, help: "JSON list of feature keys" },
  { name: "status", label: "Lifecycle status", options: ["draft", "active", "disabled", "retired"], required: true },
  { name: "notes", label: "Operator notes", type: "textarea", wide: true },
];

const JOB_FIELDS = [
  { name: "source_definition_id", label: "Source ID", required: true, wide: true },
  { name: "name", label: "Job name", required: true },
  { name: "profile_key", label: "Registered profile", required: true },
  { name: "profile_version", label: "Profile version", required: true },
  { name: "adapter_key", label: "Registered adapter", required: true },
  { name: "release_builder_key", label: "Release builder", required: true },
  { name: "import_profile_key", label: "Import profile", required: true },
  { name: "import_profile_version", label: "Import profile version", required: true },
  { name: "target_feature", label: "Target feature", required: true },
  { name: "dataset_id", label: "Dataset ID", required: true },
  { name: "refresh_strategy", label: "Refresh strategy", options: ["full_snapshot", "append_only_partitioned", "partitioned_snapshot", "manual_versioned_import"], required: true },
  { name: "default_run_mode", label: "Default run mode", options: ["full_refresh", "reprocess_cached"], required: true },
  { name: "scope_json", label: "Bounded default scope", type: "json", wide: true },
  { name: "quality_policy_key", label: "Quality policy", required: true },
  { name: "quality_policy_version", label: "Quality policy version", required: true },
  { name: "max_parallelism", label: "Maximum parallel tasks", type: "number", min: 1, required: true },
  { name: "timeout_seconds", label: "Time limit (seconds)", type: "number", min: 1, required: true },
  { name: "max_objects", label: "Object limit", type: "number", min: 1, required: true },
  { name: "max_bytes", label: "Byte limit", type: "number", min: 1, required: true },
  { name: "max_rows", label: "Row limit", type: "number", min: 1, required: true },
  { name: "status", label: "Lifecycle status", options: ["draft", "active", "disabled", "retired"], required: true },
  { name: "schedule_text", label: "Schedule note", wide: true, help: "Descriptive only in Release 0" },
];

async function openEntityDialog(kind, item = null) {
  const isSource = kind === "source";
  const fields = isSource ? SOURCE_FIELDS : JOB_FIELDS;
  document.querySelector("#entity-kicker").textContent = isSource ? "Source definition" : "Job definition";
  document.querySelector("#entity-title").textContent = `${item ? "Edit" : "Create"} ${kind}`;
  const fieldHost = document.querySelector("#entity-fields");
  const fieldValue = (name) => {
    const aliases = {
      adapter_key: item?.adapter?.key,
      import_profile_key: item?.import_profile?.key,
      import_profile_version: item?.import_profile?.version,
      target_feature: item?.target?.feature,
      target_features: item?.target_features_json,
      quality_policy_key: item?.quality_policy,
      max_parallelism: item?.limits?.max_parallelism,
      timeout_seconds: item?.limits?.deadline_seconds,
      max_objects: item?.limits?.max_objects,
      max_bytes: item?.limits?.max_bytes,
      max_rows: item?.limits?.max_rows,
    };
    return item?.[name] ?? aliases[name];
  };
  fieldHost.replaceChildren(...fields.map((definition) => formField(definition, fieldValue(definition.name))));
  document.querySelector("#entity-error").textContent = "";
  entityDialog.returnValue = "";
  entityDialog.showModal();
  entityDialog.querySelector("input, select, textarea")?.focus();

  const returnValue = await new Promise((resolve) => {
    const closed = () => { entityDialog.removeEventListener("close", closed); resolve(entityDialog.returnValue); };
    entityDialog.addEventListener("close", closed);
  });
  if (returnValue !== "save") return;
  const data = Object.fromEntries(new FormData(entityForm));
  try {
    for (const definition of fields.filter((field) => field.type === "json")) data[definition.name] = parseJsonField(data[definition.name], definition.label);
    for (const definition of fields.filter((field) => field.type === "json_array")) {
      try {
        const parsed = JSON.parse(data[definition.name] || "[]");
        if (!Array.isArray(parsed) || (definition.required && parsed.length === 0) || parsed.some((value) => typeof value !== "string")) throw new Error();
        data[definition.name] = parsed;
      } catch { throw new Error(`${definition.label} must be a JSON list of text values.`); }
    }
    for (const definition of fields.filter((field) => field.type === "number")) data[definition.name] = Number(data[definition.name]);
    if (item?.version !== undefined) data.version = item.version;
    const path = isSource ? "sources" : "jobs";
    const method = item ? "PUT" : "POST";
    const result = await request(`${path}${item ? `/${encodeURIComponent(item.id)}` : ""}`, { method, body: data });
    showToast(`${humanise(kind)} ${item ? "updated" : "created"}. Request ID ${result.requestId}`);
    await renderRoute();
  } catch (error) {
    showToast(`${error.message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`);
  }
}

function confirmAction({ title, description, label = "Confirm", tone = "danger", extra = null }) {
  document.querySelector("#action-title").textContent = title;
  document.querySelector("#action-description").textContent = description;
  document.querySelector("#action-error").textContent = "";
  const host = document.querySelector("#action-extra");
  host.replaceChildren();
  if (extra) append(host, extra);
  const confirm = document.querySelector("#action-confirm");
  confirm.textContent = label;
  confirm.className = `button ${tone}`;
  actionDialog.returnValue = "";
  actionDialog.showModal();
  return new Promise((resolve) => {
    const closed = () => { actionDialog.removeEventListener("close", closed); resolve(actionDialog.returnValue === "confirm"); };
    actionDialog.addEventListener("close", closed);
  });
}

async function mutate(path, { method = "POST", body = {}, success = "Action completed" } = {}) {
  const idempotencyKey = body?.idempotency_key || newRequestId();
  const result = await request(path, {
    method,
    headers: { "Idempotency-Key": idempotencyKey },
    body,
  });
  showToast(`${success}. Request ID ${result.requestId}`);
  return result.body;
}

async function renderOverview() {
  loading("Loading operations overview");
  const results = await Promise.allSettled([
    request("sources?limit=100"), request("ingestion-runs?limit=25"), request("dataset-releases?limit=100"), request("overview"),
  ]);
  const sources = results[0].status === "fulfilled" ? collection(results[0].value.body) : [];
  const runs = results[1].status === "fulfilled" ? collection(results[1].value.body) : [];
  const releases = results[2].status === "fulfilled" ? collection(results[2].value.body) : [];
  const coverage = releases.filter((release) => release.status === "accepted").map((release) => ({
    dataset: release.dataset_id,
    locality: release.coverage_json?.locality || release.coverage_json?.state || "NSW",
    status: release.coverage_json?.complete === false ? "partial" : "accepted",
  }));
  const failures = results.filter((result) => result.status === "rejected");
  clearView();
  append(view, pageHeading("Data operations", "Know what is live, fresh and trustworthy", "Monitor acquisition, quality and publication without confusing service health with data readiness.", [button("Plan a run", "button primary", () => { location.hash = "#jobs"; })]));
  if (failures.length) append(view, el("div", "notice warning", `${failures.length} overview feed${failures.length === 1 ? " is" : "s are"} unavailable. Available evidence is shown below; direct property search remains independent.`));
  const active = runs.filter((run) => ACTIVE_RUN_STATES.has(String(run.status).toLowerCase())).length;
  const failed = runs.filter((run) => String(run.status).toLowerCase() === "failed").length;
  const stale = releases.filter((release) => ["stale", "expired"].includes(String(release.freshness_status || release.status).toLowerCase())).length;
  const accepted = releases.filter((release) => String(release.status).toLowerCase() === "accepted").length;
  const stats = el("section", "stat-grid", "");
  for (const [label, value, note, tone] of [
    ["Active runs", active, "Currently progressing", "info"],
    ["Failed runs", failed, "Requires evidence review", failed ? "negative" : "neutral"],
    ["Stale releases", stale, "Freshness, not service health", stale ? "warning" : "neutral"],
    ["Accepted releases", accepted, "Currently available to consumers", "positive"],
  ]) {
    const card = el("article", `stat-card ${tone}`);
    append(card, el("span", "stat-label", label), el("strong", "stat-value", value), el("span", "stat-note", note));
    append(stats, card);
  }
  append(view, stats);
  const grid = el("div", "dashboard-grid");
  const recentBody = runs.length ? makeTable(
    [{ label: "Run" }, { label: "Mode" }, { label: "Status" }, { label: "Requested" }], runs.slice(0, 8),
    (run) => {
      const row = el("tr");
      append(row, cell(link(run.job_name || `Run ${String(run.id).slice(0, 8)}`, `#runs/${run.id}`), "primary-cell"), cell(humanise(run.run_mode)), cell(badge(run.status)), cell(formatDate(run.requested_at || run.created_at)));
      return row;
    },
  ) : emptyState("No runs yet", "Activate a bounded job, preview its plan and launch the first fixture run.", link("Open jobs", "#jobs", "button secondary"));
  const freshness = el("div", "stack");
  const sourceBody = el("div");
  if (!sources.length) append(sourceBody, el("p", "", "No source definitions are currently available."));
  for (const source of sources.slice(0, 6)) {
    const item = el("div", "coverage-card");
    const release = releases.find((candidate) => candidate.source_definition_id === source.id && candidate.status === "accepted");
    item.classList.add(statusTone(release?.freshness_status || (release ? "accepted" : "unavailable")));
    append(item, el("strong", "", source.name), el("span", "", release ? `${release.release_version} · ${formatDate(release.accepted_at)}` : "No accepted release"));
    append(sourceBody, item);
  }
  const coverageBody = el("div", "coverage-grid");
  for (const item of coverage.slice(0, 6)) {
    const card = el("div", `coverage-card ${statusTone(item.status)}`);
    append(card, el("strong", "", item.locality || item.area || "NSW"), el("span", "", `${item.dataset || item.dataset_id || "Dataset"} · ${humanise(item.status)}`));
    append(coverageBody, card);
  }
  if (!coverage.length) append(coverageBody, el("p", "", "Coverage evidence is not available from this deployment."));
  append(freshness, panel("Source freshness", "Accepted evidence by source", sourceBody), panel("Supported coverage", "Geography and dataset availability", coverageBody));
  append(grid, panel("Recent ingestion runs", "Durable execution history", recentBody, link("View all", "#runs")), freshness);
  append(view, grid);
  view.setAttribute("aria-busy", "false");
}

async function renderEntityList(kind) {
  const isSource = kind === "sources";
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const filters = { q: params.get("q") || "", status: params.get("status") || "" };
  loading(`Loading ${kind}`);
  try {
    const { body } = await request(`${kind}${queryString({ ...filters, limit: 100 })}`);
    const items = collection(body);
    clearView();
    append(view, pageHeading("Data control", isSource ? "Source definitions" : "Ingestion jobs", isSource ? "Manage attributed, allowlisted data sources and their operating status." : "Configure bounded, reusable ingestion without exposing commands, code paths or database details.", [button(`Create ${isSource ? "source" : "job"}`, "button primary", () => openEntityDialog(isSource ? "source" : "job"))]));
    append(view, filterToolbar({ ...filters, statuses: ["", "draft", "active", "disabled", "retired"], placeholder: isSource ? "Source or publisher" : "Job or dataset", onApply: (values) => { location.hash = `#${kind}${queryString(values)}`; renderRoute(); } }));
    if (!items.length) {
      append(view, emptyState(`No ${kind} found`, filters.q || filters.status ? "Try clearing the current filters." : `Create the first ${isSource ? "allowlisted source" : "bounded ingestion job"}.`));
      return;
    }
    const columns = isSource
      ? [{ label: "Source" }, { label: "Publisher" }, { label: "Adapter" }, { label: "Cadence" }, { label: "Status" }, { label: "Actions" }]
      : [{ label: "Job" }, { label: "Dataset / target" }, { label: "Strategy" }, { label: "Limits" }, { label: "Status" }, { label: "Actions" }];
    const table = makeTable(columns, items, (item) => {
      const row = el("tr");
      const actions = el("div", "button-row");
      append(actions, link("View", `#${kind}/${item.id}`, "button secondary small"), button("Edit", "button secondary small", () => openEntityDialog(isSource ? "source" : "job", item)), button("Delete", "button small danger", async () => {
        const confirmed = await confirmAction({ title: `Delete ${item.name}?`, description: "Only unused draft/test definitions can be deleted. Existing provenance remains protected.", label: "Delete definition" });
        if (!confirmed) return;
        try { await mutate(`${kind}/${item.id}`, { method: "DELETE", body: item.version === undefined ? undefined : { version: item.version }, success: `${humanise(isSource ? "source" : "job")} deleted` }); await renderRoute(); } catch (error) { showToast(`${error.message} Request ID ${error.requestId}`); }
      }));
      if (isSource) append(row, cell(primaryCell(item.name, item.id)), cell(item.publisher), cell(item.adapter_key, "mono"), cell(item.cadence), cell(badge(item.status)), cell(actions, "actions-cell"));
      else append(row, cell(primaryCell(item.name, item.profile_key)), cell(primaryCell(item.dataset_id || item.target?.contract, item.target_feature || item.target?.feature)), cell(humanise(item.refresh_strategy)), cell(`${formatNumber(item.max_rows ?? item.limits?.max_rows)} rows`, "numeric"), cell(badge(item.status)), cell(actions, "actions-cell"));
      return row;
    });
    append(view, panel(`${items.length} ${kind}`, "Bounded to 100 results", table));
  } catch (error) { clearView(); append(view, errorState(error, renderRoute)); }
}

async function renderEntityDetail(kind, id) {
  const singular = kind === "sources" ? "source" : "job";
  loading(`Loading ${singular}`);
  try {
    const result = await request(`${kind}/${encodeURIComponent(id)}`);
    const item = entity(result.body, singular);
    let capabilities = null;
    if (kind === "jobs") {
      try { capabilities = (await request(`jobs/${encodeURIComponent(id)}/capabilities`)).body; } catch { /* optional evidence */ }
    }
    clearView();
    const actions = [button("Edit", "button secondary", () => openEntityDialog(singular, item))];
    if (kind === "jobs") actions.unshift(button("Plan run", "button primary", () => openPlanDialog(item, capabilities)));
    append(view, pageHeading(kind === "sources" ? "Source definition" : "Job definition", item.name || humanise(singular), `${kind === "sources" ? item.publisher || "Attributed source" : item.dataset_id || item.target?.contract || "Bounded ingestion"} · Version ${item.version ?? "—"}`, actions));
    const left = el("div");
    const entries = kind === "sources" ? [
      ["Status", badge(item.status)], ["Publisher", item.publisher], ["Update cadence", item.cadence], ["Registered adapter", item.adapter_key], ["Licence", item.licence_id], ["Redistribution", item.redistribution_policy], ["Attribution URL", item.source_url], ["Updated", formatDate(item.updated_at)],
    ] : [
      ["Status", badge(item.status)], ["Dataset contract", item.dataset_id || item.target?.contract], ["Target feature", item.target_feature || item.target?.feature], ["Profile", item.profile_key], ["Refresh strategy", humanise(item.refresh_strategy)], ["Default mode", humanise(item.default_run_mode)], ["Quality policy", item.quality_policy_key || item.quality_policy], ["Updated", formatDate(item.updated_at)],
    ];
    append(left, detailList(entries), technicalDetails(item));
    const right = el("div", "stack");
    if (kind === "sources") {
      const notice = el("div", "notice", "The attribution URL is descriptive. Acquisition is constrained by the registered adapter’s host and path allowlist.");
      append(right, panel("Safety boundary", "Source changes cannot create arbitrary requests", notice));
    } else {
      const limits = el("div", "metric-strip");
      for (const [label, value] of [["Rows", formatNumber(item.max_rows ?? item.limits?.max_rows)], ["Bytes", formatBytes(item.max_bytes ?? item.limits?.max_bytes)], ["Objects", formatNumber(item.max_objects ?? item.limits?.max_objects)], ["Time", `${formatNumber(item.timeout_seconds ?? item.limits?.deadline_seconds)}s`]]) {
        const metric = el("div"); append(metric, el("span", "", label), el("strong", "", value)); append(limits, metric);
      }
      append(right, panel("Hard execution limits", "Validated before launch", limits));
      if (capabilities) append(right, panel("Registered capabilities", "Resolved adapter and builder behavior", technicalDetails(capabilities, "Inspect capability contract")));
    }
    const layout = el("div", "detail-layout");
    append(layout, panel(kind === "sources" ? "Source metadata" : "Resolved configuration", "Visible operator-safe fields", left), right);
    append(view, layout);
  } catch (error) { clearView(); append(view, errorState(error, renderRoute)); }
}

async function openPlanDialog(job, capabilities = null) {
  const wrapper = el("div", "stack");
  const modeLabel = el("label", "field");
  append(modeLabel, el("span", "", "Run mode"));
  const mode = el("select"); mode.name = "run_mode";
  for (const value of capabilities?.supported_modes || capabilities?.run_modes || ["full_refresh", "reprocess_cached"]) { const option = el("option", "", humanise(value)); option.value = value; option.selected = value === job.default_run_mode; append(mode, option); }
  append(modeLabel, mode);
  append(wrapper, modeLabel);
  const scopeLabel = el("label", "field");
  append(scopeLabel, el("span", "", "Bounded scope (JSON object)"));
  const scope = el("textarea"); scope.value = JSON.stringify(job.scope_json || {}, null, 2); append(scopeLabel, scope); append(wrapper, scopeLabel);
  const preview = button("Preview deterministic plan", "button secondary");
  const evidence = el("div");
  append(wrapper, preview, evidence);
  preview.addEventListener("click", async () => {
    preview.disabled = true; evidence.replaceChildren(el("p", "", "Validating limits and proposed work…"));
    try {
      const payload = { run_mode: mode.value, scope: parseJsonField(scope.value, "Scope") };
      const result = await request(`jobs/${job.id}/plans`, { method: "POST", body: payload });
      evidence.replaceChildren(el("div", "notice", "Plan validated. Review task, cache/network work and limits before launch."), technicalDetails(result.body, "Plan evidence"));
    } catch (error) { evidence.replaceChildren(el("div", "notice negative", `${error.message} Request ID ${error.requestId}`)); }
    finally { preview.disabled = false; }
  });
  const confirmed = await confirmAction({ title: `Launch ${job.name}?`, description: "A durable run will be created with a new idempotency key. The runner processes it independently.", label: "Launch run", tone: "primary", extra: wrapper });
  if (!confirmed) return;
  try {
    const idempotencyKey = newRequestId();
    const body = await mutate(`jobs/${job.id}/runs`, { body: { run_mode: mode.value, scope: parseJsonField(scope.value, "Scope"), idempotency_key: idempotencyKey }, success: "Run requested" });
    const run = entity(body, "run");
    location.hash = `#runs/${run.id}`;
  } catch (error) { showToast(`${error.message} Request ID ${error.requestId}`); }
}

async function renderRuns() {
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const filters = { q: params.get("q") || "", status: params.get("status") || "" };
  loading("Loading run history");
  try {
    const { body } = await request(`ingestion-runs${queryString({ ...filters, limit: 100 })}`);
    const runs = collection(body);
    clearView();
    append(view, pageHeading("Durable orchestration", "Ingestion runs", "Inspect task attempts, checkpoint movement and accepted watermarks. Recovery always creates explicit evidence."));
    append(view, filterToolbar({ ...filters, statuses: RUN_FILTERS, placeholder: "Run, job or request ID", onApply: (values) => { location.hash = `#runs${queryString(values)}`; renderRoute(); } }));
    if (!runs.length) { append(view, emptyState("No runs found", "Launch a validated job plan or adjust the current filters.", link("Open jobs", "#jobs", "button primary"))); return; }
    const table = makeTable([{ label: "Run" }, { label: "Mode" }, { label: "Progress" }, { label: "Rows accepted" }, { label: "Requested" }, { label: "Request ID" }], runs, (run) => {
      const row = el("tr");
      append(row, cell(primaryCell(run.job_name || `Run ${String(run.id).slice(0, 8)}`, run.id)), cell(humanise(run.run_mode)), cell(badge(run.status)), cell(formatNumber(run.rows_accepted), "numeric"), cell(formatDate(run.requested_at)), cell(run.request_id || "—", "mono"));
      row.tabIndex = 0; row.setAttribute("aria-label", `Open run ${run.id}`); row.addEventListener("click", () => { location.hash = `#runs/${run.id}`; }); row.addEventListener("keydown", (event) => { if (event.key === "Enter") location.hash = `#runs/${run.id}`; });
      return row;
    });
    append(view, panel(`${runs.length} runs`, "Newest evidence first", table));
  } catch (error) { clearView(); append(view, errorState(error, renderRoute)); }
}

function runTimeline(tasks) {
  const list = el("ol", "timeline");
  if (!tasks.length) append(list, el("li", "", "No task ledger is available yet."));
  for (const task of tasks) {
    const item = el("li");
    const tone = statusTone(task.status);
    const marker = el("span", `timeline-marker ${tone}`, stateLabel(task.status).symbol);
    const detail = el("div");
    append(detail, el("h3", "", `${humanise(task.stage)} · ${task.logical_key || "Task"}`), el("p", "", `${humanise(task.status)} · attempt ${task.attempt_number ?? 1} · ${formatNumber(task.rows_out)} rows out`));
    if (task.error_json) append(detail, technicalDetails(task.error_json, "Safe failure evidence"));
    append(item, marker, detail);
    append(list, item);
  }
  return list;
}

async function renderRunDetail(id, { polling = false } = {}) {
  const scrollTop = polling ? window.scrollY : 0;
  if (!polling) loading("Loading run evidence");
  try {
    const [detailResult, tasksResult, qualityResult, artifactsResult] = await Promise.all([
      request(`ingestion-runs/${id}`), request(`ingestion-runs/${id}/tasks?limit=100`), request(`ingestion-runs/${id}/quality-results?limit=100`), request(`ingestion-runs/${id}/artifacts?limit=100`),
    ]);
    const run = entity(detailResult.body, "run");
    const tasks = collection(tasksResult.body);
    const quality = collection(qualityResult.body);
    const artifacts = collection(artifactsResult.body);
    clearView();
    const availability = actionAvailability(run.status);
    const actions = [];
    const runAction = (key, label, description, tone = "secondary") => actions.push(button(label, `button ${tone}`, async () => {
      const confirmed = await confirmAction({ title: `${label} this run?`, description, label, tone: tone === "secondary" ? "primary" : tone });
      if (!confirmed) return;
      try { const created = await mutate(`ingestion-runs/${id}/${key}`, { success: `${label} requested` }); const child = entity(created, "run"); if (child?.id && child.id !== id) location.hash = `#runs/${child.id}`; else renderRunDetail(id); } catch (error) { showToast(`${error.message} Request ID ${error.requestId}`); }
    }));
    if (availability.resume) runAction("resume", "Resume", "Continue the existing non-terminal run from durable task evidence.");
    if (availability.retry) runAction("retry", "Retry failed", "Create a linked child run containing only eligible failed work.");
    if (availability.reprocess) runAction("reprocess-cached", "Reprocess cached", "Create a linked child run using verified cached artifacts and current transforms.");
    if (availability.cancel) runAction("cancel", "Cancel", "Request cooperative cancellation. Completed evidence will remain available.", "danger");
    if (availability.diagnose) actions.push(button("Diagnose with AI", "button primary", () => { location.hash = `#ai/${id}`; }));
    append(view, pageHeading("Run evidence", run.job_name || `Run ${String(id).slice(0, 8)}`, `${humanise(run.run_mode)} · ${formatDate(run.requested_at)}`, actions));
    if (run.error_json) append(view, el("div", "notice negative", `${run.error_json.message || run.error_json.detail || "The run recorded a classified failure."} The previously accepted release remains unchanged.`));
    const metrics = el("div", "metric-strip");
    for (const [label, value] of [["Discovered", formatNumber(run.rows_discovered)], ["Staged", formatNumber(run.rows_staged)], ["Accepted", formatNumber(run.rows_accepted)], ["Rejected", formatNumber(run.rows_rejected)]]) { const metric = el("div"); append(metric, el("span", "", label), el("strong", "", value)); append(metrics, metric); }
    append(view, metrics);
    const grid = el("div", "dashboard-grid");
    const runBody = el("div");
    append(runBody, runTimeline(tasks));
    const evidence = el("div", "stack");
    append(evidence,
      panel("Run state", "Control-plane projection", detailList([["Status", badge(run.status)], ["Heartbeat", formatDate(run.heartbeat_at)], ["Attempt", run.attempt_number], ["Parent run", run.parent_run_id ? link(String(run.parent_run_id), `#runs/${run.parent_run_id}`) : "None"], ["Request ID", el("code", "mono", run.request_id || detailResult.requestId)], ["Finished", formatDate(run.finished_at)]])),
      panel("Checkpoints and watermark", "Candidate progress never advances accepted data", detailList([["Input checkpoint", JSON.stringify(run.input_checkpoint_json || {})], ["Candidate checkpoint", JSON.stringify(run.output_checkpoint_json || {})], ["Accepted watermark", JSON.stringify(run.accepted_watermark_json || {})]])),
      panel("Linked evidence", "Safe metadata only", detailList([["Quality checks", link(`${quality.length} results`, `#quality/${id}`)], ["Artifacts", link(`${artifacts.length} records`, `#artifacts/${id}`)]])),
    );
    append(grid, panel("Stage and task timeline", `${tasks.length} durable task records`, runBody), evidence);
    append(view, grid);
    append(view, panel("Complete run projection", "Expandable, structured evidence for audit", technicalDetails(detailResult.body)));
    if (polling) window.scrollTo({ top: scrollTop });
    const statusChanged = state.lastRunStatus && state.lastRunStatus !== run.status;
    if (statusChanged) announce(`Run status changed to ${humanise(run.status)}.`);
    state.lastRunStatus = run.status;
    scheduleRunPoll(id, run.status);
  } catch (error) {
    if (!polling) { clearView(); append(view, errorState(error, () => renderRunDetail(id))); }
    else scheduleRunPoll(id, state.lastRunStatus, 1);
  }
}

function scheduleRunPoll(id, status, failures = 0) {
  clearTimeout(state.pollTimer);
  const delay = nextPollDelay(status, failures, document.hidden);
  if (delay === null) return;
  const generation = state.generation;
  state.pollTimer = setTimeout(() => {
    const current = routeParts();
    if (state.generation === generation && current.route === "runs" && current.id === id) renderRunDetail(id, { polling: true });
  }, delay);
}

async function renderReleases(id = "") {
  loading("Loading release evidence");
  try {
    if (id) return await renderReleaseDetail(id);
    const { body } = await request("dataset-releases?limit=100");
    const releases = collection(body);
    clearView();
    append(view, pageHeading("Publication control", "Dataset releases", "Compare candidate and accepted evidence, then publish only after quality and human review."));
    if (!releases.length) { append(view, emptyState("No dataset releases", "Completed ingestion runs can create isolated candidate releases.")); return; }
    const table = makeTable([{ label: "Dataset / release" }, { label: "Target" }, { label: "Records" }, { label: "Status" }, { label: "Accepted" }, { label: "Checksum" }], releases, (release) => {
      const row = el("tr");
      append(row, cell(link(release.dataset_id || "Dataset", `#releases/${release.id}`), "primary-cell"), cell(release.target_feature), cell(formatNumber(release.record_count), "numeric"), cell(badge(release.status)), cell(formatDate(release.accepted_at)), cell(String(release.content_sha256 || "—").slice(0, 12), "mono"));
      return row;
    });
    append(view, panel(`${releases.length} releases`, "Candidates are isolated from accepted generations", table));
  } catch (error) { if (!id) { clearView(); append(view, errorState(error, renderRoute)); } else throw error; }
}

async function renderReleaseDetail(id) {
  const { body, requestId } = await request(`dataset-releases/${id}`);
  const release = entity(body, "release");
  const receipts = body.receipts || [];
  let manifest = release.manifest_json || body.manifest;
  if (!manifest) { try { manifest = (await request(`dataset-releases/${id}/manifest`)).body; } catch { manifest = null; } }
  clearView();
  const actions = [];
  if (["validated", "candidate"].includes(release.status)) actions.push(button("Submit for review", "button secondary", async () => {
    const comment = el("textarea"); comment.placeholder = "Reviewer context (required)";
    const ok = await confirmAction({ title: "Submit candidate for review?", description: "Blocking failures cannot be bypassed. The candidate remains isolated until publication succeeds.", label: "Submit review", tone: "primary", extra: comment });
    if (ok && comment.value.trim()) { await mutate(`dataset-releases/${id}/submit-review`, { body: { version: release.version, comment: comment.value.trim() }, success: "Candidate submitted" }); renderRoute(); }
    else if (ok) showToast("A review comment is required.");
  }));
  if (["review", "review_required", "awaiting_review"].includes(release.status)) actions.push(button("Publish", "button primary", async () => {
    const comment = el("textarea"); comment.placeholder = "Approval evidence (required)";
    const ok = await confirmAction({ title: "Publish this release?", description: "This protected action starts the idempotent consumer import handshake. The prior accepted release stays live unless the consumer accepts this release.", label: "Publish release", tone: "primary", extra: comment });
    if (ok && comment.value.trim()) { await mutate(`dataset-releases/${id}/publish`, { body: { approved: true, version: release.version, comment: comment.value.trim() }, success: "Publication requested" }); renderRoute(); }
    else if (ok) showToast("Approval evidence is required.");
  }));
  if (["candidate", "review", "review_required", "awaiting_review"].includes(release.status)) actions.push(button("Reject", "button danger", async () => { const reason = el("textarea"); reason.placeholder = "Reason for rejection (required)"; const ok = await confirmAction({ title: "Reject this candidate?", description: "The decision and reason become durable evidence. Accepted data is unchanged.", label: "Reject candidate", extra: reason }); if (ok && reason.value.trim()) { await mutate(`dataset-releases/${id}/reject`, { body: { reason: reason.value.trim(), version: release.version }, success: "Candidate rejected" }); renderRoute(); } }));
  actions.push(button("Diagnose with AI", "button secondary", () => { location.hash = `#ai/release:${id}`; }));
  append(view, pageHeading("Dataset release", `${release.dataset_id} ${release.release_version}`, `${release.target_feature} · ${formatNumber(release.record_count)} records`, actions));
  if (!["accepted", "superseded"].includes(release.status)) append(view, el("div", "notice warning", "This is candidate evidence. The previously accepted release remains live until the publication handshake succeeds."));
  const layout = el("div", "detail-layout");
  const releaseBody = el("div");
  append(releaseBody, detailList([["Status", badge(release.status)], ["Schema", release.schema_version], ["Content hash", el("code", "mono", release.content_sha256)], ["Created", formatDate(release.created_at)], ["Accepted", formatDate(release.accepted_at)], ["Supersedes", release.supersedes_release_id ? link(release.supersedes_release_id, `#releases/${release.supersedes_release_id}`) : "None"]]), technicalDetails(release));
  const side = el("div", "stack");
  append(side, panel("Manifest", "Bounded reproducibility evidence", manifest ? technicalDetails(manifest, "Inspect manifest") : el("p", "", "Manifest unavailable.")));
  const receiptBody = el("div");
  if (!receipts.length) append(receiptBody, el("p", "", "No consumer publication receipts recorded."));
  for (const receipt of receipts) append(receiptBody, detailList([["Target", receipt.target_feature], ["Status", badge(receipt.status)], ["Rows accepted", formatNumber(receipt.rows_accepted)], ["Request ID", el("code", "mono", receipt.request_id || requestId)]]));
  append(side, panel("Publication receipts", "Consumer-owned import outcomes", receiptBody));
  append(layout, panel("Release evidence", "Candidate and accepted state remain distinct", releaseBody), side);
  append(view, layout);
}

async function resolveRunScopedEvidence(kind, id) {
  let runId = id;
  if (!runId) {
    const result = await request("ingestion-runs?limit=1");
    runId = collection(result.body)[0]?.id;
  }
  if (!runId) return { runId: "", items: [] };
  const suffix = kind === "quality" ? "quality-results" : "artifacts";
  const result = await request(`ingestion-runs/${runId}/${suffix}?limit=100`);
  return { runId, items: collection(result.body), requestId: result.requestId };
}

async function renderEvidenceExplorer(kind, id) {
  loading(`Loading ${kind} evidence`);
  try {
    const { runId, items } = await resolveRunScopedEvidence(kind, id);
    clearView();
    append(view, pageHeading("Evidence explorer", kind === "quality" ? "Quality results" : "Artifacts", kind === "quality" ? "Filter rule outcomes without exposing unbounded source records." : "Inspect hashes, sizes, retention and lineage without exposing storage paths or restricted data."));
    if (runId) append(view, el("div", "notice", `Showing bounded evidence for run ${runId}. Select another run from the Runs screen to inspect its evidence.`));
    if (!items.length) { append(view, emptyState(`No ${kind} evidence`, runId ? "This run has not recorded evidence of this type." : "No ingestion runs are available yet.")); return; }
    const table = kind === "quality" ? makeTable(
      [{ label: "Rule" }, { label: "Dimension" }, { label: "Severity" }, { label: "Outcome" }, { label: "Message" }, { label: "Evidence" }], items,
      (item) => { const row = el("tr"); append(row, cell(primaryCell(item.rule_key, item.rule_version)), cell(humanise(item.dimension)), cell(badge(item.severity)), cell(badge(item.status)), cell(item.message), cell(technicalDetails({ observed: item.observed_value_json, expected: item.expected_value_json, sample: item.sample_json }, "Inspect"))); return row; },
    ) : makeTable(
      [{ label: "Artifact" }, { label: "Type" }, { label: "Size" }, { label: "SHA-256" }, { label: "Retention" }, { label: "Created" }], items,
      (item) => { const row = el("tr"); append(row, cell(primaryCell(item.logical_key, item.id)), cell(`${item.artifact_kind} · ${item.media_type}`), cell(formatBytes(item.bytes), "numeric"), cell(String(item.content_sha256).slice(0, 16), "mono"), cell(humanise(item.retention_class)), cell(formatDate(item.created_at))); return row; },
    );
    append(view, panel(`${items.length} ${kind === "quality" ? "checks" : "artifact records"}`, "Safe, bounded metadata", table));
  } catch (error) { clearView(); append(view, errorState(error, renderRoute)); }
}

async function renderCoverage() {
  loading("Loading coverage matrix");
  try {
    const result = await request("dataset-releases?limit=100");
    const rows = [];
    for (const release of collection(result.body).filter((item) => ["accepted", "superseded"].includes(item.status))) {
      const coverage = release.coverage_json || {};
      rows.push({ dataset_id: release.dataset_id, locality: coverage.locality || coverage.area || coverage.state || "NSW", coverage_status: coverage.status || (coverage.complete === false ? "partial" : "supported"), target_feature: release.target_feature, release_version: release.release_version, accepted_at: release.accepted_at, description: coverage.profile });
    }
    clearView();
    append(view, pageHeading("Availability evidence", "Coverage matrix", "Accepted, partial, stale and unavailable are explicit data states—not inferred from a running service."));
    if (!rows.length) { append(view, emptyState("No coverage evidence", "Coverage is published only after a release has been accepted.")); return; }
    const table = makeTable([{ label: "Dataset" }, { label: "Locality / area" }, { label: "Consumer feature" }, { label: "Coverage" }, { label: "Accepted release" }, { label: "As at" }], rows, (item) => {
      const row = el("tr");
      append(row, cell(primaryCell(item.dataset || item.dataset_id, item.description)), cell(item.locality || item.area || item.geography || "NSW"), cell(item.feature || item.target_feature || "Property discovery"), cell(badge(item.status || item.coverage_status)), cell(item.release_version || item.dataset_release_id || "—", "mono"), cell(formatDate(item.as_at || item.accepted_at)));
      return row;
    });
    append(view, panel(`${rows.length} coverage entries`, "Colour is always paired with status text", table));
  } catch (error) { clearView(); append(view, errorState(error, renderRoute)); }
}

async function renderProperties() {
  clearView();
  const hero = el("section", "discovery-hero");
  append(hero, el("p", "eyebrow", "Property discovery"), el("h1", "", "Trace an NSW address to the evidence behind it"), el("p", "", "Search the accepted property registry, inspect match provenance and see which buyer features have usable data."));
  const form = el("form", "search-box");
  const input = el("input"); input.type = "search"; input.name = "q"; input.placeholder = "Try 1 Farrer Place, Sydney NSW 2000"; input.autocomplete = "street-address"; input.maxLength = 250; input.required = true;
  append(form, input, button("Search", "button primary"));
  append(hero, form);
  append(hero, el("p", "search-help", "NSW only · Maximum 25 matches · Search works without AI"));
  append(view, hero);
  const resultHost = el("div");
  append(resultHost, emptyState("Start with a street address", "Results include an accessible list and table-based coordinate context. No map interaction is required."));
  append(view, resultHost);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    resultHost.replaceChildren(el("section", "loading-state", "Searching the accepted property registry…"));
    try {
      const result = await request(`properties/search${queryString({ q: input.value.trim(), state: "NSW", limit: 25 })}`);
      const items = collection(result.body);
      state.propertyResults = items;
      if (result.body.supported === false) resultHost.replaceChildren(el("div", "notice warning", "This query is outside the supported NSW coverage. Try an NSW street address."));
      else if (!items.length) resultHost.replaceChildren(emptyState("No canonical property found", "Try including a street number, suburb and four-digit postcode. The platform will not invent or silently broaden a match."));
      else { renderPropertyResults(resultHost, items); announce(`${items.length} property matches found.`); }
    } catch (error) { resultHost.replaceChildren(errorState(error, () => form.requestSubmit())); }
  });
}

function renderPropertyResults(host, items) {
  const layout = el("div", "property-results");
  const listBody = el("div", "result-list");
  listBody.setAttribute("aria-label", "Property matches");
  const detailHost = el("div");
  items.forEach((item, index) => {
    const result = el("button", "result-card"); result.type = "button";
    append(result, el("strong", "", item.address_display), el("span", "", `${item.locality || ""} ${item.state || "NSW"} ${item.postcode || ""} · ${humanise(item.resolution_status || item.match?.status)}`));
    result.addEventListener("click", () => selectProperty(item, detailHost, result, listBody));
    append(listBody, result);
    if (index === 0) queueMicrotask(() => result.click());
  });
  append(layout, panel(`${items.length} matches`, "Select a result to inspect evidence", listBody), detailHost);
  append(host, layout);
}

async function selectProperty(summary, host, selectedButton, list) {
  for (const item of list.querySelectorAll(".result-card")) item.removeAttribute("aria-current");
  selectedButton.setAttribute("aria-current", "true");
  host.replaceChildren(panel("Property evidence", "Loading accepted snapshot…", el("div", "loading-state", "Loading…")));
  try {
    const [detailResult, mapResult, coverageResult] = await Promise.all([
      request(`properties/${encodeURIComponent(summary.property_ref)}`),
      request(`properties/${encodeURIComponent(summary.property_ref)}/map-context`),
      request(`properties/${encodeURIComponent(summary.property_ref)}/coverage`),
    ]);
    const property = entity(detailResult.body, "property");
    const map = entity(mapResult.body);
    const coverage = coverageRows(coverageResult.body).length ? coverageRows(coverageResult.body) : (detailResult.body.coverage || []);
    const body = el("div", "stack");
    append(body, el("div", "notice", `Canonical property reference: ${property.property_ref}. Match evidence is shown explicitly; aliases are not silently merged.`));
    const mapPanel = el("div", "map-context");
    const latitude = map.latitude ?? map.coordinates?.latitude ?? property.latitude ?? property.coordinates?.latitude;
    const longitude = map.longitude ?? map.coordinates?.longitude ?? property.longitude ?? property.coordinates?.longitude;
    append(mapPanel, el("span", "map-pin", "⌖"), el("div", "map-caption", `${latitude ?? "Unknown latitude"}, ${longitude ?? "unknown longitude"} · Map-style context with accessible evidence below`));
    append(body, mapPanel, detailList([["Canonical address", property.address_display || property.display_address], ["Locality", property.locality], ["Postcode", property.postcode], ["Resolution", badge(property.resolution_status || summary.resolution_status || property.match?.tier)], ["Match source", summary.match?.source || property.match?.source], ["Match score", summary.match?.score ?? summary.match?.confidence ?? property.match?.score ?? property.match?.confidence ?? "Not supplied"]]));
    const cards = el("div", "coverage-grid");
    for (const item of coverage) { const card = el("div", `coverage-card ${statusTone(item.status || item.coverage_status || item.state)}`); append(card, el("strong", "", item.dataset || item.dataset_id || item.feature || item.target_feature || "Dataset"), el("span", "", `${humanise(item.status || item.coverage_status || item.state)}${item.release_version ? ` · ${item.release_version}` : ""}${item.limitation ? ` · ${item.limitation}` : ""}`)); append(cards, card); }
    if (coverage.length) append(body, el("h3", "", "Feature coverage"), cards);
    append(body, technicalDetails({ identifiers: detailResult.body.identifiers || [], aliases: detailResult.body.aliases || [], map }, "Identifiers, aliases and coordinate evidence"));
    host.replaceChildren(panel("Property evidence", "Accepted snapshot and provenance", body));
  } catch (error) { host.replaceChildren(errorState(error, () => selectProperty(summary, host, selectedButton, list))); }
}

async function renderAi(context = "") {
  loading("Loading diagnosis workspace");
  try {
    const releasesResult = await request("dataset-releases?limit=100");
    const releases = collection(releasesResult.body);
    clearView();
    append(view, pageHeading("Assisted investigation", "AI diagnosis", "The model inspects bounded stored evidence and pauses before protected retry or publish actions."));
    append(view, el("div", "notice", "Direct operations and property discovery do not depend on Ollama. If the model is unavailable, all stored evidence remains accessible."));
    const formBody = el("div");
    const form = el("form", "form-grid");
    const releaseLabel = el("label", "wide"); append(releaseLabel, el("span", "", "Candidate release"));
    const releaseSelect = el("select"); releaseSelect.required = true;
    for (const release of releases) { const option = el("option", "", `${release.dataset_id} ${release.release_version} · ${humanise(release.status)}`); option.value = release.id; option.selected = context === `release:${release.id}`; append(releaseSelect, option); }
    append(releaseLabel, releaseSelect);
    append(form, releaseLabel);
    const objectiveLabel = el("label", "wide"); append(objectiveLabel, el("span", "", "Diagnosis objective"));
    const objective = el("textarea"); objective.value = "Diagnose why this candidate is not publishable, determine whether existing buyer analytics remain usable, and prepare the safest recovery action."; objective.maxLength = 2000; objective.required = true; append(objectiveLabel, objective); append(form, objectiveLabel);
    const submit = button("Start bounded diagnosis", "button primary"); submit.type = "submit"; append(form, submit); append(formBody, form);
    const traceHost = el("div");
    append(view, panel("Start diagnosis", "Plan → Act → Observe → Adapt with human review", formBody), traceHost);
    if (!releases.length) { form.replaceChildren(el("p", "", "No release candidates are available to diagnose.")); return; }
    form.addEventListener("submit", async (event) => {
      event.preventDefault(); submit.disabled = true;
      traceHost.replaceChildren(panel("Agent trace", "Creating a durable AI-mode run…", el("div", "loading-state", "Connecting to AI-mode…")));
      try {
        const result = await mutate(`dataset-releases/${releaseSelect.value}/agent-runs`, { body: { objective: objective.value.trim() }, success: "Diagnosis started" });
        const run = entity(result, "agent_run");
        await pollAgent(run.id || result.id, traceHost);
      } catch (error) {
        const message = error.status === 503 ? "Ollama is unavailable. Direct evidence and recovery controls remain usable; retry diagnosis when the model service is ready." : error.message;
        traceHost.replaceChildren(el("div", "notice warning", `${message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`));
        submit.disabled = false;
      }
    });
  } catch (error) { clearView(); append(view, errorState(error, renderRoute)); }
}

async function pollAgent(id, host, cursor = 0, failures = 0) {
  const generation = state.generation;
  try {
    const [detailResult, eventsResult] = await Promise.all([request(`agent-runs/${id}`), request(`agent-runs/${id}/events${queryString({ after: cursor, limit: 100 })}`)]);
    if (generation !== state.generation) return;
    const run = entity(detailResult.body, "agent_run");
    const events = collection(eventsResult.body);
    const body = el("div");
    const steps = run.steps || detailResult.body.steps || events;
    append(body, detailList([["Status", badge(run.status)], ["Agent run", el("code", "mono", run.id || id)], ["Request ID", el("code", "mono", run.request_id || detailResult.requestId)]]));
    const timeline = el("ol", "timeline");
    for (const step of steps) {
      const item = el("li"); const tone = statusTone(step.status); const detail = el("div");
      append(detail, el("h3", "", humanise(step.phase || step.event_type || "Agent event")), el("p", "", step.summary || step.message || humanise(step.status)));
      if (step.tool_key || step.tool_name) append(detail, el("code", "mono", step.tool_key || step.tool_name));
      append(item, el("span", `timeline-marker ${tone}`, stateLabel(step.status).symbol), detail);
      append(timeline, item);
    }
    append(body, timeline);
    if (run.status === "review_required") append(body, el("div", "notice warning", "A protected retry or publication is paused for human review. Review it in the durable AI-mode approval interface; no write has occurred."));
    if (run.final_result) append(body, technicalDetails(run.final_result, "Terminal result and cited evidence"));
    host.replaceChildren(panel("Agent trace", "Live durable phases and bounded tool calls", body));
    if (["succeeded", "failed", "cancelled", "review_required"].includes(run.status)) return;
    const nextCursor = eventsResult.body.next_cursor || events.at(-1)?.id || cursor;
    setTimeout(() => { if (generation === state.generation) pollAgent(id, host, nextCursor); }, document.hidden ? 8000 : 1500);
  } catch (error) {
    if (generation !== state.generation) return;
    host.replaceChildren(el("div", "notice warning", `Diagnosis polling paused: ${error.message} Request ID ${error.requestId}. The run is durable and can be reloaded.`));
    if (failures < 4) setTimeout(() => pollAgent(id, host, cursor, failures + 1), Math.min(15000, 2000 * (2 ** failures)));
  }
}

async function checkHealth() {
  try {
    await request("/health/ready", { timeoutMs: 4000 });
    serviceState.className = "service-state online";
    serviceState.lastElementChild.textContent = "Data service available";
  } catch {
    serviceState.className = "service-state offline";
    serviceState.lastElementChild.textContent = "Data service unavailable";
  }
}

async function renderRoute() {
  state.generation += 1;
  clearTimeout(state.pollTimer);
  state.lastRunStatus = "";
  const { route, id } = routeParts();
  setActiveNavigation(route);
  view.setAttribute("aria-busy", "true");
  try {
    if (route === "overview") await renderOverview();
    else if (route === "sources" || route === "jobs") id ? await renderEntityDetail(route, id) : await renderEntityList(route);
    else if (route === "runs") id ? await renderRunDetail(id) : await renderRuns();
    else if (route === "releases") await renderReleases(id);
    else if (route === "quality" || route === "artifacts") await renderEvidenceExplorer(route, id);
    else if (route === "coverage") await renderCoverage();
    else if (route === "properties") await renderProperties();
    else if (route === "ai") await renderAi(id);
  } catch (error) {
    clearView();
    append(view, errorState(error, renderRoute));
  } finally {
    view.setAttribute("aria-busy", "false");
  }
}

entityForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (event.submitter?.value === "cancel") entityDialog.close("cancel");
  else if (entityForm.reportValidity()) entityDialog.close("save");
});
actionForm.addEventListener("submit", (event) => { event.preventDefault(); actionDialog.close(event.submitter?.value || "cancel"); });
navToggle.addEventListener("click", () => { const open = sidebar.classList.toggle("open"); navToggle.setAttribute("aria-expanded", String(open)); });
window.addEventListener("hashchange", renderRoute);
document.addEventListener("visibilitychange", () => { const current = routeParts(); if (!document.hidden && current.route === "runs" && current.id && ACTIVE_RUN_STATES.has(state.lastRunStatus)) renderRunDetail(current.id, { polling: true }); });

checkHealth();
renderRoute();
setInterval(checkHealth, 30000);
