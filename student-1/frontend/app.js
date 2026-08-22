import { API_BASE, newRequestId, requestJson } from "./core/api.js";
import { append, el } from "./core/dom.js";
import { humanise } from "./core/formats.js";
import { parseJsonField } from "./core/forms.js";
import { ACTIVE_AGENT_STATES, ACTIVE_RUN_STATES, createGenerationGuard } from "./core/polling.js";
import { parseRoute } from "./core/router.js?v=7";
import { waitForDialog } from "./components/dialogs.js";
import { formField } from "./components/forms.js";
import { renderLoading } from "./components/states.js";
import { createAiDiagnosisRoutes } from "./routes/ai-diagnosis.js?v=8";
import { createEntityRoutes } from "./routes/entities.js?v=7";
import { createDataProductRoutes } from "./routes/data-products.js";
import { createEvidenceRoutes } from "./routes/evidence.js";
import { renderOverview } from "./routes/overview.js?v=7";
import { createPropertyRoutes } from "./routes/properties.js?v=7";
import { createReleaseRoutes } from "./routes/releases.js?v=7";
import { createRunPlanner } from "./routes/run-plan.js";
import { createRunRoutes } from "./routes/runs.js?v=7";

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

const productHomeUrl = window.PROPERTYSCOPE_HOME_URL
  || (window.location.pathname.startsWith("/features/data-platform/") ? "/" : "http://localhost:5100/");
const healthUrl = window.location.pathname.startsWith("/features/data-platform/")
  ? "/api/shared-health/data-platform"
  : "/health/ready";
for (const item of document.querySelectorAll("[data-product-home]")) item.href = productHomeUrl;

const state = { pollTimer: null, lastRunStatus: "", lastAgentStatus: "", requests: new Map() };
const generationGuard = createGenerationGuard();

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

