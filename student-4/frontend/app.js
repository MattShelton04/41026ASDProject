// Student 4 - Site, Planning & Building Due Diligence frontend.
// Dependency-free ES module with a tiny hash router (#site-reviews list,
// #site-reviews/<id> detail). Pure helpers are exported for the Node test gate;
// the DOM bootstrap only runs inside a browser.

export const API_BASE = "/api/due-diligence/v1";

const LIST_INTRO =
  "Review available planning, environmental, strata and building evidence for a property, " +
  "and record a due-diligence disposition. Confirmed observations, non-intersections, partial " +
  "coverage and unavailable coverage are shown distinctly.";

const STATUS_LABELS = {
  draft: "Draft",
  in_review: "In review",
  completed: "Completed",
  archived: "Archived",
};

const DISPOSITION_LABELS = {
  undecided: "Undecided",
  proceed: "Proceed",
  hold: "Hold",
  do_not_proceed: "Do not proceed",
};

const EVIDENCE_STATE_LABELS = {
  confirmed: "Confirmed",
  non_intersection: "No intersection",
  partial_coverage: "Partial coverage",
  unavailable: "Unavailable",
};

// Map a review status to a shared evidence badge modifier (or "" for the neutral badge).
const STATUS_BADGE = {
  completed: "ps-badge--confirmed",
  in_review: "ps-badge--info",
  draft: "ps-badge--planned",
};

// Map an evidence state to a shared badge modifier (or "" for the neutral badge).
const EVIDENCE_STATE_BADGE = {
  confirmed: "ps-badge--confirmed",
  partial_coverage: "ps-badge--partial",
  non_intersection: "ps-badge--info",
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || "Unknown";
}

export function dispositionLabel(disposition) {
  return DISPOSITION_LABELS[disposition] || "Unknown";
}

export function evidenceStateLabel(state) {
  return EVIDENCE_STATE_LABELS[state] || "Unknown";
}

export function statusBadgeClass(status) {
  return STATUS_BADGE[status] || "";
}

export function evidenceBadgeClass(state) {
  return EVIDENCE_STATE_BADGE[state] || "";
}

export function summariseReview(review) {
  return `${review.title} - ${review.address_display} (${statusLabel(review.status)})`;
}

