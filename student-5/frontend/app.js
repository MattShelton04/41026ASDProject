import { createLatestTask, pollUntilSettled } from "./browser/index.js";

import {
  API_BASE,
  MAX_PREFERENCE_ITEMS,
  MAX_PREFERENCE_TEXT_LENGTH,
  JOURNEY_STAGES,
  PROPERTY_PRIORITIES,
  ApiProblem,
  createBuyerCaseApi,
} from "./api.js";
export {
  API_BASE,
  MAX_PREFERENCE_ITEMS,
  MAX_PREFERENCE_TEXT_LENGTH,
  JOURNEY_STAGES,
  PROPERTY_PRIORITIES,
  ApiProblem,
  createBuyerCaseApi,
} from "./api.js";

import {
  statusLabel,
  statusClass,
  formatBudget,
  formatUpdated,
  targetSuburbsFromText,
  preferenceStringsFromText,
  projectPreferenceLists,
  mergePreferences,
  validateCaseInput,
  buildCasePayload,
  buildPropertyPayload,
  buildNotePayload,
  buildTaskPayload,
  parseRoute,
  navigateForFollowUp,
  uiStateForError,
  escapeHtml,
} from "./models.js";
export {
  statusLabel,
  statusClass,
  formatBudget,
  formatUpdated,
  targetSuburbsFromText,
  preferenceStringsFromText,
  projectPreferenceLists,
  mergePreferences,
  validateCaseInput,
  buildCasePayload,
  buildPropertyPayload,
  buildNotePayload,
  buildTaskPayload,
  parseRoute,
  navigateForFollowUp,
  uiStateForError,
  escapeHtml,
} from "./models.js";

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
const viewTask = createLatestTask();
const summaryTask = createLatestTask();
const evidenceTask = createLatestTask();
let toastTimer;

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
  clearTimeout(toastTimer);
  toastTimer = globalThis.setTimeout(() => delete toast.dataset.visible, 2400);
}

