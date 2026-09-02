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

function checklistCard(checklist) {
  const card = el("article", "ps-card");
  const body = el("div", "ps-card__body");
  body.append(el("h2", "card-title", "Checklist"));
  const items = Array.isArray(checklist) ? checklist : [];
  if (items.length === 0) {
    body.append(el("p", "empty", "No checklist items yet."));
  } else {
    const list = el("ul", "checklist");
    items.forEach((entry) => {
      const done = Boolean(entry && entry.done);
      const li = el("li", done ? "checklist__item is-done" : "checklist__item");
      li.append(el("span", "checklist__mark", done ? "\u2713" : "\u25CB"));
      li.append(el("span", "checklist__text", (entry && entry.item) || ""));
      list.append(li);
    });
    body.append(list);
  }
  card.append(body);
  return card;
}

function questionsCard(questions) {
  const card = el("article", "ps-card");
  const body = el("div", "ps-card__body");
  body.append(el("h2", "card-title", "Professional-verification questions"));
  const items = Array.isArray(questions) ? questions : [];
  if (items.length === 0) {
    body.append(
      el(
        "p",
        "empty",
        "No questions yet. The AI-generated question pack will appear here in a later release.",
      ),
    );
  } else {
    const list = el("ol", "question-list");
    items.forEach((question) =>
      list.append(el("li", null, typeof question === "string" ? question : (question && question.question) || "")),
    );
    body.append(list);
  }
  card.append(body);
  return card;
}

function notesCard(notes) {
  const card = el("article", "ps-card");
  const body = el("div", "ps-card__body");
  body.append(el("h2", "card-title", "Notes"));
  body.append(el("p", "notes-text", notes));
  card.append(body);
  return card;
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
  view.append(heading);

  const stack = el("div", "detail-stack");
  if (review.notes) stack.append(notesCard(review.notes));
  stack.append(checklistCard(review.checklist));
  stack.append(questionsCard(review.verification_questions));
  view.append(stack);

  view.append(evidenceSection("Planning & environmental constraints", data.constraints, "constraint"));
  view.append(evidenceSection("Strata & building records", data.buildings, "building"));
}

// --- create dialog ---
let selectedProperty = null;
let searchTimer;
let toastTimer;

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
  clearError(document.querySelector("#review-error"));
  dialog.showModal();
  const input = document.querySelector("#property-search");
  if (input) input.focus();
}

function closeDialog() {
  const dialog = document.querySelector("#review-dialog");
  if (dialog && dialog.open) dialog.close();
}

async function submitReview(event) {
  event.preventDefault();
  const error = document.querySelector("#review-error");
  const title = document.querySelector("#review-title");
  clearError(error);
  if (!selectedProperty) {
    showError(error, "Search for and select a verified property first.");
    return;
  }
  if (!title || !title.value.trim()) {
    showError(error, "Enter a title for the review.");
    return;
  }
  const payload = buildReviewPayload({
    propertyRef: selectedProperty.property_ref,
    addressDisplay: selectedProperty.address_display,
    title: title.value,
    status: document.querySelector("#review-status").value,
    disposition: document.querySelector("#review-disposition").value,
    notes: document.querySelector("#review-notes").value,
  });
  const submit = document.querySelector("#review-submit");
  if (submit) submit.disabled = true;
  try {
    const response = await fetch(`${API_BASE}/site-reviews`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (response.status === 201) {
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

  route({ focus: false });
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", initialise);
}
