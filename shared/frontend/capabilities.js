import { featureRegistry } from "./features.js?v=9";

export const RELEASE_STAGES = Object.freeze([
  {
    id: "Available now",
    label: "Property records and data operations",
    state: "current",
    summary: "Search NSW property records, inspect their evidence and maintain the datasets behind them.",
    capabilities: ["Property identity search", "Source and update history", "Published data review", "Recorded AI reviews"],
  },
  {
    id: "Planned next",
    label: "Cited document research",
    state: "planned",
    summary: "Add curated document research with citations and visible retrieval failures.",
    capabilities: ["Structured research tools", "Curated document retrieval", "Citation checks", "Clear unavailable states"],
  },
  {
    id: "Planned later",
    label: "Coordinated research workflows",
    state: "planned",
    summary: "Coordinate specialised research roles while keeping review decisions with people.",
    capabilities: ["Specialised research roles", "Human review queue", "Hosted deployment", "Mode-specific availability"],
  },
]);

export function capabilityManifest(config = {}) {
  return {
    release: "release-0",
    deploymentMode: "local",
    features: featureRegistry(config),
    services: [
      { id: "shared-shell", label: "Shared product shell", implemented: true, enabled: true, detail: "Navigation, availability and shared operational views." },
      { id: "ai-mode", label: "AI review history", implemented: true, enabled: true, href: config.agentRuns, detail: "Recorded AI reviews, source checks and results." },
      { id: "mcp", label: "Structured tool access", implemented: false, enabled: false, detail: "Planned; not active." },
      { id: "rag", label: "Cited document retrieval", implemented: false, enabled: false, detail: "Planned; not active." },
      { id: "multi-agent", label: "Coordinated research roles", implemented: false, enabled: false, detail: "Planned; not active." },
    ],
  };
}

export function capabilityState(item) {
  if (!item.implemented) return { label: "Planned", tone: "planned" };
  if (!item.enabled) return { label: "Unavailable", tone: "partial" };
  return { label: "Available", tone: "confirmed" };
}