// Turn a snake_case identifier (e.g. floor_space_ratio) into a readable label.
export function formatType(value) {
  if (!value) return "";
  const spaced = String(value).replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

// Parse the location hash into a route: the list, or a review detail with its id.
export function parseRoute(hash) {
  const clean = String(hash || "").replace(/^#/, "");
  const match = clean.match(/^site-reviews\/(.+)$/);
  if (match) return { name: "detail", id: decodeURIComponent(match[1]) };
  return { name: "list" };
}

const DEFAULT_CHECKLIST = [
  { item: "Confirm zoning permits the intended use", done: false },
  { item: "Check flood and bushfire exposure", done: false },
  { item: "Review strata and building orders", done: false },
];

// Build a create payload from raw form values, trimming text and defaulting safely.
export function buildReviewPayload(values) {
  return {
    property_ref: String(values.propertyRef || "").trim(),
    address_display: String(values.addressDisplay || "").trim(),
    title: String(values.title || "").trim(),
    status: values.status || "draft",
    disposition: values.disposition || "undecided",
    notes: String(values.notes || "").trim(),
    checklist: Array.isArray(values.checklist) ? values.checklist : DEFAULT_CHECKLIST,
  };
}

// Map a create/update Problem Details response to a friendly message.
export function problemMessage(problem, status) {
  const code = problem && problem.code;
  if (code === "unknown_property") return "That property is not verified in Feature 1.";
  if (code === "invalid_site_review") {
    return (problem && problem.detail) || "Please check the review details and try again.";
  }
  return `Could not save the review (status ${status}).`;
}

// Build an update payload for an existing review (property is not editable).
export function buildUpdatePayload(values) {
  return {
    title: String(values.title || "").trim(),
    status: values.status || "draft",
    disposition: values.disposition || "undecided",
    notes: String(values.notes || "").trim(),
  };
}

// Return a new checklist with one item's done-state changed (pure).
export function toggleChecklist(checklist, index, done) {
  const items = Array.isArray(checklist) ? checklist : [];
  return items.map((item, position) => (position === index ? { ...item, done } : item));
}

// Extract a clean question / verification-point list from an AI-mode final_result (pure).
// Prefers an explicit `questions` array; otherwise uses the default.v7 `findings` list
// (plus the recommended next step); otherwise pulls question-like lines from the text.
export function extractQuestions(finalResult) {
  if (!finalResult || typeof finalResult !== "object") return [];
  if (Array.isArray(finalResult.questions)) {
    const questions = finalResult.questions
      .map((q) => (typeof q === "string" ? q : q && q.question))
      .filter((q) => typeof q === "string" && q.trim())
      .map((q) => q.trim());
    if (questions.length) return questions;
  }
  if (Array.isArray(finalResult.findings)) {
    const points = finalResult.findings
      .filter((f) => typeof f === "string" && f.trim())
      .map((f) => f.trim());
    if (typeof finalResult.recommended_next_step === "string" && finalResult.recommended_next_step.trim()) {
      points.push(finalResult.recommended_next_step.trim());
    }
    if (points.length) return points;
  }
  const text = [finalResult.summary, finalResult.answer]
    .filter((value) => typeof value === "string")
    .join("\n");
  return text
    .split("\n")
    .map((line) => line.replace(/^\s*(?:\d+[.)]|[-*\u2022])\s*/, "").trim())
    .filter((line) => line.endsWith("?"));
}

// Build shared-map layer definitions from the backend /map payload (pure).
export function mapLayerDefinitions(mapData) {
  const layers = [];
  if (mapData && mapData.property) {
    layers.push({
      id: "property",
      label: "Property",
      kind: "point",
      data: mapData.property,
      popup: { title: "address", fields: [] },
    });
  }
  const hazards = Array.isArray(mapData && mapData.layers) ? mapData.layers : [];
  for (const layer of hazards) {
    layers.push({
      id: layer.id,
      label: layer.label,
      kind: "polygon",
      data: layer.data,
      popup: {
        title: "hazard",
        fields: [
          { label: "Evidence", property: "evidence_state" },
          { label: "Note", property: "summary" },
        ],
      },
    });
  }
  return layers;
}

// --- DOM helpers (browser only) ---
function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function badge(modifier, text) {
  return el("span", ["ps-badge", modifier].filter(Boolean).join(" "), text);
}

function renderMessage(container, text) {
  container.replaceChildren(el("p", "empty", text));
}

function setServiceState(state, label) {
  const indicator = document.querySelector("#service-state");
  if (!indicator) return;
  indicator.classList.remove("checking", "online", "offline");
  indicator.classList.add(state);
  const text = indicator.querySelector("[data-service-label]");
  if (text) text.textContent = label;
}

// --- list view ---
let allReviews = [];
let reviewsLoaded = false;
let filterQuery = "";

function reviewCard(review) {
  const card = el("a", "ps-card review-card");
  card.href = `#site-reviews/${encodeURIComponent(review.id)}`;
  const body = el("div", "ps-card__body");
  body.append(el("p", "review-card__eyebrow", "Site review"));
  body.append(el("h3", null, review.title));
  body.append(el("p", "review-address", review.address_display));
  const meta = el("div", "review-meta");
  meta.append(badge(statusBadgeClass(review.status), statusLabel(review.status)));
  meta.append(el("span", "review-disposition", `Disposition: ${dispositionLabel(review.disposition)}`));
  body.append(meta);
  card.append(body);
  return card;
}

function renderListView(view) {
  view.replaceChildren();
  const heading = el("div", "page-heading");
  heading.append(el("p", "ps-eyebrow", "Site, planning & building due diligence"));
  const titleRow = el("div", "page-title-row");
  titleRow.append(el("h1", null, "Site reviews"));
  const newButton = el("button", "ps-button ps-button--primary", "New site review");
  newButton.type = "button";
  newButton.addEventListener("click", openCreateDialog);
  titleRow.append(newButton);
  heading.append(titleRow);
  heading.append(el("p", "page-intro", LIST_INTRO));
  view.append(heading);

  const grid = el("div", "review-grid");
  view.append(grid);
  if (allReviews.length === 0) {
    renderMessage(grid, "No site reviews yet.");
    return;
  }
  const needle = filterQuery.trim().toLowerCase();
  const matches = needle
    ? allReviews.filter((review) =>
        `${review.title} ${review.address_display}`.toLowerCase().includes(needle),
      )
    : allReviews;
  if (matches.length === 0) {
    renderMessage(grid, "No site reviews match your filter.");
    return;
  }
  matches.forEach((review) => grid.append(reviewCard(review)));
}

async function ensureReviews(view) {
  if (reviewsLoaded) return true;
  renderMessage(view, "Loading site reviews\u2026");
  try {
    const response = await fetch(`${API_BASE}/site-reviews`);
    if (!response.ok) throw new Error(`Unexpected status ${response.status}`);
    const payload = await response.json();
    allReviews = Array.isArray(payload.items) ? payload.items : [];
    reviewsLoaded = true;
    setServiceState("online", "Evidence service available");
    return true;
  } catch (error) {
    renderMessage(view, "Could not load site reviews. Is the due-diligence service running?");
    setServiceState("offline", "Service unavailable");
    return false;
  }
}

// --- detail view ---
function backLink() {
  const link = el("a", "back-link", "\u2190 Back to site reviews");
  link.href = "#site-reviews";
  return link;
}

function evidenceCard(item, kind) {
  const card = el("article", "ps-card evidence-card");
  const body = el("div", "ps-card__body");

  const head = el("div", "evidence-head");
  const typeText = kind === "constraint" ? item.constraint_type : item.record_type;
  head.append(el("p", "review-card__eyebrow", formatType(typeText)));
  head.append(badge(evidenceBadgeClass(item.evidence_state), evidenceStateLabel(item.evidence_state)));
  body.append(head);

  body.append(el("p", "evidence-summary", item.summary || ""));

  const observed =
    kind === "constraint"
      ? item.observed_value
      : item.reference_code
        ? `Ref ${item.reference_code}`
        : null;
  if (observed) body.append(el("p", "evidence-observed", observed));

  const footer = el("div", "evidence-footer");
  if (item.source_url) {
    const source = el("a", "evidence-source", item.source_name || "Source");
    source.href = item.source_url;
    source.target = "_blank";
    source.rel = "noreferrer noopener";
    footer.append(source);
  } else if (item.source_name) {
    footer.append(el("span", "evidence-source", item.source_name));
  }
  if (item.confidence != null) {
    footer.append(
      el("span", "evidence-confidence", `${Math.round(Number(item.confidence) * 100)}% match confidence`),
    );
  }
  if (footer.childNodes.length) body.append(footer);

  card.append(body);
  return card;
}

function evidenceSection(title, items, kind) {
  const section = el("section", "evidence-section");
  section.append(el("h2", "card-title", title));
  const rows = Array.isArray(items) ? items : [];
  if (rows.length === 0) {
    section.append(el("p", "empty", "No records available for this property."));
    return section;
  }
  const grid = el("div", "evidence-grid");
  rows.forEach((item) => grid.append(evidenceCard(item, kind)));
  section.append(grid);
  return section;
}

function checklistCard(review) {
  const card = el("article", "ps-card");
  const body = el("div", "ps-card__body");
  body.append(el("h2", "card-title", "Checklist"));
  const items = Array.isArray(review.checklist) ? review.checklist : [];
  if (items.length === 0) {
    body.append(el("p", "empty", "No checklist items yet."));
  } else {
    const list = el("ul", "checklist");
    items.forEach((entry, index) => {
      const done = Boolean(entry && entry.done);
      const li = el("li", done ? "checklist__item is-done" : "checklist__item");
      const label = el("label", "checklist__label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "checklist__checkbox";
      checkbox.checked = done;
      checkbox.addEventListener("change", () => toggleChecklistItem(review, index, checkbox, li));
      label.append(checkbox, el("span", "checklist__text", (entry && entry.item) || ""));
      li.append(label);
      list.append(li);
    });
    body.append(list);
  }
  card.append(body);
  return card;
}

async function toggleChecklistItem(review, index, checkbox, li) {
  const desired = checkbox.checked;
  const updated = toggleChecklist(review.checklist, index, desired);
  checkbox.disabled = true;
  try {
    const response = await fetch(`${API_BASE}/site-reviews/${encodeURIComponent(review.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ checklist: updated }),
    });
    if (!response.ok) throw new Error(`Unexpected status ${response.status}`);
    review.checklist = updated;
    reviewsLoaded = false;
    if (li) li.classList.toggle("is-done", desired);
  } catch (networkError) {
    checkbox.checked = !desired;
    showToast("Could not update the checklist item.");
  } finally {
    checkbox.disabled = false;
  }
}

function questionsCard(review) {
  const card = el("article", "ps-card");
  const body = el("div", "ps-card__body");
  const head = el("div", "questions-head");
  head.append(el("h2", "card-title", "Professional-verification questions"));
  const generate = el("button", "ps-button ps-button--primary ps-button--small", "Generate with AI");
  generate.type = "button";
  head.append(generate);
  body.append(head);

  const status = el("p", "questions-status");
  status.hidden = true;
  body.append(status);

  const listHost = el("div", "questions-host");
  body.append(listHost);
  renderQuestionList(listHost, Array.isArray(review.verification_questions) ? review.verification_questions : []);

  generate.addEventListener("click", () => generateQuestions(review, generate, status, listHost));
  card.append(body);
  return card;
}

function renderQuestionList(host, questions) {
  if (!questions.length) {
    host.replaceChildren(
      el("p", "empty", "No questions yet. Generate a bounded AI question pack from the evidence."),
    );
    return;
  }
  const list = el("ol", "question-list");
  questions.forEach((question) =>
    list.append(el("li", null, typeof question === "string" ? question : (question && question.question) || "")),
  );
  host.replaceChildren(list);
}

async function generateQuestions(review, button, status, listHost) {
  button.disabled = true;
  status.hidden = false;
  status.textContent = "Starting a bounded Plan \u2192 Act \u2192 Observe \u2192 Adapt run\u2026";
  try {
    const start = await fetch(`${API_BASE}/assistant/turns`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_id: review.id }),
    });
    if (!start.ok) {
      const problem = await start.json().catch(() => ({}));
      throw new Error(
        problem.code === "ai_mode_unavailable"
          ? "AI mode is unavailable. The evidence below remains usable."
          : `Could not start the AI run (status ${start.status}).`,
      );
    }
    const run = await start.json();
    const questions = await pollAssistant(run.id, status);
    if (questions.length === 0) {
      status.textContent = "The AI run finished without a clear question list. Try again.";
      return;
    }
    renderQuestionList(listHost, questions);
    status.textContent = `Generated ${questions.length} question(s).`;
    await saveQuestions(review, questions, status);
  } catch (error) {
    status.textContent = error.message;
  } finally {
    button.disabled = false;
  }
}

async function pollAssistant(runId, status) {
  for (let attempt = 0; attempt < 90; attempt += 1) {
    const response = await fetch(`${API_BASE}/assistant/turns/${encodeURIComponent(runId)}`);
    if (!response.ok) throw new Error("Lost track of the AI run.");
    const detail = await response.json();
    const run = detail.run || detail;
    status.textContent = `AI run: ${run.status}\u2026`;
    if (run.status === "succeeded") return extractQuestions(run.final_result);
    if (["failed", "cancelled", "timed_out"].includes(run.status)) {
      throw new Error(
        (run.error && run.error.message) ||
          `AI run ${run.status}. Add an AI credential to enable generation; the evidence remains usable.`,
      );
    }
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  throw new Error("The AI run is still active; check back shortly.");
}

async function saveQuestions(review, questions, status) {
  try {
    const response = await fetch(`${API_BASE}/site-reviews/${encodeURIComponent(review.id)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ verification_questions: questions }),
    });
    if (response.ok) {
      review.verification_questions = questions;
      reviewsLoaded = false;
      status.textContent = `Saved ${questions.length} question(s) to this review.`;
    }
  } catch (networkError) {
    // Non-fatal: the generated questions are already displayed.
  }
}

