const DEFINITIONS = [
  {
    id: "property-records",
    slug: "data-platform",
    featureKey: "student-1-propertyscope-data-platform",
    label: "Property data",
    shortLabel: "Property data",
    owner: "student-1",
    summary: "Search NSW addresses and review available sources, coordinates and published datasets.",
    detail: "Property identities, sources, data updates and published datasets.",
    icon: "⌂",
    frontendBase: "/features/data-platform/",
    defaultHash: "#properties",
    healthPath: "/api/shared-health/data-platform",
    integrationModule: "/features/data-platform/integration/shell.js?v=1",
    aliases: ["feature-1"],
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
    aliases: ["feature-2"],
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
    aliases: ["feature-3"],
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
    aliases: ["feature-4"],
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
    aliases: ["feature-5"],
  },
];

export const FEATURE_DEFINITIONS = Object.freeze(DEFINITIONS.map((item) => Object.freeze({
  ...item,
  aliases: Object.freeze([...item.aliases]),
})));

function configuredHref(definition, config) {
  if (config.featureHrefs?.[definition.id]) return config.featureHrefs[definition.id];
  return `${definition.frontendBase}${definition.defaultHash}`;
}

export function featureRegistry(config = {}) {
  return FEATURE_DEFINITIONS.map((definition) => Object.freeze({
    ...definition,
    href: definition.implemented && definition.enabled ? configuredHref(definition, config) : undefined,
  }));
}

export function findFeature(id, config = {}) {
  return featureRegistry(config).find((item) => item.id === id || item.slug === id || item.featureKey === id || item.aliases.includes(id));
}

export function researchAreaLabel(value, config = {}) {
  const feature = findFeature(value, config);
  if (feature) return feature.label;
  const text = String(value ?? "").replaceAll("_", " ").replaceAll("-", " ");
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Unknown area";
}
