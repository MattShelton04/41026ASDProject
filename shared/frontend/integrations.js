const REQUIRED_METHODS = Object.freeze(["primarySearchHref", "healthDependencies"]);

export async function loadFeatureIntegration(modulePath, overrides = {}, importer = (path) => import(path)) {
  if (!modulePath) throw new TypeError("An enabled feature must declare an integration module.");
  const module = await importer(modulePath);
  if (typeof module.createShellIntegration !== "function") {
    throw new TypeError("A feature integration module must export createShellIntegration().");
  }
  const integration = module.createShellIntegration(overrides);
  for (const method of REQUIRED_METHODS) {
    if (typeof integration?.[method] !== "function") {
      throw new TypeError(`Feature integration is missing ${method}().`);
    }
  }
  if (!integration.links || !integration.evidence || !integration.featureHrefs) {
    throw new TypeError("Feature integration must expose links, featureHrefs and evidence contracts.");
  }
  return integration;
}

export function unavailableFeatureIntegration(feature, overrides = {}) {
  const primaryHref = overrides.propertyDiscovery || feature?.href || "/#features";
  const links = Object.freeze({
    propertyDiscovery: primaryHref,
    dataOperations: overrides.dataOperations || primaryHref,
    releaseDetail: overrides.releaseDetail || primaryHref,
    agentRuns: overrides.agentRuns || "/operations/ai-mode/",
  });
  return Object.freeze({
    links,
    featureHrefs: Object.freeze(feature?.id ? { [feature.id]: primaryHref } : {}),
    primarySearchHref(_query, currentHref) { return new URL(primaryHref, currentHref).href; },
    healthDependencies() { return []; },
    evidence: Object.freeze({
      publishedPath: "",
      projectPublished() { return []; },
      publishedHref(_id, currentHref) { return new URL(primaryHref, currentHref).href; },
      agentRunsPath: "/api/ai-mode/agent-runs?limit=10",
      agentRunHref(id, currentHref) {
        const target = new URL(links.agentRuns, currentHref);
        target.searchParams.set("run", id);
        return target.href;
      },
    }),
  });
}
