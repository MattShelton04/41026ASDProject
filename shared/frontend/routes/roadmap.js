import { capabilityManifest, capabilityState, RELEASE_STAGES } from "../capabilities.js";
import { append, badge, cell, el, link, notice, pageHeader, panel, table } from "../core.js";

function stageCard(stage) {
  const card = el("article", `ps-card roadmap-card roadmap-card--${stage.state}`);
  const body = el("div", "ps-card__body");
  const label = stage.state === "current" ? "Current foundation" : "Planned";
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
    append(root, pageHeader("Shared capability plan", "Capability roadmap", "Implemented and enabled are separate. Future research and AI capabilities stay visibly gated until their independently owned services exist.", [link("View live status", "#system-status", "ps-button ps-button--primary")]));
    const mode = notice("success", "Local foundation mode", "Property records and shared agent activity are enabled. MCP, RAG and multi-agent are not part of this release and ordinary CRUD does not depend on them.");
    append(root, mode);
    const stages = el("div", "ps-grid ps-grid-3 roadmap-grid");
    append(stages, ...RELEASE_STAGES.map(stageCard));
    append(root, stages);

    const capabilityPanel = panel("Deployment capability manifest", `${manifest.release} · ${manifest.deploymentMode} deployment. Planned capability is not treated as a runtime failure.`);
    const rows = [
      ...manifest.features.map((item) => ({ ...item, group: "Research area" })),
      ...manifest.services.map((item) => ({ ...item, group: "Shared service" })),
    ];
    append(capabilityPanel.body, table(["Capability", "Kind", "Implemented", "Enabled", "Availability"], rows, (item) => {
      const tr = el("tr");
      const name = el("div", "table-primary");
      append(name, item.href ? link(item.label, item.href) : el("strong", "", item.label), el("span", "table-secondary", item.detail));
      const state = capabilityState(item);
      append(tr, cell(name), cell(item.group), cell(item.implemented ? "Yes" : "No"), cell(item.enabled ? "Yes" : "No"), cell(badge(state.label, state.tone)));
      return tr;
    }, "Current deployment capability manifest"));
    append(root, capabilityPanel.card);
  };
}
