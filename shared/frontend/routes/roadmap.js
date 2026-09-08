import { capabilityManifest, capabilityState, RELEASE_STAGES } from "../capabilities.js";
import { append, badge, cell, el, link, notice, pageHeader, panel, requestJson, table } from "../core.js";

function stageCard(stage, index) {
  const card = el("article", `ps-card roadmap-card roadmap-card--${stage.state}`);
  const body = el("div", "ps-card__body");
  const label = stage.state === "current" ? "Available" : stage.state === "implemented" ? "Implemented · runtime dependent" : "Planned";
  append(body, el("span", "roadmap-number", String(index + 1).padStart(2, "0")), badge(label, stage.state === "current" ? "confirmed" : stage.state === "implemented" ? "unknown" : "planned"), el("p", "ps-card__eyebrow", stage.id), el("h2", "", stage.label), el("p", "", stage.summary));
  const list = el("ul", "roadmap-list");
  for (const item of stage.capabilities) append(list, el("li", "", item));
  append(body, list);
  append(card, body);
  return card;
}

export function createRoadmapRoute({ config, requestJson: requestJsonFn = requestJson }) {
  return async function renderRoadmap(root) {
    let manifest = capabilityManifest(config);
    append(root, pageHeader("PropertyScope", "What’s available", "See which research tools you can use today and what is coming later.", [link("View data status", "#system-status", "ps-button ps-button--primary")]));
    const mode = notice("success", "Workspaces, not a service-health guarantee", "Enabled research areas are listed below. Open Data status to check their current service availability.");
    append(root, mode);
    const stages = el("div", "ps-grid ps-grid-3 roadmap-grid");
    append(stages, ...RELEASE_STAGES.map((stage, index) => stageCard(stage.state === "current" ? {
      ...stage,
      label: "Evidence-led research",
      summary: "The research workspaces enabled in this deployment. Source coverage and live service health are separate checks.",
      capabilities: manifest.features.filter((item) => item.implemented && item.enabled).map((item) => item.label),
    } : stage, index)));
    append(root, stages);

    const capabilityPanel = panel("Detailed availability", "Planned tools are shown separately from services that are temporarily unavailable.");
    const runtimeNote = el("p", "", "Checking local research service configuration and health…");
    append(capabilityPanel.body, runtimeNote);
    function renderAvailability() {
      const rows = [
        ...manifest.features.map((item) => ({ ...item, group: "Research area" })),
        ...manifest.services.map((item) => ({ ...item, group: "Shared service" })),
      ];
      capabilityPanel.body.querySelector(".dashboard-table-wrap")?.remove();
      append(capabilityPanel.body, table(["Tool", "Type", "Availability", "What it provides"], rows, (item) => {
        const tr = el("tr");
        const name = el("div", "table-primary");
        append(name, item.href ? link(item.label, item.href) : el("strong", "", item.label));
        const state = capabilityState(item);
        append(tr, cell(name), cell(item.group), cell(badge(state.label, state.tone)), cell(item.detail));
        return tr;
      }, "PropertyScope availability"));
    }
    renderAvailability();
    append(root, capabilityPanel.card);
    try {
      const result = await requestJsonFn("/api/ai-mode/capabilities");
      manifest = capabilityManifest(config, result.body);
      runtimeNote.textContent = "Local service configuration and health checked. Readiness does not imply every feature has registered a corpus or that its evidence is complete.";
    } catch (error) {
      if (error.name === "AbortError") return;
      runtimeNote.textContent = "Runtime checks are unavailable. Local MCP and RAG are implemented, but their current configuration and health are unknown. Ordinary feature access is checked separately in Data status.";
    }
    renderAvailability();
  };
}
