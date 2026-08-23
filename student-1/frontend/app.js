import { API_BASE, newRequestId, requestJson } from "./core/api.js";
import { append, el } from "./core/dom.js";
import { humanise } from "./core/formats.js?v=17";
import { parseIntegerField, parseJsonField, parseJsonTextList, propertySearchQuery } from "./core/forms.js";
import { ACTIVE_AGENT_STATES, ACTIVE_RUN_STATES, createGenerationGuard } from "./core/polling.js";
import { parseRoute } from "./core/router.js?v=7";
import { requestActiveDialogClose, runDialogForm } from "./components/dialogs.js";
import { createDrawerController, createToastController } from "./browser/index.js?v=3";
import { formField } from "./components/forms.js?v=17";
import { renderLoading } from "./components/states.js";
import { createAiDiagnosisRoutes } from "./routes/ai-diagnosis.js?v=17";
import { createEntityRoutes } from "./routes/entities.js?v=18";
import { createDataProductRoutes } from "./routes/data-products.js?v=17";
import { createEvidenceRoutes } from "./routes/evidence.js?v=17";
import { renderOverview } from "./routes/overview.js?v=18";
import { createPropertyRoutes } from "./routes/properties.js?v=18";
import { createReleaseRoutes } from "./routes/releases.js?v=18";
import { createRunPlanner } from "./routes/run-plan.js?v=17";
import { createRunRoutes } from "./routes/runs.js?v=17";

const view = document.querySelector("#view");
const liveRegion = document.querySelector("#live-region");
const serviceState = document.querySelector("#service-state");
const sidebar = document.querySelector("#primary-nav");
const navToggle = document.querySelector("#nav-toggle");
const drawerScrim = document.querySelector("#drawer-scrim");
const headerPropertySearch = document.querySelector("#header-property-search");
const headerPropertyQuery = document.querySelector("#header-property-query");
const entityDialog = document.querySelector("#entity-dialog");
const entityForm = document.querySelector("#entity-form");
const actionDialog = document.querySelector("#action-dialog");
const actionForm = document.querySelector("#action-form");
const discardDialog = document.querySelector("#discard-dialog");
const discardForm = document.querySelector("#discard-form");
const toast = document.querySelector("#toast");
const toastController = createToastController(toast, { duration: 4500 });
let drawerController = null;

const productHomeUrl = window.PROPERTYSCOPE_HOME_URL
  || (window.location.pathname.startsWith("/features/data-platform/") ? "/" : "http://localhost:5100/");
const healthUrl = window.location.pathname.startsWith("/features/data-platform/")
  ? "/api/shared-health/data-platform"
  : "/health/ready";
for (const item of document.querySelectorAll("[data-product-home]")) item.href = productHomeUrl;
for (const item of document.querySelectorAll("[data-product-path]")) {
  item.href = new URL(item.dataset.productPath, new URL(productHomeUrl, window.location.href)).href;
}

const state = { pollTimer: null, lastRunStatus: "", lastAgentStatus: "", requests: new Map() };
const generationGuard = createGenerationGuard();
let lastRenderedHash = location.hash;
let guardedNavigationGeneration = 0;
let pendingGuardedNavigation = null;

function announce(message) {
  liveRegion.textContent = "";
  requestAnimationFrame(() => { liveRegion.textContent = message; });
}

function showToast(message) {
  toastController.show(message);
}

function setActiveNavigation(route) {
  for (const item of document.querySelectorAll("[data-route]")) {
    if (item.dataset.route === route) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  }
  const advanced = document.querySelector(".advanced-nav");
  if (advanced?.querySelector(`[data-route="${route}"]`)) advanced.open = true;
  drawerController?.close({ restoreFocus: false });
}

function closeNavigation({ restoreFocus = false } = {}) {
  drawerController?.close({ restoreFocus });
}

function loading(title = "Loading evidence") { renderLoading(view, title); }

function request(path, options = {}) {
  return requestJson(fetch, path.startsWith("/") ? path : `${API_BASE}/${path}`, options);
}

