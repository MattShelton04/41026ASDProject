export const API_BASE = "/api/buyer-workspaces/v1";
export const MAX_PREFERENCE_ITEMS = 20;
export const MAX_PREFERENCE_TEXT_LENGTH = 100;

export class ApiProblem extends Error {
  constructor(status, code, detail) {
    super(detail || `Request failed with status ${status}.`);
    this.name = "ApiProblem";
    this.status = status;
    this.code = code || "request_failed";
  }
}

export function createBuyerCaseApi(fetchImpl = globalThis.fetch) {
  async function request(method, path, body) {
    const options = { method, headers: { Accept: "application/json" } };
    if (body !== undefined) {
      options.headers["Content-Type"] = "application/json";
      options.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetchImpl(`${API_BASE}${path}`, options);
    } catch (error) {
      throw new ApiProblem(503, "database_unavailable", "Buyer cases are temporarily unavailable.");
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new ApiProblem(response.status, payload.code, payload.detail);
    }
    return payload;
  }

  return {
    list: (page = 1, pageSize = 100) => request("GET", `/buyer-cases?page=${page}&page_size=${pageSize}`),
    create: (values) => request("POST", "/buyer-cases", values),
    read: (caseId) => request("GET", `/buyer-cases/${encodeURIComponent(caseId)}`),
    update: (caseId, values) => request("PUT", `/buyer-cases/${encodeURIComponent(caseId)}`, values),
    delete: (caseId) => request("DELETE", `/buyer-cases/${encodeURIComponent(caseId)}`),
  };
}

export function statusLabel(status) {
  return { active: "Active", paused: "Paused", closed: "Closed" }[status] || "Unknown";
}

export function statusClass(status) {
  return {
    active: "ps-badge--confirmed",
    paused: "ps-badge--partial",
    closed: "ps-badge--planned",
  }[status] || "";
}

export function formatBudget(minimum, maximum) {
  const currency = new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    maximumFractionDigits: 0,
  });
  if (minimum == null && maximum == null) return "Not set";
  if (minimum == null) return `Up to ${currency.format(maximum)}`;
  if (maximum == null) return `From ${currency.format(minimum)}`;
  return `${currency.format(minimum)} – ${currency.format(maximum)}`;
}

export function formatUpdated(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return new Intl.DateTimeFormat("en-AU", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Australia/Sydney",
  }).format(date);
}

export function targetSuburbsFromText(value) {
  const seen = new Set();
  return String(value || "")
    .split(/\r?\n|,/)
    .map((locality) => locality.trim().toUpperCase())
    .filter((locality) => {
      if (!locality || seen.has(locality)) return false;
      seen.add(locality);
      return true;
    })
    .map((locality) => ({ state: "NSW", locality }));
}

