export const RELEASE_STAGES = Object.freeze([
  {
    id: "release-0",
    label: "Integrated foundations",
    state: "current",
    summary: "Independent feature services, deterministic CRUD, shared AI activity and local Compose operation.",
    capabilities: ["Shared product navigation", "Feature-owned APIs and stores", "Bounded Plan → Act → Observe → Adapt", "Human review for protected actions"],
  },
  {
    id: "release-1",
    label: "Grounded intelligence",
    state: "planned",
    summary: "Separate MCP and RAG services add structured tools and cited documents after foundation acceptance.",
    capabilities: ["MCP tool and resource access", "Curated document retrieval", "Citation and grounding checks", "Independent retrieval failure states"],
  },
  {
    id: "release-2",
    label: "Multi-agent and cloud",
    state: "planned",
    summary: "Local planner, worker and reviewer roles plus an intentionally reduced cloud capability set.",
    capabilities: ["Planner, worker and reviewer roles", "Human review queue", "Cloud deployment", "Mode-specific capability gates"],
  },
]);

export function capabilityManifest(config = {}) {
  return {
    release: "release-0",
    deploymentMode: "local",
    features: [
      { id: "property-records", label: "Property records", implemented: true, enabled: true, href: config.propertyDiscovery, detail: "Identity, provenance, ingestion and accepted data." },
      { id: "sales-market", label: "Sales and market", implemented: false, enabled: false, detail: "Awaiting its independently owned service." },
      { id: "suburb-context", label: "Suburb context", implemented: false, enabled: false, detail: "Awaiting its independently owned service." },
      { id: "site-planning", label: "Site and planning", implemented: false, enabled: false, detail: "Awaiting its independently owned service." },
      { id: "buyer-workspace", label: "Buyer workspace", implemented: false, enabled: false, detail: "Awaiting supporting research services." },
    ],
    services: [
      { id: "shared-shell", label: "Shared product shell", implemented: true, enabled: true, detail: "Navigation, availability and shared operational views." },
      { id: "ai-mode", label: "Agent activity", implemented: true, enabled: true, href: config.agentRuns, detail: "Durable bounded agent-run evidence." },
      { id: "mcp", label: "MCP", implemented: false, enabled: false, detail: "Release 1 capability; not active." },
      { id: "rag", label: "RAG", implemented: false, enabled: false, detail: "Release 1 capability; not active." },
      { id: "multi-agent", label: "Multi-agent", implemented: false, enabled: false, detail: "Release 2 local capability; not active." },
    ],
  };
}

export function capabilityState(item) {
  if (!item.implemented) return { label: "Planned", tone: "planned" };
  if (!item.enabled) return { label: "Disabled", tone: "partial" };
  return { label: "Enabled", tone: "confirmed" };
}