const SOURCE_FIELDS = [
  { name: "name", label: "Source name", required: true },
  { name: "publisher", label: "Publisher", required: true },
  { name: "source_url", label: "Attribution URL", type: "url", required: true, wide: true, help: "Metadata only; acquisition remains allowlisted" },
  { name: "adapter_key", label: "Connector", required: true },
  { name: "cadence", label: "Update cadence", required: true },
  { name: "licence_id", label: "Licence", required: true },
  { name: "licence_url", label: "Licence URL", type: "url", required: true },
  { name: "redistribution_policy", label: "Redistribution policy", required: true, wide: true },
  { name: "target_features", label: "Research area keys", type: "json_array", wide: true, required: true, maximumItems: 5, uniqueItems: true, help: "One to five unique stored contract keys as JSON, for example [\"feature-1\"]" },
  { name: "status", label: "Lifecycle status", options: ["draft", "active", "disabled", "retired"], required: true },
  { name: "notes", label: "Operator notes", type: "textarea", wide: true, maxLength: 2000, help: "Up to 2,000 characters; optional." },
];

const JOB_FIELDS = [
  { name: "source_definition_id", label: "Source ID", required: true, wide: true },
  { name: "name", label: "Job name", required: true },
  { name: "profile_key", label: "Registered profile", required: true },
  { name: "profile_version", label: "Profile version", required: true, maxLength: 30 },
  { name: "adapter_key", label: "Connector", required: true },
  { name: "release_builder_key", label: "Release builder", required: true },
  { name: "import_profile_key", label: "Import profile", required: true },
  { name: "import_profile_version", label: "Import profile version", required: true, maxLength: 30 },
  { name: "target_feature", label: "Research area key", required: true },
  { name: "dataset_id", label: "Dataset ID", required: true },
  { name: "refresh_strategy", label: "Refresh strategy", options: ["full_snapshot", "append_only_partitioned", "partitioned_snapshot", "manual_versioned_import"], required: true },
  { name: "default_run_mode", label: "Default run mode", options: ["full_refresh", "reprocess_cached"], required: true },
  { name: "scope_json", label: "Default update scope", type: "json", wide: true },
  { name: "quality_policy_key", label: "Quality policy", required: true },
  { name: "quality_policy_version", label: "Quality policy version", required: true },
  { name: "max_parallelism", label: "Maximum parallel tasks", type: "number", min: 1, max: 16, required: true, help: "1–16 tasks." },
  { name: "timeout_seconds", label: "Time limit (seconds)", type: "number", min: 1, max: 86400, required: true, help: "1–86,400 seconds (24 hours)." },
  { name: "max_objects", label: "Object limit", type: "number", min: 1, max: 100000, required: true, help: "1–100,000 source objects." },
  { name: "max_bytes", label: "Byte limit", type: "number", min: 1, max: 100000000000, required: true, help: "1–100,000,000,000 bytes." },
  { name: "max_rows", label: "Row limit", type: "number", min: 1, max: 100000000, required: true, help: "1–100,000,000 rows." },
  { name: "status", label: "Lifecycle status", options: ["draft", "active", "disabled", "retired"], required: true },
  { name: "schedule_text", label: "Schedule note", wide: true, maxLength: 200, help: "Optional, up to 200 characters. Descriptive only; no scheduler is enabled." },
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
  const saved = await runDialogForm({
    dialog: entityDialog,
    form: entityForm,
    submitButton: document.querySelector("#entity-save"),
    errorHost: document.querySelector("#entity-error"),
    acceptedValue: "save",
    progressLabel: item ? "Saving changes…" : `Creating ${kind}…`,
    discardMessage: `Discard your unsaved ${kind} changes?`,
    confirmDiscard,
    onSubmit: async () => {
      const data = Object.fromEntries(new FormData(entityForm));
      for (const definition of fields.filter((field) => field.type === "json")) {
        data[definition.name] = parseJsonField(data[definition.name], definition.label, definition.name);
      }
      for (const definition of fields.filter((field) => field.type === "json_array")) {
        data[definition.name] = parseJsonTextList(data[definition.name], definition.label, definition.name, {
          maximum: definition.maximumItems ?? null,
          unique: Boolean(definition.uniqueItems),
        });
      }
      for (const definition of fields.filter((field) => field.type === "number")) {
        data[definition.name] = parseIntegerField(data[definition.name], definition.label, {
          fieldName: definition.name,
          minimum: definition.min ?? null,
          maximum: definition.max ?? null,
        });
      }
      if (item?.version !== undefined) data.version = item.version;
      const path = isSource ? "sources" : "jobs";
      const result = await request(`${path}${item ? `/${encodeURIComponent(item.id)}` : ""}`, { method: item ? "PUT" : "POST", body: data });
      showToast(`${humanise(kind)} ${item ? "updated" : "created"}. Request ID ${result.requestId}`);
    },
  });
  if (saved) await renderRoute();
}

