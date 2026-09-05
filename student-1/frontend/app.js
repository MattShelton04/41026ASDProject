import { API_BASE, newRequestId, requestJson } from "./core/api.js";
import { append, el } from "./core/dom.js";
import { humanise } from "./core/formats.js";
import { parseIntegerField, parseJsonField, propertySearchQuery } from "./core/forms.js";
import { ACTIVE_AGENT_STATES, ACTIVE_RUN_STATES, createGenerationGuard } from "./core/polling.js";
import { parseRoute } from "./core/router.js";
import { requestActiveDialogClose, runDialogForm } from "./components/dialogs.js";
import { createDrawerController, createToastController, disposeTableRegions } from "./browser/index.js";
import { formField } from "./components/forms.js";
import { hydrateIcons } from "./components/icons.js";
import { renderLoading } from "./components/states.js";
import { createAiDiagnosisRoutes } from "./routes/ai-diagnosis.js";
import { createFeatureAssistantRoute } from "./routes/assistant.js";
import { createEntityRoutes } from "./routes/entities.js";
import { createDataProductRoutes } from "./routes/data-products.js";
import { createEvidenceRoutes } from "./routes/evidence.js";
import { renderOverview } from "./routes/overview.js";
import { createPropertyRoutes } from "./routes/properties.js";
import { createReleaseRoutes } from "./routes/releases.js?v=49";
import { createRunPlanner } from "./routes/run-plan.js";
import { createRunRoutes } from "./routes/runs.js";
import { createSourceHtmxRoute } from "./routes/sources-htmx.js";

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
hydrateIcons();
let drawerController = null;

const healthUrl = window.location.pathname.startsWith("/features/data-platform/")
  ? "/api/shared-health/data-platform"
  : "/health/ready";

const state = {
  pollTimer: null,
  lastRunStatus: "",
  lastAgentStatus: "",
  interruptedReconciliationAttempts: 0,
};
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

function routeRequest(path, options = {}) {
  return request(path, {
    ...options,
    signals: [generationGuard.signal(), ...(options.signals || [])],
  });
}

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
  { name: "quality_policy_key", label: "Quality policy", required: true },
  { name: "quality_policy_version", label: "Quality policy version", required: true },
  { name: "status", label: "Lifecycle status", options: ["draft", "active", "disabled", "retired"], required: true },
  { name: "schedule_text", label: "Schedule note", wide: true, maxLength: 200, help: "Optional, up to 200 characters. Descriptive only; no scheduler is enabled." },
];

async function openEntityDialog(kind, item = null) {
  const fields = JOB_FIELDS;
  document.querySelector("#entity-form [data-source-editor]")?.removeAttribute("data-source-editor");
  document.querySelector("#entity-kicker").textContent = "Job definition";
  document.querySelector("#entity-title").textContent = `${item ? "Edit" : "Create"} ${kind}`;
  const fieldHost = document.querySelector("#entity-fields");
  const fieldValue = (name) => item?.[name] ?? ({
    adapter_key: item?.adapter?.key,
    import_profile_key: item?.import_profile?.key,
    import_profile_version: item?.import_profile?.version,
    target_feature: item?.target?.feature,
    quality_policy_key: item?.quality_policy,
  })[name];
  fieldHost.replaceChildren(...fields.map((definition) => formField(definition, fieldValue(definition.name))));
  const entitySave = document.querySelector("#entity-save");
  for (const attribute of ["hx-delete", "hx-post", "hx-put", "hx-include", "hx-target", "hx-swap", "hx-indicator", "hx-disabled-elt"]) entitySave.removeAttribute(attribute);
  const saved = await runDialogForm({
    dialog: entityDialog,
    form: entityForm,
    submitButton: entitySave,
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
      for (const definition of fields.filter((field) => field.type === "number")) {
        data[definition.name] = parseIntegerField(data[definition.name], definition.label, {
          fieldName: definition.name,
          minimum: definition.min ?? null,
          maximum: definition.max ?? null,
        });
      }
      if (item?.version !== undefined) data.version = item.version;
      const result = await request(`jobs${item ? `/${encodeURIComponent(item.id)}` : ""}`, { method: item ? "PUT" : "POST", body: data });
      showToast(`${humanise(kind)} ${item ? "updated" : "created"}. Request ID ${result.requestId}`);
    },
  });
  if (saved) await renderRoute();
}