function renderState(state, heading, detail, retry = false) {
  const view = document.querySelector("#case-view");
  if (!view) return;
  view.setAttribute("aria-busy", state === "loading" ? "true" : "false");
  view.innerHTML = `<div class="state-panel" data-state="${state}">
    <p class="ps-eyebrow">${escapeHtml(state.toUpperCase())}</p>
    <h2>${escapeHtml(heading)}</h2><p>${escapeHtml(detail)}</p>
    ${state === "loading" ? '<div class="ps-skeleton-lines" aria-hidden="true"><span class="ps-skeleton"></span><span class="ps-skeleton"></span><span class="ps-skeleton"></span></div>' : ""}
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
    <details class="item-reference"><summary>Property reference</summary><code>${escapeHtml(property.property_ref)}</code></details></div>
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
    feature_3: "Suburb analytics evidence",
    feature_4: "Due diligence evidence",
  };
  const cards = Object.entries(titles).map(([key, title]) => {
    const section = sections[key] || { state: "unavailable", items: [], limitations: [] };
    const items = Array.isArray(section.items) ? section.items : [];
    const limitations = Array.isArray(section.limitations) ? section.limitations : [];
    const visibleLimitations = limitations.map((item) => key === "feature_3" && item === "Feature 3 has no available Release 0 public API." ? "No suburb evidence was returned to this buyer case." : item);
    return `<article class="evidence-card"><header><h4>${escapeHtml(title)}</h4><span class="ps-badge evidence-${escapeHtml(section.state)}">${escapeHtml(evidenceStateLabel(section.state))}</span></header>
      ${items.length ? `<ul>${items.map((item) => `<li>${escapeHtml(item.address_display || item.property_ref || "Unknown property")} · ${escapeHtml(evidenceStateLabel(item.state))}</li>`).join("")}</ul>` : "<p>No evidence records returned.</p>"}
      ${visibleLimitations.map((item) => `<p class="item-reference">${escapeHtml(item)}</p>`).join("")}</article>`;
  }).join("");
  const limitations = Array.isArray(value?.limitations) ? value.limitations : [];
  const references = Array.isArray(value?.evidence_references) ? value.evidence_references : [];
  return `${cards}<details class="evidence-references"><summary>Evidence references</summary>${references.length ? `<ul>${references.map((item) => `<li><code>${escapeHtml(item)}</code></li>`).join("")}</ul>` : "<p>No evidence references available.</p>"}</details>
    <div class="evidence-limitations"><h4>Evidence limitations</h4><ul>${limitations.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`;
}

function workflowPhaseLabel(value) {
  const label = String(value || "").replaceAll("_", " ");
  return label ? `${label[0].toUpperCase()}${label.slice(1)}` : "Pending";
}

export function summaryWorkflowView(run) {
  const status = typeof run?.status === "string" ? run.status : "";
  const phases = Array.isArray(run?.phases) ? run.phases : [];
  let statusText = "Generating case summary";

  if (!status) {
    statusText = "Ready to generate a case summary.";
  } else if (status === "succeeded") {
    statusText = "Case summary generated successfully.";
  } else if (["failed", "cancelled"].includes(status)) {
    const failedPhase = phases.find((phase) => phase?.status === "failed")?.name;
    statusText = failedPhase
      ? `The case summary could not be generated: ${workflowPhaseLabel(failedPhase)} failed.`
      : "The case summary could not be generated.";
  }

  if (status === "cancelled") statusText = "Case summary cancelled. Your saved case is unchanged.";
  if (["review_required", "waiting_for_review"].includes(status)) statusText = "The workflow requires human review; no final summary is available.";
  return { statusText };
}

export function renderSummaryRun(run, workflowView = summaryWorkflowView(run)) {
  const phases = Array.isArray(run?.phases) ? run.phases : [];
  const actions = Array.isArray(run?.suggested_next_actions) ? run.suggested_next_actions : [];
  const evidenceUsed = Array.isArray(run?.evidence_used) ? run.evidence_used : [];
  const references = Array.isArray(run?.evidence_references) ? run.evidence_references : [];
  const limitations = Array.isArray(run?.limitations) ? run.limitations : [];
  if (!run?.status) return `<p class="workflow-status" role="status" aria-live="polite" data-workflow-status>${escapeHtml(workflowView.statusText)}</p>`;
  return `<p class="workflow-status" role="status" aria-live="polite" data-workflow-status>${escapeHtml(workflowView.statusText)}</p>
    ${phases.length ? `<ol class="workflow-phases" aria-label="Recorded workflow phases">${phases.map(phase => `<li><strong>${escapeHtml(workflowPhaseLabel(phase.name))}</strong><span>${escapeHtml(workflowPhaseLabel(phase.status))}</span></li>`).join("")}</ol>` : ""}
    ${run?.summary ? `<h4>Case summary</h4><p>${escapeHtml(run.summary)}</p>` : `<p>${run?.error ? escapeHtml(run.error) : "Summary generation is in progress."}</p>`}
    <h4>Suggested next actions</h4>${actions.length ? `<ol>${actions.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ol>` : "<p>No suggested actions yet.</p>"}
    <h4>Evidence used</h4>${evidenceUsed.length ? `<ul>${evidenceUsed.map((item) => `<li><strong>${escapeHtml(item?.label || "Evidence source")}</strong>: ${escapeHtml(item?.status || "Unavailable")}${item?.detail ? `; ${escapeHtml(item.detail)}` : ""}</li>`).join("")}</ul>` : "<p>No evidence summary is available. Review the bounded evidence above.</p>"}
    <details class="technical-audit"><summary>Technical audit references</summary>${references.length ? `<ul>${references.map((item) => `<li><code>${escapeHtml(item)}</code></li>`).join("")}</ul>` : "<p>No technical references reported.</p>"}</details>
    <h4>Limitations</h4>${limitations.length ? `<ul>${limitations.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : "<p>No additional AI limitations reported.</p>"}`;
}

const summaryMarkup = new WeakMap();
export function updateSummaryRegion(target, run) {
  const markup = renderSummaryRun(run);
  if (summaryMarkup.get(target) === markup) return;
  const audit = target.querySelector(".technical-audit");
  const open = Boolean(audit?.open);
  const restoreFocus = audit?.contains(target.ownerDocument?.activeElement);
  const before = restoreFocus ? audit.getBoundingClientRect().top : null;
  target.innerHTML = markup;
  summaryMarkup.set(target, markup);
  const updated = target.querySelector(".technical-audit");
  if (updated) {
    updated.open = open;
    if (restoreFocus) {
      updated.querySelector("summary")?.focus({ preventScroll: true });
      globalThis.scrollBy?.(0, updated.getBoundingClientRect().top - before);
    }
  }
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
    <nav class="workspace-jumps" aria-label="Within this buyer case">${[["properties", "Shortlist"], ["tasks", "Tasks"], ["notes", "Notes"], ["evidence", "Evidence"], ["summary", "AI summary"]].map(([id, label]) => `<button type="button" data-jump="${id}-heading">${label}</button>`).join("")}</nav>
    <section class="workspace-section" aria-labelledby="properties-heading"><header><div><p class="ps-eyebrow">SHORTLIST</p><h3 id="properties-heading">Properties</h3></div><button class="ps-button ps-button--primary" type="button" data-add-property>Add property</button></header><div class="workspace-items">${renderPropertyItems(properties)}</div></section>
    <section class="workspace-section" aria-labelledby="tasks-heading"><header><div><p class="ps-eyebrow">NEXT STEPS</p><h3 id="tasks-heading">Tasks</h3></div><button class="ps-button ps-button--primary" type="button" data-add-task>Add task</button></header><div class="workspace-items">${renderTaskItems(tasks, propertyName)}</div></section>
    <section class="workspace-section" aria-labelledby="notes-heading"><header><div><p class="ps-eyebrow">OBSERVATIONS</p><h3 id="notes-heading">Notes</h3></div><button class="ps-button ps-button--primary" type="button" data-add-note>Add note</button></header><div class="workspace-items">${renderNoteItems(notes, propertyName)}</div></section>
    <section class="workspace-section" aria-labelledby="evidence-heading"><header><div><p class="ps-eyebrow">CROSS-FEATURE EVIDENCE</p><h3 id="evidence-heading">Bounded evidence</h3></div><button class="ps-button" type="button" data-refresh-evidence>Refresh evidence</button></header><div data-evidence aria-live="polite"><p>Loading evidence…</p></div></section>
    <section class="workspace-section" aria-labelledby="summary-heading"><header><div><p class="ps-eyebrow">AI ASSISTANCE</p><h3 id="summary-heading">Buyer case summary</h3></div><button class="ps-button ps-button--primary" type="button" data-generate-summary>Generate case summary</button></header><p class="item-reference">AI output is advisory. Confirm evidence and important decisions yourself.</p><div data-summary-run>${renderSummaryRun(null)}</div></section>`;
  view.querySelectorAll("[data-jump]").forEach(button => button.addEventListener("click", () => {
    const heading = view.querySelector(`#${button.dataset.jump}`);
    if (!heading) return;
    heading.tabIndex = -1;
    heading.scrollIntoView({block: "start"}); heading.focus({preventScroll: true});
  }));
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
  const task = evidenceTask.start();
  const target = document.querySelector("[data-evidence]");
  if (!target) return;
  target.setAttribute("aria-busy", "true");
  if (!target.querySelector(".evidence-card")) target.innerHTML = "<p>Loading bounded evidence…</p>";
  showNotice("Refreshing evidence. Any existing evidence remains the last retrieved result.", "info");
  try {
    const value = await api.evidence(caseId, {signal: task.signal});
    if (task.isCurrent() && target.isConnected && currentCase?.id === caseId) { target.innerHTML = renderEvidence(value); showNotice("Evidence refreshed. Review each source’s coverage and limitations.", "info"); }
  } catch (error) {
    if (task.isCurrent() && target.isConnected && currentCase?.id === caseId) {
      showNotice("Evidence could not be refreshed. Any existing evidence is the last retrieved result. Buyer-case editing remains available.", "error");
      if (!target.querySelector(".evidence-card")) target.innerHTML = '<div data-state="unavailable"><p>No evidence could be retrieved. Use Refresh evidence to try again.</p></div>';
    }
  } finally {
    if (task.isCurrent()) target.setAttribute("aria-busy", "false");
  }
}