function confirmAction({ title, description, label = "Confirm", tone = "danger", extra = null, onConfirm = null, progressLabel = "Working…", discardMessage = "Discard your entered changes?" }) {
  document.querySelector("#action-title").textContent = title;
  document.querySelector("#action-description").textContent = description;
  document.querySelector("#action-error").textContent = "";
  const host = document.querySelector("#action-extra"); host.replaceChildren(); if (extra) append(host, extra);
  const confirm = document.querySelector("#action-confirm"); confirm.textContent = label; confirm.className = `button ${tone}`;
  return runDialogForm({
    dialog: actionDialog,
    form: actionForm,
    submitButton: confirm,
    errorHost: document.querySelector("#action-error"),
    acceptedValue: "confirm",
    progressLabel,
    discardMessage,
    confirmDiscard,
    initialFocus: '#action-form button[value="cancel"]:not(.close-button)',
    onSubmit: onConfirm || (async () => {}),
  });
}

function confirmDiscard(message) {
  document.querySelector("#discard-description").textContent = message;
  return runDialogForm({
    dialog: discardDialog,
    form: discardForm,
    submitButton: document.querySelector("#discard-confirm"),
    errorHost: document.createElement("span"),
    acceptedValue: "discard",
    progressLabel: "Discarding…",
    initialFocus: "#discard-cancel",
    onSubmit: async () => {},
  });
}

async function mutate(path, { method = "POST", body = {}, success = "Action completed" } = {}) {
  const result = await request(path, { method, headers: { "Idempotency-Key": body?.idempotency_key || newRequestId() }, body });
  showToast(`${success}. Request ID ${result.requestId}`); return result.body;
}

const openPlanDialog = createRunPlanner({ request, mutate, confirmAction });
const { renderEntityList, renderEntityDetail } = createEntityRoutes({ view, request, openEntityDialog, openPlanDialog, confirmAction, mutate, rerender: renderRoute });
const { renderRuns, renderRunDetail } = createRunRoutes({ view, request, mutate, confirmAction, announce, state, generationGuard, rerender: renderRoute });
const { renderProperties } = createPropertyRoutes({ view, request, announce, rerender: renderRoute });
const { renderDataProducts } = createDataProductRoutes({ view, request, loading, rerender: renderRoute });
const { renderReleases } = createReleaseRoutes({ view, request, loading, entityDialog, entityForm, confirmAction, confirmDiscard, mutate, showToast, rerender: renderRoute });
const { renderEvidenceExplorer, renderCoverage } = createEvidenceRoutes({ view, request, loading, rerender: renderRoute });
const { renderAi, resumeAgentTrace } = createAiDiagnosisRoutes({ view, request, loading, mutate, state, generationGuard, rerender: renderRoute });

async function checkHealth() {
  try { await request(healthUrl, { timeoutMs: 4000 }); serviceState.className = "service-state online"; serviceState.lastElementChild.textContent = "Data service available"; serviceState.setAttribute("aria-label", "Data service available"); }
  catch { serviceState.className = "service-state offline"; serviceState.lastElementChild.textContent = "Data service unavailable"; serviceState.setAttribute("aria-label", "Data service unavailable"); }
}