function notesCard(notes) {
  const card = el("article", "ps-card");
  const body = el("div", "ps-card__body");
  body.append(el("h2", "card-title", "Notes"));
  body.append(el("p", "notes-text", notes));
  card.append(body);
  return card;
}

function mapCard(review) {
  const card = el("article", "ps-card");
  const body = el("div", "ps-card__body");
  body.append(el("h2", "card-title", "Environmental map"));
  body.append(
    el(
      "p",
      "map-intro",
      "Flood and bushfire layers are drawn only where the evidence intersects the property.",
    ),
  );
  const host = el("div", "ps-map");
  const canvas = el("div", "ps-map__canvas");
  const statusNode = el("div", "ps-map__status", "Loading map\u2026");
  statusNode.setAttribute("role", "status");
  statusNode.dataset.state = "loading";
  host.append(canvas, statusNode);
  body.append(host);
  card.append(body);
  loadMap(review.id, canvas, statusNode);
  return card;
}

async function loadMap(reviewId, canvas, statusNode) {
  let mapData;
  try {
    const response = await fetch(`${API_BASE}/site-reviews/${encodeURIComponent(reviewId)}/map`);
    if (!response.ok) throw new Error(`Unexpected status ${response.status}`);
    mapData = await response.json();
  } catch (networkError) {
    statusNode.dataset.state = "error";
    statusNode.textContent = "The map could not be loaded.";
    return;
  }
  if (!mapData.available) {
    statusNode.dataset.state = "error";
    statusNode.textContent = "No verified coordinate is available, so the map cannot be shown.";
    return;
  }
  try {
    const mapping = await import("./mapping/index.js");
    await mapping.createMap({
      container: canvas,
      provider: mapping.createOpenFreeMapProvider(),
      layers: mapLayerDefinitions(mapData),
      view: { center: mapData.center, zoom: 15 },
      onStatus(event) {
        statusNode.dataset.state = event.state;
        statusNode.textContent = event.message;
      },
    });
  } catch (mapError) {
    statusNode.dataset.state = "error";
    statusNode.textContent = "The interactive map could not start; the evidence below remains available.";
  }
}