async function generateSummary(caseId) {
  const target = document.querySelector("[data-summary-run]");
  const button = document.querySelector("[data-generate-summary]");
  if (!target || !button || button.disabled) return;
  const task = summaryTask.start();
  const isCurrent = () => task.isCurrent() && currentCase?.id === caseId && target.isConnected;
  button.disabled = true;
  updateSummaryRegion(target, { status: "queued", phases: [] });
  try {
    const key = `buyer-summary-${caseId}-${globalThis.crypto?.randomUUID?.() || Date.now()}`;
    const initial = await api.summaries.create(caseId, key);
    if (!isCurrent()) return;
    updateSummaryRegion(target, initial);
    await pollUntilSettled((signal) => api.summaries.read(caseId, initial.id, {signal}), {
      task, initial, isSettled: (run) => ["succeeded", "failed", "cancelled", "timed_out", "waiting_for_review", "review_required"].includes(run.status),
      onUpdate: (run) => { if (isCurrent()) updateSummaryRegion(target, run); },
    });
  } catch (error) {
    if (isCurrent()) target.textContent = error.message + " Your saved buyer case is unchanged. A workflow may still be active; do not assume this network error cancelled it.";
  } finally {
    if (isCurrent()) button.disabled = false;
  }
}

async function loadList() {
  const task = viewTask.start();
  summaryTask.cancel();
  evidenceTask.cancel();
  currentCase = null;
  renderState("loading", "Loading buyer cases…", "Please wait while saved cases are retrieved.");
  try {
    const payload = await api.list(1, 100, {signal: task.signal});
    if (!task.isCurrent()) return;
    cases = Array.isArray(payload.items) ? payload.items : [];
    renderList();
    setServiceState(true);
  } catch (error) {
    if (!task.isCurrent()) return;
    setServiceState(false);
    renderState("unavailable", "Buyer cases are unavailable", "The service could not be reached. Your browser has not changed any cases.", true);
  }
}

async function loadDetail(caseId) {
  const task = viewTask.start();
  summaryTask.cancel();
  evidenceTask.cancel();
  currentCase = null;
  renderState("loading", "Loading buyer case…", "Please wait while the case is retrieved.");
  try {
    const [item, propertyPage, notePage, taskPage] = await Promise.all([
      api.read(caseId, {signal: task.signal}),
      api.properties.list(caseId, {signal: task.signal}),
      api.notes.list(caseId, {signal: task.signal}),
      api.tasks.list(caseId, {signal: task.signal}),
    ]);
    if (!task.isCurrent()) return;
    currentCase = item;
    properties = propertyPage.items;
    notes = notePage.items;
    tasks = taskPage.items;
    renderDetail(item);
    setServiceState(true);
    void loadEvidence(caseId);
  } catch (error) {
    if (!task.isCurrent()) return;
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
  globalThis.addEventListener("pagehide", () => { viewTask.cancel(); summaryTask.cancel(); evidenceTask.cancel(); clearTimeout(toastTimer); }, { once: true });
  route(false);
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", initialise);
}