function setActiveNavigation(route) {
  for (const item of document.querySelectorAll("[data-route]")) {
    if (item.dataset.route === route) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  const advanced = document.querySelector(".advanced-nav");
  if (advanced?.querySelector(`[data-route="${route}"]`)) advanced.open = true;
  sidebar.classList.remove("open");
  navToggle.setAttribute("aria-expanded", "false");
  navToggle.querySelector(".visually-hidden").textContent = "Open navigation";
}

function closeNavigation({ restoreFocus = false } = {}) {
  sidebar.classList.remove("open");
  navToggle.setAttribute("aria-expanded", "false");
  navToggle.querySelector(".visually-hidden").textContent = "Open navigation";
  if (restoreFocus) navToggle.focus();
}

function loading(title = "Loading evidence") { renderLoading(view, title); }

function request(path, options = {}) {
  return requestJson(fetch, path.startsWith("/") ? path : `${API_BASE}/${path}`, options);
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
  { name: "target_features", label: "Research area keys", type: "json_array", wide: true, required: true, help: "Stored contract keys for the areas allowed to consume this source" },
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
  { name: "target_feature", label: "Research area key", required: true },
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
  { name: "schedule_text", label: "Schedule note", wide: true, help: "Descriptive only; no scheduler is enabled" },
];

async function openEntityDialog(kind, item = null) {
  const isSource = kind === "source";
  const fields = isSource ? SOURCE_FIELDS : JOB_FIELDS;
  document.querySelector("#entity-kicker").textContent = isSource ? "Source definition" : "Job definition";
  document.querySelector("#entity-title").textContent = `${item ? "Edit" : "Create"} ${kind}`;
  const fieldHost = document.querySelector("#entity-fields");
  const fieldValue = (name) => item?.[name] ?? ({
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
  })[name];
  fieldHost.replaceChildren(...fields.map((definition) => formField(definition, fieldValue(definition.name))));
  document.querySelector("#entity-error").textContent = "";
  entityDialog.returnValue = "";
  entityDialog.showModal();
  entityDialog.querySelector("input, select, textarea")?.focus();
  if (!await waitForDialog(entityDialog, "save")) return;
  const data = Object.fromEntries(new FormData(entityForm));
  try {
    for (const definition of fields.filter((field) => field.type === "json")) data[definition.name] = parseJsonField(data[definition.name], definition.label);
    for (const definition of fields.filter((field) => field.type === "json_array")) {
      try { const parsed = JSON.parse(data[definition.name] || "[]"); if (!Array.isArray(parsed) || (definition.required && !parsed.length) || parsed.some((value) => typeof value !== "string")) throw new Error(); data[definition.name] = parsed; }
      catch { throw new Error(`${definition.label} must be a JSON list of text values.`); }
    }
    for (const definition of fields.filter((field) => field.type === "number")) data[definition.name] = Number(data[definition.name]);
    if (item?.version !== undefined) data.version = item.version;
    const path = isSource ? "sources" : "jobs";
    const result = await request(`${path}${item ? `/${encodeURIComponent(item.id)}` : ""}`, { method: item ? "PUT" : "POST", body: data });
    showToast(`${humanise(kind)} ${item ? "updated" : "created"}. Request ID ${result.requestId}`);
    await renderRoute();
  } catch (error) { showToast(`${error.message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`); }
}

function confirmAction({ title, description, label = "Confirm", tone = "danger", extra = null }) {
  document.querySelector("#action-title").textContent = title;
  document.querySelector("#action-description").textContent = description;
  document.querySelector("#action-error").textContent = "";
  const host = document.querySelector("#action-extra"); host.replaceChildren(); if (extra) append(host, extra);
  const confirm = document.querySelector("#action-confirm"); confirm.textContent = label; confirm.className = `button ${tone}`;
  actionDialog.returnValue = ""; actionDialog.showModal(); return waitForDialog(actionDialog, "confirm");
}

async function mutate(path, { method = "POST", body = {}, success = "Action completed" } = {}) {
  const result = await request(path, { method, headers: { "Idempotency-Key": body?.idempotency_key || newRequestId() }, body });
  showToast(`${success}. Request ID ${result.requestId}`); return result.body;
}

const openPlanDialog = createRunPlanner({ request, mutate, confirmAction, showToast });
const { renderEntityList, renderEntityDetail } = createEntityRoutes({ view, request, openEntityDialog, openPlanDialog, confirmAction, mutate, showToast, rerender: renderRoute });
const { renderRuns, renderRunDetail } = createRunRoutes({ view, request, mutate, confirmAction, showToast, announce, state, generationGuard, rerender: renderRoute });
const { renderProperties } = createPropertyRoutes({ view, request, announce });
const { renderDataProducts } = createDataProductRoutes({ view, request, loading, rerender: renderRoute });
const { renderReleases } = createReleaseRoutes({ view, request, loading, entityDialog, entityForm, confirmAction, mutate, showToast, rerender: renderRoute });
const { renderEvidenceExplorer, renderCoverage } = createEvidenceRoutes({ view, request, loading, rerender: renderRoute });
const { renderAi, resumeAgentTrace } = createAiDiagnosisRoutes({ view, request, loading, mutate, state, generationGuard, rerender: renderRoute });

async function checkHealth() {
  try { await request(healthUrl, { timeoutMs: 4000 }); serviceState.className = "service-state online"; serviceState.lastElementChild.textContent = "Data service available"; }
  catch { serviceState.className = "service-state offline"; serviceState.lastElementChild.textContent = "Data service unavailable"; }
}

async function renderRoute({ focus = false } = {}) {
  generationGuard.next(); clearTimeout(state.pollTimer); state.lastRunStatus = ""; state.lastAgentStatus = "";
  liveRegion.textContent = "";
  if (entityDialog.open) entityDialog.close("cancel");
  if (actionDialog.open) actionDialog.close("cancel");
  const { route, id } = parseRoute(location.hash); setActiveNavigation(route); view.setAttribute("aria-busy", "true");
  try {
    if (route === "overview") await renderOverview({ view, request });
    else if (route === "data-products") await renderDataProducts(id);
    else if (route === "sources" || route === "jobs") id ? await renderEntityDetail(route, id) : await renderEntityList(route);
    else if (route === "runs") id ? await renderRunDetail(id) : await renderRuns();
    else if (route === "releases") await renderReleases(id);
    else if (route === "quality" || route === "artifacts") await renderEvidenceExplorer(route, id);
    else if (route === "coverage") await renderCoverage();
    else if (route === "properties") await renderProperties(id);
    else if (route === "ai") await renderAi(id);
  } catch (error) { view.replaceChildren(el("div", "notice negative", `${error.message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`)); }
  finally {
    view.setAttribute("aria-busy", "false");
    const heading = view.querySelector("h1");
    if (heading) document.title = `PropertyScope | ${heading.textContent}`;
    if (focus && heading) {
      heading.tabIndex = -1;
      heading.focus();
    }
  }
}

entityForm.addEventListener("submit", (event) => { event.preventDefault(); if (event.submitter?.value === "cancel") entityDialog.close("cancel"); else if (entityForm.reportValidity()) entityDialog.close("save"); });
actionForm.addEventListener("submit", (event) => { event.preventDefault(); actionDialog.close(event.submitter?.value || "cancel"); });
navToggle.addEventListener("click", () => { const open = sidebar.classList.toggle("open"); navToggle.setAttribute("aria-expanded", String(open)); navToggle.querySelector(".visually-hidden").textContent = open ? "Close navigation" : "Open navigation"; });
sidebar.addEventListener("click", (event) => { if (event.target.closest("a")) closeNavigation(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape" && sidebar.classList.contains("open")) closeNavigation({ restoreFocus: true }); });
window.addEventListener("hashchange", () => renderRoute({ focus: true }));
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  const current = parseRoute(location.hash);
  if (current.route === "runs" && current.id && ACTIVE_RUN_STATES.has(state.lastRunStatus)) renderRunDetail(current.id, { polling: true });
  else if (current.route === "ai" && current.id && ACTIVE_AGENT_STATES.has(state.lastAgentStatus)) resumeAgentTrace(current.id);
});

checkHealth(); renderRoute(); setInterval(checkHealth, 30000);
