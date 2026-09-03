export const API_BASE = "/api/buyer-workspaces/v1";
export const MAX_PREFERENCE_ITEMS = 20;
export const MAX_PREFERENCE_TEXT_LENGTH = 100;
export const JOURNEY_STAGES = ["Shortlisted", "Inspecting", "Reviewing", "Offer Considered", "Closed"];
export const PROPERTY_PRIORITIES = ["low", "medium", "high"];

export class ApiProblem extends Error {
  constructor(status, code, detail) {
    super(detail || `Request failed with status ${status}.`);
    this.name = "ApiProblem";
    this.status = status;
    this.code = code || "request_failed";
  }
}

export function createBuyerCaseApi(fetchImpl = globalThis.fetch) {
  async function request(method, path, body, extraHeaders = {}) {
    const options = { method, headers: { Accept: "application/json", ...extraHeaders } };
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

  function childApi(resource) {
    return {
      list: (caseId) => request("GET", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}?page=1&page_size=100`),
      create: (caseId, values) => request("POST", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}`, values),
      read: (caseId, childId) => request("GET", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}/${encodeURIComponent(childId)}`),
      update: (caseId, childId, values) => request("PUT", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}/${encodeURIComponent(childId)}`, values),
      delete: (caseId, childId) => request("DELETE", `/buyer-cases/${encodeURIComponent(caseId)}/${resource}/${encodeURIComponent(childId)}`),
    };
  }

  return {
    list: (page = 1, pageSize = 100) => request("GET", `/buyer-cases?page=${page}&page_size=${pageSize}`),
    create: (values) => request("POST", "/buyer-cases", values),
    read: (caseId) => request("GET", `/buyer-cases/${encodeURIComponent(caseId)}`),
    update: (caseId, values) => request("PUT", `/buyer-cases/${encodeURIComponent(caseId)}`, values),
    delete: (caseId) => request("DELETE", `/buyer-cases/${encodeURIComponent(caseId)}`),
    properties: childApi("properties"),
    notes: childApi("notes"),
    tasks: childApi("tasks"),
    evidence: (caseId) => request("GET", `/buyer-cases/${encodeURIComponent(caseId)}/evidence`),
    summaries: {
      create: (caseId, idempotencyKey) => request(
        "POST",
        `/buyer-cases/${encodeURIComponent(caseId)}/case-summary-runs`,
        {},
        { "Idempotency-Key": idempotencyKey },
      ),
      read: (caseId, runId) => request(
        "GET",
        `/buyer-cases/${encodeURIComponent(caseId)}/case-summary-runs/${encodeURIComponent(runId)}`,
      ),
    },
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

function optionalInteger(value) {
  return value === "" || value == null ? null : Number(value);
}

export function buildPropertyPayload(values, version = null) {
  const errors = {};
  const propertyRef = String(values.propertyRef || "").trim();
  const label = String(values.propertyLabel || "").trim();
  const rating = optionalInteger(values.rating);
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(propertyRef)) {
    errors.propertyRef = "Enter a valid property reference UUID.";
  }
  if (label.length > 500) errors.propertyLabel = "Property label must contain at most 500 characters.";
  if (!JOURNEY_STAGES.includes(values.journeyStage || "Shortlisted")) errors.journeyStage = "Choose a supported journey stage.";
  if (rating !== null && (!Number.isInteger(rating) || rating < 1 || rating > 5)) errors.rating = "Rating must be empty or from 1 to 5.";
  if (!PROPERTY_PRIORITIES.includes(values.priority || "medium")) errors.priority = "Choose a supported priority.";
  if (Object.keys(errors).length) return { errors, payload: null };
  const payload = {
    property_label: label || null,
    journey_stage: values.journeyStage || "Shortlisted",
    rating,
    priority: values.priority || "medium",
  };
  if (version === null) payload.property_ref = propertyRef;
  else payload.version = version;
  return { errors: {}, payload };
}

export function buildNotePayload(values, version = null) {
  const content = String(values.content || "").trim();
  const errors = {};
  if (!content) errors.note = "Enter note content.";
  if (content.length > 4000) errors.note = "Note content must contain at most 4000 characters.";
  const payload = { case_property_id: values.propertyId || null, content };
  if (version !== null) payload.version = version;
  return { errors, payload: Object.keys(errors).length ? null : payload };
}