async function renderDetailView(view, id) {
  renderMessage(view, "Loading review\u2026");
  let data;
  try {
    const response = await fetch(`${API_BASE}/site-reviews/${encodeURIComponent(id)}/evidence`);
    if (response.status === 404) {
      view.replaceChildren(backLink(), el("p", "empty", "That site review was not found."));
      setServiceState("online", "Evidence service available");
      return;
    }
    if (!response.ok) throw new Error(`Unexpected status ${response.status}`);
    data = await response.json();
    setServiceState("online", "Evidence service available");
  } catch (error) {
    view.replaceChildren(
      backLink(),
      el("p", "empty", "Could not load this review. Is the due-diligence service running?"),
    );
    setServiceState("offline", "Service unavailable");
    return;
  }

  const review = data.site_review || {};
  view.replaceChildren();
  view.append(backLink());

  const heading = el("div", "page-heading");
  heading.append(el("p", "ps-eyebrow", "Site review"));
  heading.append(el("h1", null, review.title || "Site review"));
  heading.append(el("p", "review-address", review.address_display || ""));
  const meta = el("div", "review-meta");
  meta.append(badge(statusBadgeClass(review.status), statusLabel(review.status)));
  meta.append(el("span", "review-disposition", `Disposition: ${dispositionLabel(review.disposition)}`));
  heading.append(meta);
  const actions = el("div", "detail-actions");
  const editButton = el("button", "ps-button", "Edit");
  editButton.type = "button";
  editButton.addEventListener("click", () => openEditDialog(review));
  const deleteButton = el("button", "ps-button ps-button--danger", "Delete");
  deleteButton.type = "button";
  deleteButton.addEventListener("click", () => openDeleteConfirm(review));
  actions.append(editButton, deleteButton);
  heading.append(actions);
  view.append(heading);

  const stack = el("div", "detail-stack");
  if (review.notes) stack.append(notesCard(review.notes));
  stack.append(checklistCard(review));
  stack.append(questionsCard(review));
  view.append(stack);

  view.append(mapCard(review));

  view.append(evidenceSection("Planning & environmental constraints", data.constraints, "constraint"));
  view.append(evidenceSection("Strata & building records", data.buildings, "building"));
}

