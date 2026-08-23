import { append, button, el } from "../core/dom.js";

export function renderLoading(view, title = "Loading evidence") {
  view.replaceChildren();
  const section = el("section", "loading-state");
  section.setAttribute("role", "status");
  section.setAttribute("aria-live", "polite");
  const box = el("div");
  const spinner = el("div", "spinner");
  spinner.setAttribute("aria-hidden", "true");
  append(box, spinner, el("h2", "", title), el("p", "", "Loading the latest available information…"));
  append(section, box);
  append(view, section);
}

export function emptyState(title, message, action = null) {
  const section = el("section", "empty-state");
  section.setAttribute("role", "status");
  const box = el("div");
  append(box, el("span", "state-icon", "◇"), el("h2", "", title), el("p", "", message));
  if (action) { action.style.marginTop = ".8rem"; append(box, action); }
  append(section, box);
  return section;
}

export function errorState(error, retry) {
  const section = el("section", "error-state");
  section.setAttribute("role", "alert");
  const box = el("div");
  append(box, el("span", "state-icon", "!"), el("h2", "", error.status === 503 ? "Service temporarily unavailable" : "We couldn’t load this view"), el("p", "", error.message));
  if (error.requestId) append(box, el("code", "request-id", `Request ID: ${error.requestId}`));
  if (retry) {
    const retryButton = button("Try again", "button primary", retry);
    retryButton.style.marginTop = ".9rem";
    append(box, retryButton);
  }
  append(section, box);
  return section;
}
