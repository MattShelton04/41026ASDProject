const DEFINITIONS = [
  {
    id: "property-records",
    slug: "data-platform",
    featureKey: "student-1-propertyscope-data-platform",
    label: "Property records",
    shortLabel: "Property records",
    owner: "student-1",
    summary: "Search NSW addresses and review available sources, coordinates and published datasets.",
    detail: "Property identities, sources, data updates and published datasets.",
    icon: "⌂",
    frontendBase: "/features/data-platform/",
    defaultHash: "#properties",
    healthPath: "/api/shared-health/data-platform",
    implemented: true,
    enabled: true,
  },
  {
    id: "sales-market",
    slug: "market-intelligence",
    featureKey: "student-2-market-intelligence",
    label: "Sales and market",
    shortLabel: "Market intelligence",
    owner: "student-2",
    summary: "Review recorded sales, comparable properties and local market context.",
    detail: "Recorded sales, comparable properties and market research.",
    icon: "$",
    frontendBase: "/features/market-intelligence/",
    defaultHash: "#market-cases",
    healthPath: "/api/shared-health/market-intelligence",
    implemented: false,
    enabled: false,
  },
  {
    id: "suburb-context",
    slug: "suburb-analytics",
    featureKey: "student-3-suburb-analytics",
    label: "Suburb context",
    shortLabel: "Suburb analytics",
    owner: "student-3",
    summary: "Crime trends, schools, local places and neutral area context with saved comparisons.",
    detail: "Crime, place and area evidence with saved comparisons.",
    icon: "◎",
    frontendBase: "/features/suburb-analytics/",
    defaultHash: "#suburb-comparisons",
    healthPath: "/api/shared-health/suburb-analytics",
    implemented: false,
    enabled: false,
  },
  {
    id: "site-planning",
    slug: "due-diligence",
    featureKey: "student-4-due-diligence",
    label: "Site and planning",
    shortLabel: "Due diligence",
    owner: "student-4",
    summary: "Review available planning, environmental, strata and building information.",
    detail: "Site, planning and building information with visible gaps.",
    icon: "⌗",
    frontendBase: "/features/due-diligence/",
    defaultHash: "#site-reviews",
    healthPath: "/api/shared-health/due-diligence",
    implemented: false,
    enabled: false,
  },
  {
    id: "buyer-workspace",
    slug: "buyer-workspaces",
    featureKey: "student-5-buyer-workspaces",
    label: "Buyer workspace",
    shortLabel: "Buyer workspace",
    owner: "student-5",
    summary: "Keep property shortlists, saved reports, open questions and follow-up tasks together.",
    detail: "Buyer profiles, watchlists, saved reports and follow-up work.",
    icon: "□",
    frontendBase: "/features/buyer-workspaces/",
    defaultHash: "#workspace",
    healthPath: "/api/shared-health/buyer-workspaces",
    implemented: false,
    enabled: false,
  },
];

export const FEATURE_DEFINITIONS = Object.freeze(DEFINITIONS.map((item) => Object.freeze({ ...item })));

function configuredHref(definition, config) {
  if (definition.id === "property-records" && config.propertyDiscovery) return config.propertyDiscovery;
  return `${definition.frontendBase}${definition.defaultHash}`;
}

export function featureRegistry(config = {}) {
  return FEATURE_DEFINITIONS.map((definition) => Object.freeze({
    ...definition,
    href: definition.implemented && definition.enabled ? configuredHref(definition, config) : undefined,
  }));
}

export function findFeature(id, config = {}) {
  return featureRegistry(config).find((item) => item.id === id || item.slug === id || item.featureKey === id);
}