// --- create / edit / delete dialogs ---
let selectedProperty = null;
let searchTimer;
let toastTimer;
let dialogMode = "create";
let editingReviewId = null;
let deletingReviewId = null;

function showToast(message) {
  const toast = document.querySelector("#toast");
  if (!toast) return;
  toast.textContent = message;
  toast.dataset.visible = "true";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.dataset.visible = "false";
  }, 4000);
}

function showError(node, message) {
  if (!node) return;
  node.textContent = message;
  node.hidden = false;
}

function clearError(node) {
  if (!node) return;
  node.textContent = "";
  node.hidden = true;
}

function propertyOption(item) {
  const option = el("button", "property-option");
  option.type = "button";
  option.append(el("span", "property-option__address", item.address_display));
  if (item.resolution_status) {
    option.append(el("span", "property-option__status", item.resolution_status));
  }
  option.addEventListener("click", () => selectProperty(item));
  return option;
}

async function runPropertySearch(query, results) {
  try {
    const response = await fetch(`${API_BASE}/properties/search?q=${encodeURIComponent(query)}`);
    if (!response.ok) {
      results.replaceChildren(el("p", "search-hint", "Enter at least three characters to search."));
      return;
    }
    const payload = await response.json();
    if (!payload.available) {
      results.replaceChildren(el("p", "search-hint", "Property search is unavailable right now."));
      return;
    }
    const items = Array.isArray(payload.items) ? payload.items : [];
    if (items.length === 0) {
      results.replaceChildren(el("p", "search-hint", "No verified properties matched."));
      return;
    }
    results.replaceChildren(...items.map((item) => propertyOption(item)));
  } catch (error) {
    results.replaceChildren(el("p", "search-hint", "Property search is unavailable right now."));
  }
}

