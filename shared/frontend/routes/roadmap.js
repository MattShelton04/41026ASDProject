import { capabilityManifest, capabilityState, RELEASE_STAGES } from "../capabilities.js";
import { append, badge, cell, el, link, notice, pageHeader, panel, table } from "../core.js";

function stageCard(stage) {
  const card = el("article", `ps-card roadmap-card roadmap-card--${stage.state}`);
  const body = el("div", "ps-card__body");
  const label = stage.state === "current" ? "Available" : "Planned";
  append(body, badge(label, stage.state === "current" ? "confirmed" : "planned"), el("p", "ps-card__eyebrow", stage.id), el("h2", "", stage.label), el("p", "", stage.summary));
  const list = el("ul", "roadmap-list");
  for (const item of stage.capabilities) append(list, el("li", "", item));
  append(body, list);
  append(card, body);
  return card;
}

export function createRoadmapRoute({ config }) {
  return function renderRoadmap(root) {
    const manifest = capabilityManifest(config);
    append(root, pageHeader("PropertyScope", "What’s available", "See which research tools you can use today and what is coming later.", [link("View data status", "#system-status", "ps-button ps-button--primary")]));
    const mode = notice("success", "Property data is available", "Address search, source details, data updates and AI review history are ready to use.");
    append(root, mode);
    const stages = el("div", "ps-grid ps-grid-3 roadmap-grid");
    append(stages, ...RELEASE_STAGES.map(stageCard));
    append(root, stages);

    const capabilityPanel = panel("Detailed availability", "Planned tools are shown separately from services that are temporarily unavailable.");
    const rows = [
      ...manifest.features.map((item) => ({ ...item, group: "Research area" })),
      ...manifest.services.map((item) => ({ ...item, group: "Shared service" })),
    ];
    append(capabilityPanel.body, table(["Tool", "Type", "Availability", "What it provides"], rows, (item) => {
      const tr = el("tr");
      const name = el("div", "table-primary");
      append(name, item.href ? link(item.label, item.href) : el("strong", "", item.label));
      const state = capabilityState(item);
      append(tr, cell(name), cell(item.group), cell(badge(state.label, state.tone)), cell(item.detail));
      return tr;
    }, "PropertyScope availability"));
    append(root, capabilityPanel.card);
  };
}