async function renderRoute({ focus = false } = {}) {
  generationGuard.next(); clearTimeout(state.pollTimer); state.lastRunStatus = ""; state.lastAgentStatus = "";
  liveRegion.textContent = "";
  const { route, id } = parseRoute(location.hash); setActiveNavigation(route); view.setAttribute("aria-busy", "true");
  view.dataset.density = route === "properties" ? "comfortable" : "compact";
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
    lastRenderedHash = location.hash;
    view.setAttribute("aria-busy", "false");
    const heading = view.querySelector("h1, h2");
    if (heading) document.title = `PropertyScope | ${heading.textContent}`;
    if (focus && heading) {
      heading.tabIndex = -1;
      heading.focus();
    }
  }
}

drawerController = createDrawerController({
  drawer: sidebar,
  toggle: navToggle,
  scrim: drawerScrim,
  mediaQuery: window.matchMedia("(max-width: 780px)"),
});
function validateHeaderPropertyQuery({ report = false } = {}) {
  if (!headerPropertyQuery.value.trim()) {
    headerPropertyQuery.setCustomValidity("");
    headerPropertyQuery.removeAttribute("aria-invalid");
    return "";
  }
  try {
    const query = propertySearchQuery(headerPropertyQuery.value, "header-property-query");
    headerPropertyQuery.setCustomValidity("");
    headerPropertyQuery.removeAttribute("aria-invalid");
    return query;
  } catch (error) {
    headerPropertyQuery.setCustomValidity(error.message);
    headerPropertyQuery.setAttribute("aria-invalid", "true");
    if (report) headerPropertyQuery.reportValidity();
    return null;
  }
}
headerPropertySearch.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = validateHeaderPropertyQuery({ report: true });
  if (query === "") location.hash = "#properties";
  else if (query) location.hash = `#properties?q=${encodeURIComponent(query)}`;
});
headerPropertySearch.addEventListener("invalid", (event) => {
  if (event.target === headerPropertyQuery) validateHeaderPropertyQuery();
}, true);
headerPropertyQuery.addEventListener("input", () => validateHeaderPropertyQuery());
window.addEventListener("hashchange", () => {
  const requestedHash = location.hash;
  const generation = ++guardedNavigationGeneration;
  const discardDecided = (confirmed) => {
    if (confirmed || pendingGuardedNavigation?.generation !== generation) return;
    pendingGuardedNavigation.dialog.removeEventListener("close", pendingGuardedNavigation.resume);
    pendingGuardedNavigation = null;
  };
  const blockedDialog = [entityDialog, actionDialog]
    .find((dialog) => !requestActiveDialogClose(dialog, { onDiscardDecision: discardDecided }));
  if (blockedDialog) {
    if (pendingGuardedNavigation) {
      pendingGuardedNavigation.dialog.removeEventListener("close", pendingGuardedNavigation.resume);
    }
    history.replaceState(null, "", lastRenderedHash || "#properties");
    announce("Finish or cancel the open form before leaving this page.");
    const resume = () => {
      queueMicrotask(() => {
        if (pendingGuardedNavigation?.generation !== generation) return;
        const pending = pendingGuardedNavigation;
        pendingGuardedNavigation = null;
        if (blockedDialog.returnValue !== "cancel" || location.hash !== lastRenderedHash) return;
        location.hash = pending.requestedHash;
      });
    };
    pendingGuardedNavigation = { generation, requestedHash, dialog: blockedDialog, resume };
    blockedDialog.addEventListener("close", resume, { once: true });
    return;
  }
  pendingGuardedNavigation?.dialog.removeEventListener("close", pendingGuardedNavigation.resume);
  pendingGuardedNavigation = null;
  renderRoute({ focus: true });
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  const current = parseRoute(location.hash);
  if (current.route === "runs" && current.id && ACTIVE_RUN_STATES.has(state.lastRunStatus)) renderRunDetail(current.id, { polling: true });
  else if (current.route === "ai" && current.id && ACTIVE_AGENT_STATES.has(state.lastAgentStatus)) resumeAgentTrace(current.id);
});

checkHealth(); renderRoute(); setInterval(checkHealth, 30000);