function selectProperty(item) {
  selectedProperty = { property_ref: item.property_ref, address_display: item.address_display };
  const results = document.querySelector("#property-results");
  const input = document.querySelector("#property-search");
  const selected = document.querySelector("#selected-property");
  const title = document.querySelector("#review-title");
  if (results) results.replaceChildren();
  if (input) input.value = item.address_display;
  if (selected) {
    selected.hidden = false;
    selected.textContent = `Selected: ${item.address_display}`;
  }
  if (title && !title.value.trim()) title.value = `Due-diligence review - ${item.address_display}`;
}

function initPropertySearch() {
  const input = document.querySelector("#property-search");
  const results = document.querySelector("#property-results");
  if (!input || !results) return;
  input.addEventListener("input", () => {
    selectedProperty = null;
    const selected = document.querySelector("#selected-property");
    if (selected) selected.hidden = true;
    clearTimeout(searchTimer);
    const query = input.value.trim();
    if (query.length < 3) {
      results.replaceChildren();
      return;
    }
    searchTimer = setTimeout(() => runPropertySearch(query, results), 250);
  });
}

function openCreateDialog() {
  const dialog = document.querySelector("#review-dialog");
  if (!dialog) return;
  dialogMode = "create";
  editingReviewId = null;
  selectedProperty = null;
  const form = document.querySelector("#review-form");
  if (form) form.reset();
  const results = document.querySelector("#property-results");
  if (results) results.replaceChildren();
  const selected = document.querySelector("#selected-property");
  if (selected) {
    selected.hidden = true;
    selected.textContent = "";
  }
  const propertyField = document.querySelector("#property-field");
  if (propertyField) propertyField.hidden = false;
  document.querySelector("#review-dialog-title").textContent = "New site review";
  document.querySelector("#review-submit").textContent = "Create review";
  clearError(document.querySelector("#review-error"));
  dialog.showModal();
  const input = document.querySelector("#property-search");
  if (input) input.focus();
}

function openEditDialog(review) {
  const dialog = document.querySelector("#review-dialog");
  if (!dialog) return;
  dialogMode = "edit";
  editingReviewId = review.id;
  selectedProperty = { property_ref: review.property_ref, address_display: review.address_display };
  document.querySelector("#review-title").value = review.title || "";
  document.querySelector("#review-status").value = review.status || "draft";
  document.querySelector("#review-disposition").value = review.disposition || "undecided";
  document.querySelector("#review-notes").value = review.notes || "";
  const propertyField = document.querySelector("#property-field");
  if (propertyField) propertyField.hidden = true;
  document.querySelector("#review-dialog-title").textContent = "Edit site review";
  document.querySelector("#review-submit").textContent = "Save changes";
  clearError(document.querySelector("#review-error"));
  dialog.showModal();
  document.querySelector("#review-title").focus();
}

function closeDialog() {
  const dialog = document.querySelector("#review-dialog");
  if (dialog && dialog.open) dialog.close();
}

function currentFormValues() {
  return {
    title: document.querySelector("#review-title").value,
    status: document.querySelector("#review-status").value,
    disposition: document.querySelector("#review-disposition").value,
    notes: document.querySelector("#review-notes").value,
  };
}

