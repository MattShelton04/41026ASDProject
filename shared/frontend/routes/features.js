import { capabilityState } from "../capabilities.js";
import { featureRegistry } from "../features.js";
import { append, badge, el, link, pageHeader } from "../core.js";

function featureCard(feature) {
  const card = el("article", "ps-card feature-directory-card");
  const body = el("div", "ps-card__body");
  const heading = el("div", "feature-directory-card__heading");
  const icon = el("span", "feature-directory-card__icon", feature.icon);
  icon.setAttribute("aria-hidden", "true");
  const copy = el("div");
  append(copy, el("p", "ps-card__eyebrow", feature.shortLabel), el("h2", "", feature.label));
  append(heading, icon, copy);
  const state = capabilityState(feature);
  const owner = el("dl", "feature-directory-card__facts");
  for (const [term, value] of [["Owner", feature.owner], ["Route", feature.frontendBase]]) {
    const row = el("div");
    append(row, el("dt", "", term), el("dd", term === "Route" ? "mono" : "", value));
    append(owner, row);
  }
  append(body, heading, el("p", "", feature.summary), owner);
  const actions = el("div", "feature-directory-card__actions");
  append(actions, badge(state.label, state.tone));
  if (feature.href) append(actions, link("Open research area", feature.href, "ps-button ps-button--primary"));
  else append(actions, el("span", "feature-directory-card__unavailable", "No live route yet"));
  append(body, actions);
  append(card, body);
  return card;
}

export function createFeaturesRoute({ config }) {
  return function renderFeatures(root) {
    append(root, pageHeader("Research workspace", "PropertyScope research areas", "Five independently owned feature slices share one product entry, visual language and evidence contract. Planned areas stay distinct from unavailable live services.", [link("View system status", "#system-status", "ps-button")]));
    const grid = el("div", "ps-grid ps-grid-2 feature-directory-grid");
    append(grid, ...featureRegistry(config).map(featureCard));
    append(root, grid);

    const boundary = el("aside", "product-disclaimer feature-directory-boundary");
    append(boundary, el("strong", "", "One application, independent ownership."), document.createTextNode(" Each feature owns its frontend, backend, database and domain decisions. Cross-feature work uses versioned HTTP contracts; no feature reads another feature's database."));
    append(root, boundary);
  };
}
