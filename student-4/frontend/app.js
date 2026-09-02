// Student 4 - Site, Planning & Building Due Diligence frontend.
// Dependency-free ES module. Pure helpers are exported for the Node test gate;
// the DOM bootstrap only runs inside a browser.

export const API_BASE = "/api/due-diligence/v1";

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

export function summariseReview(review) {
  return `${review.title} - ${review.address_display} (${statusLabel(review.status)})`;
}

function renderReview(review) {
  const card = document.createElement("article");
  card.className = "ps-card review-card";

  const body = document.createElement("div");
  body.className = "ps-card__body";

  const eyebrow = document.createElement("p");
  eyebrow.className = "review-card__eyebrow";
  eyebrow.textContent = "Site review";
  body.append(eyebrow);

  const heading = document.createElement("h3");
  heading.textContent = review.title;
  body.append(heading);

  const address = document.createElement("p");
  address.className = "review-address";
  address.textContent = review.address_display;
  body.append(address);

  const meta = document.createElement("div");
  meta.className = "review-meta";

  const badge = document.createElement("span");
  badge.className = ["ps-badge", statusBadgeClass(review.status)].filter(Boolean).join(" ");
  badge.textContent = statusLabel(review.status);
  meta.append(badge);

  const disposition = document.createElement("span");
  disposition.className = "review-disposition";
  disposition.textContent = `Disposition: ${dispositionLabel(review.disposition)}`;
  meta.append(disposition);

  body.append(meta);
  card.append(body);
  return card;
}

function renderMessage(container, text) {
  const message = document.createElement("p");
  message.className = "empty";
  message.textContent = text;
  container.replaceChildren(message);
}

function renderList(container, reviews) {
  if (reviews.length === 0) {
    renderMessage(container, "No site reviews match your filter.");
    return;
  }
  container.replaceChildren(...reviews.map(renderReview));
}

function setServiceState(state, label) {
  const indicator = document.querySelector("#service-state");
  if (!indicator) return;
  indicator.classList.remove("checking", "online", "offline");
  indicator.classList.add(state);
  const text = indicator.querySelector("[data-service-label]");
  if (text) text.textContent = label;
}

let allReviews = [];

function applyFilter(container, query) {
  const needle = query.trim().toLowerCase();
  const matches = needle
    ? allReviews.filter((review) =>
        `${review.title} ${review.address_display}`.toLowerCase().includes(needle),
      )
    : allReviews;
  renderList(container, matches);
}

async function loadReviews(container) {
  try {
    const response = await fetch(`${API_BASE}/site-reviews`);
    if (!response.ok) throw new Error(`Unexpected status ${response.status}`);
    const payload = await response.json();
    allReviews = Array.isArray(payload.items) ? payload.items : [];
    renderList(container, allReviews);
    setServiceState("online", "Evidence service available");
  } catch (error) {
    renderMessage(container, "Could not load site reviews. Is the due-diligence service running?");
    setServiceState("offline", "Service unavailable");
  }
}

function initialise() {
  const container = document.querySelector("#site-reviews");
  if (!container) return;
  const form = document.querySelector("#review-filter-form");
  const input = document.querySelector("#review-filter");
  if (form) form.addEventListener("submit", (event) => event.preventDefault());
  if (input) input.addEventListener("input", () => applyFilter(container, input.value));
  loadReviews(container);
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", initialise);
}