function saveCreate() {
  const payload = buildReviewPayload({
    propertyRef: selectedProperty.property_ref,
    addressDisplay: selectedProperty.address_display,
    ...currentFormValues(),
  });
  return fetch(`${API_BASE}/site-reviews`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

function saveEdit() {
  const payload = buildUpdatePayload(currentFormValues());
  return fetch(`${API_BASE}/site-reviews/${encodeURIComponent(editingReviewId)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function submitReview(event) {
  event.preventDefault();
  const error = document.querySelector("#review-error");
  const title = document.querySelector("#review-title");
  clearError(error);
  if (!title || !title.value.trim()) {
    showError(error, "Enter a title for the review.");
    return;
  }
  if (dialogMode === "create" && !selectedProperty) {
    showError(error, "Search for and select a verified property first.");
    return;
  }
  const submit = document.querySelector("#review-submit");
  if (submit) submit.disabled = true;
  try {
    const response = dialogMode === "edit" ? await saveEdit() : await saveCreate();
    if (dialogMode === "edit" && response.ok) {
      closeDialog();
      reviewsLoaded = false;
      showToast("Site review updated.");
      route({ focus: false });
      return;
    }
    if (dialogMode === "create" && response.status === 201) {
      const created = await response.json();
      closeDialog();
      reviewsLoaded = false;
      showToast("Site review created.");
      location.hash = `#site-reviews/${encodeURIComponent(created.id)}`;
      return;
    }
    const problem = await response.json().catch(() => ({}));
    showError(error, problemMessage(problem, response.status));
  } catch (networkError) {
    showError(error, "Could not save the review. Is the due-diligence service running?");
  } finally {
    if (submit) submit.disabled = false;
  }
}

function openDeleteConfirm(review) {
  const dialog = document.querySelector("#confirm-dialog");
  if (!dialog) return;
  deletingReviewId = review.id;
  const text = document.querySelector("#confirm-text");
  if (text) text.textContent = `Delete "${review.title}"? This cannot be undone.`;
  dialog.showModal();
}

function closeConfirm() {
  const dialog = document.querySelector("#confirm-dialog");
  if (dialog && dialog.open) dialog.close();
}

async function confirmDelete() {
  if (!deletingReviewId) return;
  const button = document.querySelector("#confirm-delete");
  if (button) button.disabled = true;
  try {
    const response = await fetch(`${API_BASE}/site-reviews/${encodeURIComponent(deletingReviewId)}`, {
      method: "DELETE",
    });
    closeConfirm();
    if (response.ok) {
      reviewsLoaded = false;
      showToast("Site review deleted.");
      location.hash = "#site-reviews";
    } else {
      showToast("Could not delete the review.");
    }
  } catch (networkError) {
    closeConfirm();
    showToast("Could not delete the review. Is the service running?");
  } finally {
    if (button) button.disabled = false;
  }
}

// --- router ---
function focusMain() {
  const main = document.querySelector("#main-content");
  if (main) main.focus();
}

async function route(options) {
  const view = document.querySelector("#view");
  if (!view) return;
  const parsed = parseRoute(location.hash);
  if (parsed.name === "detail") {
    await renderDetailView(view, parsed.id);
  } else {
    const ready = await ensureReviews(view);
    if (ready) renderListView(view);
  }
  if (options && options.focus) focusMain();
}

function initialise() {
  const form = document.querySelector("#review-filter-form");
  const input = document.querySelector("#review-filter");
  if (form) form.addEventListener("submit", (event) => event.preventDefault());
  if (input) {
    input.addEventListener("input", () => {
      filterQuery = input.value;
      if (parseRoute(location.hash).name === "list" && reviewsLoaded) {
        const view = document.querySelector("#view");
        if (view) renderListView(view);
      }
    });
  }
  window.addEventListener("hashchange", () => route({ focus: true }));

  const dialog = document.querySelector("#review-dialog");
  if (dialog) {
    const reviewForm = document.querySelector("#review-form");
    if (reviewForm) reviewForm.addEventListener("submit", submitReview);
    dialog
      .querySelectorAll("[data-close]")
      .forEach((button) => button.addEventListener("click", closeDialog));
    initPropertySearch();
  }

  const confirmDialog = document.querySelector("#confirm-dialog");
  if (confirmDialog) {
    const confirmButton = document.querySelector("#confirm-delete");
    if (confirmButton) confirmButton.addEventListener("click", confirmDelete);
    confirmDialog
      .querySelectorAll("[data-confirm-close]")
      .forEach((button) => button.addEventListener("click", closeConfirm));
  }

  route({ focus: false });
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", initialise);
}