export function buildTaskPayload(values, version = null) {
  const title = String(values.title || "").trim();
  const dueDate = String(values.dueDate || "").trim();
  const errors = {};
  if (!title) errors.title = "Enter a task title.";
  if (title.length > 300) errors.title = "Task title must contain at most 300 characters.";
  if (dueDate && !/^\d{4}-\d{2}-\d{2}$/.test(dueDate)) errors.dueDate = "Enter a valid due date.";
  const payload = {
    case_property_id: values.propertyId || null,
    title,
    due_date: dueDate || null,
    completed: Boolean(values.completed),
  };
  if (version !== null) payload.version = version;
  return { errors, payload: Object.keys(errors).length ? null : payload };
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
let currentCase = null;
let properties = [];
let notes = [];
let tasks = [];
let editingCase = null;
let editingProperty = null;
let editingNote = null;
let editingTask = null;
let pendingDelete = null;

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

function propertyName(propertyId) {
  const item = properties.find((property) => property.id === propertyId);
  return item ? item.property_label || item.property_ref : "Whole buyer case";
}

export function renderPropertyItems(items) {
  if (!items.length) return '<p class="empty-inline">No shortlisted properties yet.</p>';
  return items.map((property) => `<article class="workspace-item" data-property-id="${escapeHtml(property.id)}">
    <div><h4>${escapeHtml(property.property_label || property.property_ref)}</h4>
    <p class="item-reference">${escapeHtml(property.property_ref)}</p></div>
    <ul class="case-meta"><li class="ps-badge">${escapeHtml(property.journey_stage)}</li><li class="ps-badge">${escapeHtml(property.priority)} priority</li><li class="ps-badge">${property.rating == null ? "Not rated" : `${property.rating}/5`}</li><li class="ps-badge">${escapeHtml(property.property_validation_state)}</li></ul>
    <div class="item-actions"><button class="ps-button" type="button" data-edit-property="${escapeHtml(property.id)}">Edit journey</button><button class="ps-button ps-button--danger" type="button" data-delete-property="${escapeHtml(property.id)}">Remove</button></div>
  </article>`).join("");
}

export function renderNoteItems(items, propertyLabel = () => "Whole buyer case") {
  if (!items.length) return '<p class="empty-inline">No notes recorded yet.</p>';
  return items.map((note) => `<article class="workspace-item" data-note-id="${escapeHtml(note.id)}">
    <p>${escapeHtml(note.content)}</p><p class="item-reference">Related to: ${escapeHtml(propertyLabel(note.case_property_id))}</p>
    <div class="item-actions"><button class="ps-button" type="button" data-edit-note="${escapeHtml(note.id)}">Edit note</button><button class="ps-button ps-button--danger" type="button" data-delete-note="${escapeHtml(note.id)}">Delete</button></div>
  </article>`).join("");
}

export function renderTaskItems(items, propertyLabel = () => "Whole buyer case") {
  if (!items.length) return '<p class="empty-inline">No tasks recorded yet.</p>';
  return items.map((task) => `<article class="workspace-item${task.completed ? " is-complete" : ""}" data-task-id="${escapeHtml(task.id)}">
    <div><h4>${escapeHtml(task.title)}</h4><p>Due: ${escapeHtml(task.due_date || "No due date")}</p><p class="item-reference">Related to: ${escapeHtml(propertyLabel(task.case_property_id))}</p></div>
    <div class="item-actions"><button class="ps-button" type="button" data-complete-task="${escapeHtml(task.id)}">${task.completed ? "Mark incomplete" : "Mark complete"}</button><button class="ps-button" type="button" data-edit-task="${escapeHtml(task.id)}">Edit task</button><button class="ps-button ps-button--danger" type="button" data-delete-task="${escapeHtml(task.id)}">Delete</button></div>
  </article>`).join("");
}

export function evidenceStateLabel(state) {
  return {
    complete: "Complete", partial: "Partial", unavailable: "Unavailable",
    needs_verification: "Needs verification", conflicting: "Conflicting",
  }[state] || "Unavailable";
}

export function renderEvidence(value) {
  const sections = value?.sections && typeof value.sections === "object" ? value.sections : {};
  const titles = {
    feature_1: "Property identity and source releases",
    feature_2: "Market evidence",
    feature_3: "Feature 3 evidence",
    feature_4: "Due diligence evidence",
  };
  const cards = Object.entries(titles).map(([key, title]) => {
    const section = sections[key] || { state: "unavailable", items: [], limitations: [] };
    const items = Array.isArray(section.items) ? section.items : [];
    const limitations = Array.isArray(section.limitations) ? section.limitations : [];
    return `<article class="evidence-card"><header><h4>${escapeHtml(title)}</h4><span class="ps-badge evidence-${escapeHtml(section.state)}">${escapeHtml(evidenceStateLabel(section.state))}</span></header>
      ${items.length ? `<ul>${items.map((item) => `<li><code>${escapeHtml(item.property_ref || "Unknown property")}</code> — ${escapeHtml(evidenceStateLabel(item.state))}${item.address_display ? `: ${escapeHtml(item.address_display)}` : ""}</li>`).join("")}</ul>` : "<p>No evidence records returned.</p>"}
      ${limitations.map((item) => `<p class="item-reference">${escapeHtml(item)}</p>`).join("")}</article>`;
  }).join("");
  const limitations = Array.isArray(value?.limitations) ? value.limitations : [];
  const references = Array.isArray(value?.evidence_references) ? value.evidence_references : [];
  return `${cards}<div class="evidence-references"><h4>Evidence references</h4>${references.length ? `<ul>${references.map((item) => `<li><code>${escapeHtml(item)}</code></li>`).join("")}</ul>` : "<p>No evidence references available.</p>"}</div>
    <div class="evidence-limitations"><h4>Evidence limitations</h4><ul>${limitations.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`;
}

export function renderSummaryRun(run) {
  const phases = Array.isArray(run?.phases) ? run.phases : [];
  const actions = Array.isArray(run?.suggested_next_actions) ? run.suggested_next_actions : [];
  const references = Array.isArray(run?.evidence_references) ? run.evidence_references : [];
  const limitations = Array.isArray(run?.limitations) ? run.limitations : [];
  return `<ol class="run-phases" aria-label="Plan Act Observe Adapt progress">${phases.map((phase) => `<li data-phase="${escapeHtml(phase.name)}"><strong>${escapeHtml(phase.name)}</strong><span>${escapeHtml(phase.status)}</span></li>`).join("")}</ol>
    ${run?.summary ? `<h4>Case summary</h4><p>${escapeHtml(run.summary)}</p>` : `<p>${run?.error ? escapeHtml(run.error) : "Summary generation is in progress."}</p>`}
    <h4>Suggested next actions</h4>${actions.length ? `<ol>${actions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>` : "<p>No suggested actions yet.</p>"}
    <h4>Evidence references</h4>${references.length ? `<ul>${references.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "<p>No AI evidence references yet. Review the bounded evidence above.</p>"}
    <h4>Limitations</h4>${limitations.length ? `<ul>${limitations.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "<p>No additional AI limitations reported.</p>"}`;
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
    </article>
    <section class="workspace-section" aria-labelledby="properties-heading"><header><div><p class="ps-eyebrow">SHORTLIST</p><h3 id="properties-heading">Properties</h3></div><button class="ps-button ps-button--primary" type="button" data-add-property>Add property</button></header><div class="workspace-items">${renderPropertyItems(properties)}</div></section>
    <section class="workspace-section" aria-labelledby="notes-heading"><header><div><p class="ps-eyebrow">OBSERVATIONS</p><h3 id="notes-heading">Notes</h3></div><button class="ps-button ps-button--primary" type="button" data-add-note>Add note</button></header><div class="workspace-items">${renderNoteItems(notes, propertyName)}</div></section>
    <section class="workspace-section" aria-labelledby="tasks-heading"><header><div><p class="ps-eyebrow">NEXT STEPS</p><h3 id="tasks-heading">Tasks</h3></div><button class="ps-button ps-button--primary" type="button" data-add-task>Add task</button></header><div class="workspace-items">${renderTaskItems(tasks, propertyName)}</div></section>
    <section class="workspace-section" aria-labelledby="evidence-heading"><header><div><p class="ps-eyebrow">CROSS-FEATURE EVIDENCE</p><h3 id="evidence-heading">Bounded evidence</h3></div><button class="ps-button" type="button" data-refresh-evidence>Refresh evidence</button></header><div data-evidence aria-live="polite"><p>Loading evidence…</p></div></section>
    <section class="workspace-section" aria-labelledby="summary-heading"><header><div><p class="ps-eyebrow">AI ASSISTANCE</p><h3 id="summary-heading">Buyer case summary</h3></div><button class="ps-button ps-button--primary" type="button" data-generate-summary>Generate case summary</button></header><p class="item-reference">AI output is advisory. Confirm evidence and important decisions yourself.</p><div data-summary-run aria-live="polite"><p>No AI summary has been generated.</p></div></section>`;
  view.querySelector("[data-edit]")?.addEventListener("click", () => openCaseForm(item));
  view.querySelector("[data-delete]")?.addEventListener("click", () => openDeleteDialog(`buyer case “${item.name}”`, () => api.delete(item.id), "#buyer-cases"));
  view.querySelector("[data-add-property]")?.addEventListener("click", () => openPropertyForm());
  view.querySelector("[data-add-note]")?.addEventListener("click", () => openNoteForm());
  view.querySelector("[data-add-task]")?.addEventListener("click", () => openTaskForm());
  view.querySelector("[data-refresh-evidence]")?.addEventListener("click", () => loadEvidence(item.id));
  view.querySelector("[data-generate-summary]")?.addEventListener("click", () => generateSummary(item.id));
  view.querySelectorAll("[data-edit-property]").forEach((button) => button.addEventListener("click", () => openPropertyForm(properties.find((value) => value.id === button.dataset.editProperty))));
  view.querySelectorAll("[data-delete-property]").forEach((button) => button.addEventListener("click", () => {
    const property = properties.find((value) => value.id === button.dataset.deleteProperty);
    if (property) openDeleteDialog("shortlisted property", () => api.properties.delete(item.id, property.id));
  }));
  view.querySelectorAll("[data-edit-note]").forEach((button) => button.addEventListener("click", () => openNoteForm(notes.find((value) => value.id === button.dataset.editNote))));
  view.querySelectorAll("[data-delete-note]").forEach((button) => button.addEventListener("click", () => {
    const note = notes.find((value) => value.id === button.dataset.deleteNote);
    if (note) openDeleteDialog("note", () => api.notes.delete(item.id, note.id));
  }));
  view.querySelectorAll("[data-edit-task]").forEach((button) => button.addEventListener("click", () => openTaskForm(tasks.find((value) => value.id === button.dataset.editTask))));
  view.querySelectorAll("[data-complete-task]").forEach((button) => button.addEventListener("click", () => toggleTask(button.dataset.completeTask)));
  view.querySelectorAll("[data-delete-task]").forEach((button) => button.addEventListener("click", () => {
    const task = tasks.find((value) => value.id === button.dataset.deleteTask);
    if (task) openDeleteDialog("task", () => api.tasks.delete(item.id, task.id));
  }));
}

async function loadEvidence(caseId) {
  const target = document.querySelector("[data-evidence]");
  if (!target) return;
  target.innerHTML = "<p>Loading bounded evidence…</p>";
  try {
    const value = await api.evidence(caseId);
    if (currentCase?.id === caseId) target.innerHTML = renderEvidence(value);
  } catch (error) {
    if (currentCase?.id === caseId) target.innerHTML = '<div data-state="unavailable"><p>Evidence services are unavailable. Buyer-case editing is still available.</p></div>';
  }
}

async function pollSummary(caseId, runId) {
  const target = document.querySelector("[data-summary-run]");
  if (!target || currentCase?.id !== caseId) return;
  try {
    const run = await api.summaries.read(caseId, runId);
    target.innerHTML = renderSummaryRun(run);
    if (!["succeeded", "failed", "cancelled"].includes(run.status)) {
      globalThis.setTimeout(() => pollSummary(caseId, runId), 1000);
    }
  } catch (error) {
    target.innerHTML = '<div data-state="unavailable"><p>AI summary service is unavailable. Your buyer case is unchanged.</p></div>';
  }
}

async function generateSummary(caseId) {
  const target = document.querySelector("[data-summary-run]");
  const button = document.querySelector("[data-generate-summary]");
  if (!target || !button) return;
  button.disabled = true;
  target.innerHTML = "<p>Starting the Plan → Act → Observe → Adapt workflow…</p>";
  try {
    const key = `buyer-summary-${caseId}-${Date.now()}`;
    const run = await api.summaries.create(caseId, key);
    target.innerHTML = renderSummaryRun(run);
    if (!["succeeded", "failed", "cancelled"].includes(run.status)) await pollSummary(caseId, run.id);
  } catch (error) {
    target.innerHTML = '<div data-state="unavailable"><p>AI summary service is unavailable. Ordinary case, property, note and task controls remain available.</p></div>';
  } finally {
    button.disabled = false;
  }
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
    const [item, propertyPage, notePage, taskPage] = await Promise.all([
      api.read(caseId), api.properties.list(caseId), api.notes.list(caseId), api.tasks.list(caseId),
    ]);
    currentCase = item;
    properties = propertyPage.items;
    notes = notePage.items;
    tasks = taskPage.items;
    renderDetail(item);
    setServiceState(true);
    void loadEvidence(caseId);
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
  document.querySelectorAll(".field-error, .form-message").forEach((item) => {
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

function propertyOptions(selectedId) {
  return `<option value="">Whole buyer case</option>${properties.map((property) => `<option value="${escapeHtml(property.id)}"${property.id === selectedId ? " selected" : ""}>${escapeHtml(property.property_label || property.property_ref)}</option>`).join("")}`;
}

function showChildErrors(errors, mappings, errorId) {
  clearErrors();
  const fieldName = Object.keys(errors)[0];
  const message = errors[fieldName];
  if (!message) return;
  const field = mappings[fieldName];
  document.querySelector(field)?.setAttribute("aria-invalid", "true");
  const error = document.querySelector(errorId);
  if (error) { error.textContent = message; error.hidden = false; }
  document.querySelector(field)?.focus();
}

function showChildProblem(selector, error) {
  const message = document.querySelector(selector);
  if (!message) return;
  const state = uiStateForError(error);
  message.dataset.state = state;
  message.textContent = state === "conflict"
    ? "This record changed elsewhere. Reload the buyer case and try again."
    : state === "invalid" ? error.message : "The buyer case service is unavailable. Changes were not saved.";
  message.hidden = false;
  message.focus();
}

async function reloadCurrentDetail(message) {
  showNotice(message);
  showToast(message);
  await route(false);
}

function openPropertyForm(item = null) {
  editingProperty = item || null;
  clearErrors();
  document.querySelector("#property-dialog-title").textContent = item ? "Edit shortlisted property" : "Add shortlisted property";
  setInputValue("#property-ref", item?.property_ref);
  document.querySelector("#property-ref").disabled = Boolean(item);
  setInputValue("#property-label", item?.property_label);
  setInputValue("#journey-stage", item?.journey_stage || "Shortlisted");
  setInputValue("#property-rating", item?.rating);
  setInputValue("#property-priority", item?.priority || "medium");
  document.querySelector("#property-dialog")?.showModal();
  document.querySelector(item ? "#property-label" : "#property-ref")?.focus();
}

function closePropertyForm() {
  const dialog = document.querySelector("#property-dialog");
  if (dialog?.open) dialog.close();
  editingProperty = null;
}

async function submitProperty(event) {
  event.preventDefault();
  if (!currentCase) return;
  const built = buildPropertyPayload({
    propertyRef: fieldValue("#property-ref"), propertyLabel: fieldValue("#property-label"),
    journeyStage: fieldValue("#journey-stage"), rating: fieldValue("#property-rating"),
    priority: fieldValue("#property-priority"),
  }, editingProperty?.version ?? null);
  if (!built.payload) {
    showChildErrors(built.errors, { propertyRef: "#property-ref", propertyLabel: "#property-label", journeyStage: "#journey-stage", rating: "#property-rating", priority: "#property-priority" }, "#property-error");
    return;
  }
  try {
    if (editingProperty) await api.properties.update(currentCase.id, editingProperty.id, built.payload);
    else await api.properties.create(currentCase.id, built.payload);
    const message = editingProperty ? "Shortlisted property updated." : "Property added to shortlist.";
    closePropertyForm();
    await reloadCurrentDetail(message);
  } catch (error) { showChildProblem("#property-form-error", error); }
}

function openNoteForm(item = null) {
  editingNote = item || null;
  clearErrors();
  document.querySelector("#note-dialog-title").textContent = item ? "Edit note" : "Add note";
  document.querySelector("#note-property").innerHTML = propertyOptions(item?.case_property_id);
  setInputValue("#note-content", item?.content);
  document.querySelector("#note-dialog")?.showModal();
  document.querySelector("#note-content")?.focus();
}

function closeNoteForm() {
  const dialog = document.querySelector("#note-dialog");
  if (dialog?.open) dialog.close();
  editingNote = null;
}

async function submitNote(event) {
  event.preventDefault();
  if (!currentCase) return;
  const built = buildNotePayload({ content: fieldValue("#note-content"), propertyId: fieldValue("#note-property") }, editingNote?.version ?? null);
  if (!built.payload) { showChildErrors(built.errors, { note: "#note-content" }, "#note-error"); return; }
  try {
    if (editingNote) await api.notes.update(currentCase.id, editingNote.id, built.payload);
    else await api.notes.create(currentCase.id, built.payload);
    const message = editingNote ? "Note updated." : "Note added.";
    closeNoteForm();
    await reloadCurrentDetail(message);
  } catch (error) { showChildProblem("#note-form-error", error); }
}

function openTaskForm(item = null) {
  editingTask = item || null;
  clearErrors();
  document.querySelector("#task-dialog-title").textContent = item ? "Edit task" : "Add task";
  document.querySelector("#task-property").innerHTML = propertyOptions(item?.case_property_id);
  setInputValue("#task-title", item?.title);
  setInputValue("#task-due-date", item?.due_date);
  document.querySelector("#task-completed").checked = Boolean(item?.completed);
  document.querySelector("#task-dialog")?.showModal();
  document.querySelector("#task-title")?.focus();
}

function closeTaskForm() {
  const dialog = document.querySelector("#task-dialog");
  if (dialog?.open) dialog.close();
  editingTask = null;
}

async function submitTask(event) {
  event.preventDefault();
  if (!currentCase) return;
  const built = buildTaskPayload({ title: fieldValue("#task-title"), dueDate: fieldValue("#task-due-date"), propertyId: fieldValue("#task-property"), completed: document.querySelector("#task-completed")?.checked }, editingTask?.version ?? null);
  if (!built.payload) { showChildErrors(built.errors, { title: "#task-title", dueDate: "#task-due-date" }, "#task-error"); return; }
  try {
    if (editingTask) await api.tasks.update(currentCase.id, editingTask.id, built.payload);
    else await api.tasks.create(currentCase.id, built.payload);
    const message = editingTask ? "Task updated." : "Task added.";
    closeTaskForm();
    await reloadCurrentDetail(message);
  } catch (error) { showChildProblem("#task-form-error", error); }
}

async function toggleTask(taskId) {
  const task = tasks.find((value) => value.id === taskId);
  if (!task || !currentCase) return;
  try {
    await api.tasks.update(currentCase.id, task.id, { version: task.version, completed: !task.completed });
    await reloadCurrentDetail(task.completed ? "Task marked incomplete." : "Task completed.");
  } catch (error) { showNotice(uiStateForError(error) === "conflict" ? "Task changed elsewhere. Reload and try again." : "Task could not be updated.", "error"); }
}

function openDeleteDialog(label, execute, targetHash = null) {
  pendingDelete = { execute, targetHash };
  const dialog = document.querySelector("#delete-dialog");
  const copy = document.querySelector("#delete-copy");
  if (!dialog || !copy) return;
  copy.textContent = `Delete ${label}? This action cannot be undone.`;
  dialog.showModal();
  document.querySelector("#confirm-delete")?.focus();
}

function closeDeleteDialog() {
  const dialog = document.querySelector("#delete-dialog");
  if (dialog?.open) dialog.close();
  pendingDelete = null;
}

async function confirmDelete() {
  if (!pendingDelete) return;
  const button = document.querySelector("#confirm-delete");
  if (button) button.disabled = true;
  try {
    const operation = pendingDelete;
    await operation.execute();
    closeDeleteDialog();
    showNotice("Record deleted.");
    showToast("Record deleted.");
    await navigateForFollowUp(
      operation.targetHash || location.hash,
      location.hash,
      (target) => { location.hash = target; },
      () => route(false),
    );
  } catch (error) {
    closeDeleteDialog();
    showNotice("The record could not be deleted. Please reload and try again.", "error");
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
  document.querySelector("#property-form")?.addEventListener("submit", submitProperty);
  document.querySelector("#note-form")?.addEventListener("submit", submitNote);
  document.querySelector("#task-form")?.addEventListener("submit", submitTask);
  document.querySelectorAll("[data-close-case]").forEach((button) => button.addEventListener("click", closeCaseForm));
  document.querySelectorAll("[data-close-property]").forEach((button) => button.addEventListener("click", closePropertyForm));
  document.querySelectorAll("[data-close-note]").forEach((button) => button.addEventListener("click", closeNoteForm));
  document.querySelectorAll("[data-close-task]").forEach((button) => button.addEventListener("click", closeTaskForm));
  document.querySelectorAll("[data-close-delete]").forEach((button) => button.addEventListener("click", closeDeleteDialog));
  document.querySelector("#confirm-delete")?.addEventListener("click", confirmDelete);
  globalThis.addEventListener("hashchange", () => route());
  route(false);
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", initialise);
}