export function preferenceStringsFromText(value) {
  const seen = new Set();
  return String(value || "")
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter((item) => {
      const key = item.toLocaleLowerCase("en-AU");
      if (!item || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

export function projectPreferenceLists(preferences) {
  const value = preferences && typeof preferences === "object" && !Array.isArray(preferences)
    ? preferences
    : {};
  return {
    dwellingTypes: Array.isArray(value.dwelling_types)
      ? value.dwelling_types.filter((item) => typeof item === "string")
      : [],
    priorities: Array.isArray(value.priorities)
      ? value.priorities.filter((item) => typeof item === "string")
      : [],
  };
}

export function mergePreferences(existing, dwellingTypes, priorities) {
  const retained = existing && typeof existing === "object" && !Array.isArray(existing)
    ? { ...existing }
    : {};
  return {
    ...retained,
    dwelling_types: [...dwellingTypes],
    priorities: [...priorities],
  };
}

export function validateCaseInput(values) {
  const errors = {};
  const name = String(values.name || "").trim();
  const minimum = values.budgetMin === "" ? null : Number(values.budgetMin);
  const maximum = values.budgetMax === "" ? null : Number(values.budgetMax);
  const suburbs = targetSuburbsFromText(values.suburbs);
  const dwellingTypes = preferenceStringsFromText(values.dwellingTypes);
  const priorities = preferenceStringsFromText(values.priorities);
  if (!name) errors.name = "Enter a case name.";
  if (name.length > 120) errors.name = "Case name must contain at most 120 characters.";
  if (minimum !== null && (!Number.isInteger(minimum) || minimum < 0)) {
    errors.budget = "Minimum budget must be a whole non-negative amount.";
  }
  if (maximum !== null && (!Number.isInteger(maximum) || maximum < 0)) {
    errors.budget = "Maximum budget must be a whole non-negative amount.";
  }
  if (minimum !== null && maximum !== null && maximum < minimum) {
    errors.budget = "Maximum budget cannot be less than minimum budget.";
  }
  if (suburbs.some((item) => item.locality.length > 100)) {
    errors.suburbs = "Each locality must contain at most 100 characters.";
  }
  if (dwellingTypes.length > MAX_PREFERENCE_ITEMS || priorities.length > MAX_PREFERENCE_ITEMS) {
    errors.preferences = `Use at most ${MAX_PREFERENCE_ITEMS} items in each preference list.`;
  }
  if (
    dwellingTypes.some((item) => item.length > MAX_PREFERENCE_TEXT_LENGTH)
    || priorities.some((item) => item.length > MAX_PREFERENCE_TEXT_LENGTH)
  ) {
    errors.preferences = `Each preference must contain at most ${MAX_PREFERENCE_TEXT_LENGTH} characters.`;
  }
  if (!["active", "paused", "closed"].includes(values.status || "active")) {
    errors.status = "Choose a supported status.";
  }
  return { errors, name, minimum, maximum, suburbs, dwellingTypes, priorities };
}

export function buildCasePayload(values, version = null, existingPreferences = {}) {
  const validated = validateCaseInput(values);
  if (Object.keys(validated.errors).length) return { errors: validated.errors, payload: null };
  const payload = {
    name: validated.name,
    budget_min_aud: validated.minimum,
    budget_max_aud: validated.maximum,
    target_suburbs: validated.suburbs,
    preferences: mergePreferences(
      existingPreferences,
      validated.dwellingTypes,
      validated.priorities,
    ),
    status: values.status || "active",
  };
  if (version !== null) payload.version = version;
  return { errors: {}, payload };
}

export function parseRoute(hash) {
  const match = /^#buyer-cases\/([^/]+)$/.exec(hash || "");
  if (!match) return { name: "list" };
  try {
    return { name: "detail", id: decodeURIComponent(match[1]) };
  } catch (error) {
    return { name: "list" };
  }
}

export async function navigateForFollowUp(targetHash, currentHash, setHash, reload) {
  if (targetHash === currentHash) {
    await reload();
    return "reloaded";
  }
  setHash(targetHash);
  return "navigated";
}

export function uiStateForError(error) {
  if (error instanceof ApiProblem && error.status === 409) return "conflict";
  if (error instanceof ApiProblem && error.status === 422) return "invalid";
  return "unavailable";
}

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

const api = createBuyerCaseApi();
let cases = [];
let editingCase = null;
let deletingCase = null;

function showNotice(message, kind = "success") {
  const notice = document.querySelector("#notice");
  if (!notice) return;
  notice.textContent = message;
  notice.dataset.kind = kind;
  notice.hidden = false;
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.dataset.visible = "true";
  globalThis.setTimeout(() => delete toast.dataset.visible, 2400);
}

function renderState(state, heading, detail, retry = false) {
  const view = document.querySelector("#case-view");
  if (!view) return;
  view.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  view.innerHTML = `<div class="state-panel" data-state="${state}">
    <p class="ps-eyebrow">${escapeHtml(state.toUpperCase())}</p>
    <h2>${escapeHtml(heading)}</h2><p>${escapeHtml(detail)}</p>
    ${retry ? '<button class="ps-button" type="button" data-retry>Try again</button>' : ""}
  </div>`;
  view.querySelector("[data-retry]")?.addEventListener("click", () => route(false));
}

function suburbLabels(item) {
  const suburbs = Array.isArray(item.target_suburbs) ? item.target_suburbs : [];
  if (!suburbs.length) return '<li class="ps-badge">No target suburbs</li>';
  return suburbs
    .map((suburb) => `<li class="ps-badge">${escapeHtml(suburb.locality)}, ${escapeHtml(suburb.state)}</li>`)
    .join("");
}

function preferenceList(items, emptyLabel) {
  if (!items.length) return `<li class="ps-badge">${escapeHtml(emptyLabel)}</li>`;
  return items.map((item) => `<li class="ps-badge">${escapeHtml(item)}</li>`).join("");
}

function renderList() {
  const view = document.querySelector("#case-view");
  if (!view) return;
  view.setAttribute("aria-busy", "false");
  if (!cases.length) {
    renderState("empty", "No buyer cases yet", "Create a case to organise a NSW property search.");
    return;
  }
  view.innerHTML = `<div class="case-grid">${cases
    .map(
      (item) => `<a class="ps-card ps-card__body case-card" href="#buyer-cases/${encodeURIComponent(item.id)}">
        <div><p class="ps-eyebrow">UPDATED ${escapeHtml(formatUpdated(item.updated_at))}</p>
        <h2>${escapeHtml(item.name)}</h2></div>
        <ul class="case-meta"><li class="ps-badge ${statusClass(item.status)}">${escapeHtml(statusLabel(item.status))}</li></ul>
        <p><strong>Budget:</strong> ${escapeHtml(formatBudget(item.budget_min_aud, item.budget_max_aud))}</p>
        <ul class="case-suburbs" aria-label="Target suburbs">${suburbLabels(item)}</ul>
      </a>`,
    )
    .join("")}</div>`;
}

function renderDetail(item) {
  const view = document.querySelector("#case-view");
  if (!view) return;
  const preferenceLists = projectPreferenceLists(item.preferences);
  view.setAttribute("aria-busy", "false");
  view.innerHTML = `<a class="back-link" href="#buyer-cases">← All buyer cases</a>
    <article class="ps-card ps-card__body" data-case-id="${escapeHtml(item.id)}">
      <header class="detail-heading"><div><p class="ps-eyebrow">BUYER CASE</p><h2>${escapeHtml(item.name)}</h2></div>
      <span class="ps-badge ${statusClass(item.status)}">${escapeHtml(statusLabel(item.status))}</span></header>
      <dl class="case-facts">
        <div><dt>Budget range</dt><dd>${escapeHtml(formatBudget(item.budget_min_aud, item.budget_max_aud))}</dd></div>
        <div><dt>Last updated</dt><dd>${escapeHtml(formatUpdated(item.updated_at))}</dd></div>
        <div><dt>Status</dt><dd>${escapeHtml(statusLabel(item.status))}</dd></div>
        <div><dt>Target suburbs</dt><dd>${escapeHtml((item.target_suburbs || []).map((suburb) => `${suburb.locality}, ${suburb.state}`).join("; ") || "Not set")}</dd></div>
      </dl>
      <section class="preference-section" aria-labelledby="preference-heading">
        <h3 id="preference-heading">Buyer preferences</h3>
        <div class="preference-grid">
          <div><h4>Dwelling types</h4><ul class="case-suburbs">${preferenceList(preferenceLists.dwellingTypes, "No dwelling types set")}</ul></div>
          <div><h4>Practical priorities</h4><ul class="case-suburbs">${preferenceList(preferenceLists.priorities, "No priorities set")}</ul></div>
        </div>
      </section>
      <div class="detail-actions"><button class="ps-button" type="button" data-edit>Edit case</button>
      <button class="ps-button ps-button--danger" type="button" data-delete>Delete case</button></div>
    </article>`;
  view.querySelector("[data-edit]")?.addEventListener("click", () => openCaseForm(item));
  view.querySelector("[data-delete]")?.addEventListener("click", () => openDeleteDialog(item));
}

async function loadList() {
  renderState("loading", "Loading buyer cases…", "Please wait while saved cases are retrieved.");
  try {
    const payload = await api.list();
    cases = Array.isArray(payload.items) ? payload.items : [];
    renderList();
    setServiceState(true);
  } catch (error) {
    setServiceState(false);
    renderState("unavailable", "Buyer cases are unavailable", "The service could not be reached. Your browser has not changed any cases.", true);
  }
}

async function loadDetail(caseId) {
  renderState("loading", "Loading buyer case…", "Please wait while the case is retrieved.");
  try {
    const item = await api.read(caseId);
    renderDetail(item);
    setServiceState(true);
  } catch (error) {
    setServiceState(false);
    const missing = error instanceof ApiProblem && error.status === 404;
    renderState(missing ? "empty" : "unavailable", missing ? "Buyer case not found" : "Buyer case unavailable", missing ? "It may have been deleted." : "The service could not be reached.", !missing);
  }
}

function setServiceState(online) {
  const state = document.querySelector("#service-state");
  if (!state) return;
  state.classList.toggle("online", online);
  state.classList.toggle("offline", !online);
  const label = state.querySelector("[data-service-label]");
  if (label) label.textContent = online ? "Buyer cases available" : "Buyer cases unavailable";
}

function fieldValue(selector) {
  return document.querySelector(selector)?.value || "";
}

function formValues() {
  return {
    name: fieldValue("#case-name"),
    budgetMin: fieldValue("#budget-min"),
    budgetMax: fieldValue("#budget-max"),
    suburbs: fieldValue("#target-suburbs"),
    dwellingTypes: fieldValue("#dwelling-types"),
    priorities: fieldValue("#practical-priorities"),
    status: fieldValue("#case-status") || "active",
  };
}

function setInputValue(selector, value) {
  const input = document.querySelector(selector);
  if (input) input.value = value == null ? "" : String(value);
}

function clearErrors() {
  document.querySelectorAll(".field-error, #form-error").forEach((item) => {
    item.hidden = true;
    item.textContent = "";
  });
  document.querySelectorAll('[aria-invalid="true"]').forEach((item) => item.removeAttribute("aria-invalid"));
}

function showFieldErrors(errors) {
  clearErrors();
  const mappings = {
    name: ["#case-name", "#case-name-error"],
    budget: ["#budget-min", "#budget-error"],
    suburbs: ["#target-suburbs", "#suburb-error"],
    preferences: ["#dwelling-types", "#preference-error"],
  };
  Object.entries(errors).forEach(([field, message]) => {
    const mapping = mappings[field];
    if (!mapping) return;
    document.querySelector(mapping[0])?.setAttribute("aria-invalid", "true");
    const error = document.querySelector(mapping[1]);
    if (error) {
      error.textContent = message;
      error.hidden = false;
    }
  });
  const first = document.querySelector('[aria-invalid="true"]');
  if (first) first.focus();
}

function openCaseForm(item = null) {
  editingCase = item;
  clearErrors();
  const dialog = document.querySelector("#case-dialog");
  const title = document.querySelector("#case-dialog-title");
  if (!dialog || !title) return;
  title.textContent = item ? "Edit buyer case" : "Create buyer case";
  setInputValue("#case-name", item?.name);
  setInputValue("#budget-min", item?.budget_min_aud);
  setInputValue("#budget-max", item?.budget_max_aud);
  setInputValue("#target-suburbs", (item?.target_suburbs || []).map((suburb) => suburb.locality).join("\n"));
  const preferenceLists = projectPreferenceLists(item?.preferences);
  setInputValue("#dwelling-types", preferenceLists.dwellingTypes.join("\n"));
  setInputValue("#practical-priorities", preferenceLists.priorities.join("\n"));
  setInputValue("#case-status", item?.status || "active");
  dialog.showModal();
  document.querySelector("#case-name")?.focus();
}

function closeCaseForm() {
  const dialog = document.querySelector("#case-dialog");
  if (dialog?.open) dialog.close();
  editingCase = null;
}

function showFormProblem(error) {
  const message = document.querySelector("#form-error");
  if (!message) return;
  const state = uiStateForError(error);
  message.dataset.state = state;
  message.textContent = state === "conflict"
    ? "This buyer case changed elsewhere. Close the form, reload the case and try again."
    : state === "invalid"
      ? error.message
      : "The buyer case service is unavailable. Your changes were not saved.";
  message.hidden = false;
  message.focus();
}

async function submitCase(event) {
  event.preventDefault();
  const built = buildCasePayload(
    formValues(),
    editingCase?.version ?? null,
    editingCase?.preferences || {},
  );
  if (built.payload === null) {
    showFieldErrors(built.errors);
    return;
  }
  clearErrors();
  const button = document.querySelector("#save-case");
  if (button) button.disabled = true;
  const wasEditing = editingCase !== null;
  try {
    const saved = editingCase
      ? await api.update(editingCase.id, built.payload)
      : await api.create(built.payload);
    closeCaseForm();
    showNotice(wasEditing ? "Buyer case updated." : "Buyer case created.");
    showToast(wasEditing ? "Buyer case updated." : "Buyer case created.");
    await navigateForFollowUp(
      `#buyer-cases/${encodeURIComponent(saved.id)}`,
      location.hash,
      (target) => { location.hash = target; },
      () => route(false),
    );
  } catch (error) {
    showFormProblem(error);
  } finally {
    if (button) button.disabled = false;
  }
}

function openDeleteDialog(item) {
  deletingCase = item;
  const dialog = document.querySelector("#delete-dialog");
  const copy = document.querySelector("#delete-copy");
  if (!dialog || !copy) return;
  copy.textContent = `Delete “${item.name}”? This action cannot be undone.`;
  dialog.showModal();
  document.querySelector("#confirm-delete")?.focus();
}

function closeDeleteDialog() {
  const dialog = document.querySelector("#delete-dialog");
  if (dialog?.open) dialog.close();
  deletingCase = null;
}

async function confirmDelete() {
  if (!deletingCase) return;
  const button = document.querySelector("#confirm-delete");
  if (button) button.disabled = true;
  try {
    await api.delete(deletingCase.id);
    closeDeleteDialog();
    showNotice("Buyer case deleted.");
    showToast("Buyer case deleted.");
    await navigateForFollowUp(
      "#buyer-cases",
      location.hash,
      (target) => { location.hash = target; },
      () => route(false),
    );
  } catch (error) {
    closeDeleteDialog();
    showNotice("The buyer case could not be deleted. Please reload and try again.", "error");
  } finally {
    if (button) button.disabled = false;
  }
}

async function route(focus = true) {
  const parsed = parseRoute(location.hash);
  if (parsed.name === "detail") await loadDetail(parsed.id);
  else await loadList();
  if (focus) document.querySelector("#main-content")?.focus();
}

export function initialise() {
  document.querySelector("#new-case")?.addEventListener("click", () => openCaseForm());
  document.querySelector("#case-form")?.addEventListener("submit", submitCase);
  document.querySelectorAll("[data-close-case]").forEach((button) => button.addEventListener("click", closeCaseForm));
  document.querySelectorAll("[data-close-delete]").forEach((button) => button.addEventListener("click", closeDeleteDialog));
  document.querySelector("#confirm-delete")?.addEventListener("click", confirmDelete);
  globalThis.addEventListener("hashchange", () => route());
  route(false);
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", initialise);
}
