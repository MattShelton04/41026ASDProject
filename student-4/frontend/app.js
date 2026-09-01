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

export function statusLabel(status) {
  return STATUS_LABELS[status] || "Unknown";
}

export function dispositionLabel(disposition) {
  return DISPOSITION_LABELS[disposition] || "Unknown";
}

export function evidenceStateLabel(state) {
  return EVIDENCE_STATE_LABELS[state] || "Unknown";
}

export function summariseReview(review) {
  return `${review.title} - ${review.address_display} (${statusLabel(review.status)})`;
}

function renderReview(review) {
  const card = document.createElement("article");
  card.className = "review-card";

  const heading = document.createElement("h3");
  heading.textContent = review.title;
  card.append(heading);

  const address = document.createElement("p");
  address.className = "review-address";
  address.textContent = review.address_display;
  card.append(address);

  const meta = document.createElement("p");
  meta.className = "review-meta";
  meta.textContent = `${statusLabel(review.status)} - ${dispositionLabel(review.disposition)}`;
  card.append(meta);

  return card;
}

async function loadReviews() {
  const container = document.querySelector("#site-reviews");
  if (!container) return;
  container.textContent = "Loading site reviews...";
  try {
    const response = await fetch(`${API_BASE}/site-reviews`);
    if (!response.ok) throw new Error(`Unexpected status ${response.status}`);
    const payload = await response.json();
    const items = Array.isArray(payload.items) ? payload.items : [];
    if (items.length === 0) {
      container.textContent = "No site reviews yet.";
      return;
    }
    container.replaceChildren(...items.map(renderReview));
  } catch (error) {
    container.textContent = "Could not load site reviews. Is the backend running?";
  }
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", loadReviews);
}
