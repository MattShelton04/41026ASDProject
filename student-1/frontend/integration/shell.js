/** Feature 1's public adapter for the domain-neutral Shared product shell. */

const DEFAULT_LINKS = Object.freeze({
  propertyDiscovery: "/features/data-platform/#properties",
  dataOperations: "/features/data-platform/#overview",
  releaseDetail: "/features/data-platform/#releases/",
  agentRuns: "/operations/ai-mode/?feature_key=student-1-propertyscope-data-platform",
});

const FEATURE_KEY = "student-1-propertyscope-data-platform";

function acceptedReleaseReferences(payload) {
  const items = Array.isArray(payload?.items) ? payload.items : [];
  return items.filter((item) => item.target_feature === "feature-1").map((item) => ({
    id: item.id,
    dataset: item.dataset_id || "Unnamed dataset",
    areaKey: item.target_feature,
    version: item.release_version || "Unknown",
    records: item.record_count,
    acceptedAt: item.accepted_at,
    coverage: item.coverage_json?.complete === true ? "confirmed" : item.coverage_json ? "partial" : "unknown",
    hash: item.content_sha256 || "",
  }));
}

function absoluteUrl(base, currentHref) {
  return new URL(base, currentHref).href;
}

export function createShellIntegration(overrides = {}) {
  const links = Object.freeze(Object.fromEntries(Object.entries(DEFAULT_LINKS).map(([key, value]) => [
    key,
    typeof overrides[key] === "string" && overrides[key] ? overrides[key] : value,
  ])));
  return Object.freeze({
    links,
    featureHrefs: Object.freeze({ "property-records": links.propertyDiscovery }),
    primarySearchHref(query, currentHref) {
      const target = new URL(links.propertyDiscovery, currentHref);
      if (query) {
        const hashBase = target.hash.split("?")[0] || "#properties";
        target.hash = `${hashBase}?q=${encodeURIComponent(query)}`;
      }
      return target.href;
    },
    healthDependencies(component) {
      return [{
        name: "Property data store",
        kind: "Owned dependency",
        owner: "Property data service",
        rawStatus: component.payload?.dependencies?.database,
        detail: component.payload?.dependencies?.database === true
          ? "The Property data service reports its data store ready."
          : "The owned data-store readiness check did not pass.",
      }];
    },
    evidence: Object.freeze({
      publishedPath: "/api/data-platform/v1/dataset-releases?status=accepted&limit=20",
      projectPublished: acceptedReleaseReferences,
      publishedHref(id, currentHref) {
        return absoluteUrl(`${links.releaseDetail}${encodeURIComponent(id)}`, currentHref);
      },
      agentRunsPath: "/api/ai-mode/agent-runs?limit=10",
      agentRunHref(id, currentHref) {
        const target = new URL(links.agentRuns, currentHref);
        target.searchParams.set("feature_key", FEATURE_KEY);
        target.searchParams.set("run", id);
        return target.href;
      },
    }),
  });
}

export { acceptedReleaseReferences };
