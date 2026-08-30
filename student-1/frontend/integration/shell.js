/** Feature 1's public adapter for the domain-neutral Shared product shell. */

const DEFAULT_LINKS = Object.freeze({
  propertyDiscovery: "/features/data-platform/#properties",
  dataOperations: "/features/data-platform/#overview",
  releaseDetail: "/features/data-platform/#releases/",
  agentRuns: "/operations/ai-mode/?feature_key=student-1-propertyscope-data-platform&feature_label=Property%20data&return_to=%2Ffeatures%2Fdata-platform%2F%23properties",
});

const FEATURE_KEY = "student-1-propertyscope-data-platform";
const FEATURE_ALIASES = new Set([FEATURE_KEY, "feature-1"]);

function acceptedReleaseReferences(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return items.filter((item) => item.target_feature === "feature-1").map((item) => ({
    id: item.id,
    dataset: item.dataset_id || "Unnamed dataset",
    area: "Property data",
    version: item.release_version || "Unknown",
    records: item.record_count,
    acceptedAt: item.accepted_at,
    coverage: item.coverage_json?.complete === true ? "confirmed" : item.coverage_json ? "partial" : "unknown",
    hash: item.content_sha256 || "",
  }));
}

function agentRunReferences(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return items.filter((item) => FEATURE_ALIASES.has(item.feature_key)).map((item) => ({
    id: item.id,
    area: "Property data",
    objective: item.objective_preview || "Objective hidden by policy",
    status: item.status || "unknown",
    updatedAt: item.updated_at,
  }));
}

function absoluteUrl(base, currentHref) {
  return new URL(base, currentHref).href;
}

export function createFeature1ShellAdapter(overrides = {}) {
  const links = Object.freeze(Object.fromEntries(Object.entries(DEFAULT_LINKS).map(([key, value]) => [
    key,
    typeof overrides[key] === "string" && overrides[key] ? overrides[key] : value,
  ])));
  return Object.freeze({
    links,
    primarySearchHref(query, currentHref) {
      const target = new URL(links.propertyDiscovery, currentHref);
      if (query) {
        const hashBase = target.hash.split("?")[0] || "#properties";
        target.hash = `${hashBase}?q=${encodeURIComponent(query)}`;
      }
      return target.href;
    },
    statusDependencies(component) {
      const databaseCheck = component.payload?.checks?.database;
      const legacyReady = component.payload?.dependencies?.database;
      const rawStatus = databaseCheck?.status ?? legacyReady;
      return [{
        name: "Property data store",
        kind: "Owned dependency",
        owner: "Property data service",
        rawStatus,
        detail: databaseCheck?.detail || (legacyReady === true
          ? "The Property data service reports its data store ready."
          : "The owned data-store readiness check did not pass."),
      }];
    },
    evidence: Object.freeze({
      action: Object.freeze({
        label: "Open Property data",
        href: links.dataOperations,
      }),
      copy: Object.freeze({
        headerDescription: "See the published datasets and AI reviews behind PropertyScope results.",
        releasePanelDescription: "The versions currently available to property research.",
        agentPanelDescription: "Read-only links to recorded Property data AI reviews and their results.",
        releaseEmpty: "No conclusion about source data can be made from this empty index.",
        releaseError: "Open Property data operations for the current record.",
        agentEmpty: "Property search and data operations remain available without model activity.",
        agentError: "Published data references remain visible.",
        transitionLabel: "Opens in Property data",
      }),
      published: Object.freeze({
        path: "/api/data-platform/v1/dataset-releases?status=accepted&limit=20",
        project: acceptedReleaseReferences,
        href(id, currentHref) { return absoluteUrl(`${links.releaseDetail}${encodeURIComponent(id)}`, currentHref); },
      }),
      agentRuns: Object.freeze({
        path: "/api/ai-mode/agent-runs?limit=10",
        project: agentRunReferences,
        href(id, currentHref) {
          const target = new URL(links.agentRuns, currentHref);
          target.searchParams.set("run", id);
          return target.href;
        },
      }),
    }),
  });
}

export { acceptedReleaseReferences, agentRunReferences };
