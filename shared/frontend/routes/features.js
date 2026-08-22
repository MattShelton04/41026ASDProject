import { capabilityState } from "../capabilities.js?v=9";
import { featureRegistry } from "../features.js?v=9";
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
  append(body, heading, el("p", "", feature.summary));
  const actions = el("div", "feature-directory-card__actions");
  append(actions, badge(state.label, state.tone));
  if (feature.href) append(actions, link("Open research area", feature.href, "ps-button ps-button--primary"));
  else append(actions, el("span", "feature-directory-card__unavailable", "Coming later"));
  append(body, actions);
  append(card, body);
  return card;
}

export function createFeaturesRoute({ config }) {
  return function renderFeatures(root) {
    append(root, pageHeader("Research workspace", "PropertyScope research areas", "Start with a verified property record, then add market, suburb, site and planning context as those research tools become available.", [link("Check what’s available", "#release-roadmap", "ps-button")]));
    const grid = el("div", "ps-grid ps-grid-2 feature-directory-grid");
    append(grid, ...featureRegistry(config).map(featureCard));
    append(root, grid);

    const boundary = el("aside", "product-disclaimer feature-directory-boundary");
    append(boundary, el("strong", "", "Property records are available now."), document.createTextNode(" Other research areas are clearly marked as planned and cannot be opened until they are ready."));
    append(root, boundary);
  };
}
