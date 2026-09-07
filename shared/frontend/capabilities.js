import { featureRegistry } from "./features.js";

export const RELEASE_STAGES = Object.freeze([
  {
    id: "Available now",
    label: "Property data",
    state: "current",
    summary: "Search NSW property records, inspect their evidence and maintain the datasets behind them.",
    capabilities: ["Property identity search", "Source and update history", "Published data review", "Recorded AI reviews"],
  },
  {
    id: "Implemented locally",
    label: "Cited document research",
    state: "implemented",
    summary: "Property data research can use curated project guidance with citations and visible retrieval failures when local services are enabled. Access in other research areas depends on their connected sources and tools.",
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

export function capabilityManifest(config = {}, snapshot = null) {
  const runtime = new Map((Array.isArray(snapshot?.services) ? snapshot.services : [])
    .filter((item) => item && ["mcp", "rag"].includes(item.id))
    .map((item) => [item.id, item]));
  function localService(id, label) {
    const observed = runtime.get(id);
    return {
      id, label, implemented: true,
      enabled: typeof observed?.enabled === "boolean" ? observed.enabled : null,
      status: typeof observed?.status === "string" ? observed.status : "unknown",
      detail: typeof observed?.detail === "string" ? observed.detail : "Implemented locally; runtime configuration and health have not been observed.",
    };
  }
  return {
    release: "release-1",
    deploymentMode: "local",
    features: featureRegistry(config),
    services: [
      { id: "shared-shell", label: "Shared product shell", implemented: true, enabled: true, detail: "Navigation, availability and shared operational views." },
      { id: "ai-mode", label: "AI review history", implemented: true, enabled: true, href: config.agentRuns, detail: "Recorded AI reviews, source checks and results." },
      localService("mcp", "Structured tool access (MCP)"),
      localService("rag", "Cited document retrieval (RAG)"),
      { id: "multi-agent", label: "Coordinated research roles", implemented: false, enabled: false, detail: "Planned; not active." },
    ],
  };
}

export function capabilityState(item) {
  if (!item.implemented) return { label: "Planned", tone: "planned" };
  if (item.enabled === null || item.enabled === undefined) return { label: "Runtime unknown", tone: "unknown" };
  if (item.status) {
    if (!item.enabled) return { label: "Disabled by configuration", tone: "unknown" };
    if (item.status === "ready") return { label: "Ready when checked", tone: "confirmed" };
    if (item.status === "unavailable") return { label: "Unavailable", tone: "partial" };
    return { label: "Enabled · health unknown", tone: "unknown" };
  }
  if (!item.enabled) return { label: "Unavailable", tone: "partial" };
  return { label: "Available", tone: "confirmed" };
}