function confirmAction({ title, description, label = "Confirm", tone = "danger", extra = null, onConfirm = null, progressLabel = "Working…", discardMessage = "Discard your entered changes?" }) {
  document.querySelector("#action-form [data-source-delete]")?.removeAttribute("data-source-delete");
  document.querySelector("#action-title").textContent = title;
  document.querySelector("#action-description").textContent = description;
  document.querySelector("#action-error").textContent = "";
  const host = document.querySelector("#action-extra"); host.replaceChildren(); if (extra) append(host, extra);
  const confirm = document.querySelector("#action-confirm"); confirm.textContent = label; confirm.className = `button ${tone}`;
  for (const attribute of ["hx-delete", "hx-post", "hx-put", "hx-target", "hx-swap", "hx-indicator", "hx-disabled-elt"]) confirm.removeAttribute(attribute);
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

async function mutate(path, { method = "POST", body = {}, success = "Action completed", idempotencyKey = "", timeoutMs = undefined } = {}) {
  const result = await request(path, {
    method,
    headers: { "Idempotency-Key": idempotencyKey || body?.idempotency_key || newRequestId() },
    body,
    ...(timeoutMs === undefined ? {} : { timeoutMs }),
  });
  showToast(`${success}. Request ID ${result.requestId}`); return result.body;
}

const openPlanDialog = createRunPlanner({ request, mutate, confirmAction });
const retryRoute = () => renderRoute({ focus: true });
const { renderEntityList, renderEntityDetail } = createEntityRoutes({ view, request: routeRequest, openEntityDialog, openPlanDialog, confirmAction, mutate, generationGuard, rerender: retryRoute });
const { renderSources, requestSourceDialogClose } = createSourceHtmxRoute({ view, entityDialog, actionDialog, confirmDiscard, announce, showToast });
const { renderRuns, renderRunDetail } = createRunRoutes({ view, request: routeRequest, mutate, confirmAction, announce, state, generationGuard, rerender: retryRoute });
const { renderProperties } = createPropertyRoutes({ view, request: routeRequest, announce, generationGuard, rerender: retryRoute });
const { renderDataProducts } = createDataProductRoutes({ view, request: routeRequest, loading, generationGuard, rerender: retryRoute });
const { renderReleases } = createReleaseRoutes({ view, request: routeRequest, loading, entityDialog, entityForm, confirmAction, confirmDiscard, mutate, showToast, generationGuard, rerender: retryRoute });
const { renderEvidenceExplorer, renderCoverage } = createEvidenceRoutes({ view, request: routeRequest, loading, generationGuard, rerender: retryRoute });
const { renderAi, resumeAgentTrace } = createAiDiagnosisRoutes({ view, request: routeRequest, loading, mutate, state, generationGuard, rerender: retryRoute });
const featureAssistant = createFeatureAssistantRoute({ view, announce });

async function checkHealth() {
  try { await request(healthUrl, { timeoutMs: 4000 }); serviceState.className = "service-state online"; serviceState.lastElementChild.textContent = "Data service available"; serviceState.setAttribute("aria-label", "Data service available"); }
  catch { serviceState.className = "service-state offline"; serviceState.lastElementChild.textContent = "Data service unavailable"; serviceState.setAttribute("aria-label", "Data service unavailable"); }
}

async function renderRoute({ focus = false } = {}) {
  disposeTableRegions(view);
  featureAssistant.destroy();
  const routeEpoch = generationGuard.begin();
  clearTimeout(state.pollTimer); state.lastRunStatus = ""; state.lastAgentStatus = "";
  state.interruptedReconciliationAttempts = 0;
  liveRegion.textContent = "";
  const requestedHash = location.hash;
  const { route, id } = parseRoute(requestedHash); setActiveNavigation(route); view.setAttribute("aria-busy", "true");
  view.dataset.density = route === "properties" ? "comfortable" : "compact";
  try {
    if (route === "overview") await renderOverview({ view, request, generationGuard, rerender: retryRoute });
    else if (route === "data-products") await renderDataProducts(id);
    else if (route === "sources") renderSources(id);
    else if (route === "jobs") id ? await renderEntityDetail(id) : await renderEntityList();
    else if (route === "runs") id ? await renderRunDetail(id) : await renderRuns();
    else if (route === "releases") await renderReleases(id);
    else if (route === "quality" || route === "artifacts") await renderEvidenceExplorer(route, id);
    else if (route === "coverage") await renderCoverage();
    else if (route === "properties") await renderProperties(id);
    else if (route === "assistant") featureAssistant.render();
    else if (route === "ai") await renderAi(id);
  } catch (error) {
    if (!routeEpoch.isCurrent()) return;
    view.replaceChildren(el("div", "notice negative", `${error.message}${error.requestId ? ` Request ID ${error.requestId}` : ""}`));
  } finally {
    if (!routeEpoch.isCurrent()) return;
    lastRenderedHash = requestedHash;
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
    .find((dialog) => !requestSourceDialogClose(dialog, { onDiscardDecision: discardDecided })
      || !requestActiveDialogClose(dialog, { onDiscardDecision: discardDecided }));
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
  if (current.route === "runs" && current.id && (ACTIVE_RUN_STATES.has(state.lastRunStatus) || state.lastRunStatus === "interrupted")) {
    renderRunDetail(current.id, { polling: true, resetInterruptedReconciliation: true });
  }
  else if (current.route === "ai" && current.id && ACTIVE_AGENT_STATES.has(state.lastAgentStatus)) resumeAgentTrace(current.id);
});

checkHealth(); renderRoute(); setInterval(checkHealth, 30000);

window.addEventListener("pagehide", () => { disposeTableRegions(view); drawerController?.destroy(); toastController.hide(); }, { once: true });
