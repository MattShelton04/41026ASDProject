import { ENABLED_FEATURES } from "./generated/enabled-features.js";

const ENABLED_BY_KEY = new Map(ENABLED_FEATURES.map((item) => [item.featureKey, item]));

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
    aliases: ["feature-1"],
    implemented: true,
  },
  {
    id: "sales-market",
    slug: "market-intelligence",
    featureKey: "student-2-market-intelligence",
    label: "Sales and market",
    shortLabel: "Market intelligence",
    owner: "student-2",
    summary: "Review attributed sales and simple market summaries, and save research cases.",
    detail: "Recorded sale history, deterministic summaries and saved market cases.",
    icon: "$",
    frontendBase: "/features/market-intelligence/",
    defaultHash: "#market-cases",
    healthPath: "/api/shared-health/market-intelligence",
    implemented: false,
    aliases: ["feature-2"],
  },
  {
    id: "suburb-context",
    slug: "suburb-analytics",
    featureKey: "student-3-suburb-analytics",
    label: "Suburb context",
    shortLabel: "Suburb analytics",
    owner: "student-3",
    summary: "Explore suburb, crime, liveability and amenity evidence, and save favourite suburbs.",
    detail: "Suburb, crime, liveability and amenity evidence with saved selections.",
    icon: "◎",
    frontendBase: "/features/suburb-analytics/",
    defaultHash: "#suburbs",
    healthPath: "/api/shared-health/suburb-analytics",
    implemented: false,
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
    aliases: ["feature-4"],
  },
  {
    id: "buyer-workspace",
    slug: "buyer-workspaces",
    featureKey: "student-5-buyer-workspaces",
    label: "Buyer workspace",
    shortLabel: "Buyer workspace",
    owner: "student-5",
    summary: "Manage buyer cases, shortlists, journey stages, notes and tasks with related research.",
    detail: "Buyer cases, shortlisted properties, notes, tasks and evidence-aware next actions.",
    icon: "□",
    frontendBase: "/features/buyer-workspaces/",
    defaultHash: "#workspace",
    healthPath: "/api/shared-health/buyer-workspaces",
    implemented: false,
    aliases: ["feature-5"],
  },
];

const PROJECTED_DEFINITIONS = DEFINITIONS.map((item) => {
  const enabled = ENABLED_BY_KEY.get(item.featureKey);
  return Object.freeze({
    ...item,
    implemented: Boolean(enabled),
    enabled: Boolean(enabled),
    frontendBase: enabled?.frontendBase || item.frontendBase,
    healthPath: enabled?.publicHealthPath || item.healthPath,
    aliases: Object.freeze([...item.aliases]),
  });
});

for (const enabled of ENABLED_FEATURES) {
  if (DEFINITIONS.some((item) => item.featureKey === enabled.featureKey)) continue;
  const slug = enabled.frontendBase?.split("/").filter(Boolean).at(-1) || enabled.featureKey;
  PROJECTED_DEFINITIONS.push(Object.freeze({
    id: enabled.featureKey,
    slug,
    featureKey: enabled.featureKey,
    label: enabled.displayName,
    shortLabel: enabled.displayName,
    owner: enabled.owner,
    summary: enabled.displayName,
    detail: enabled.displayName,
    icon: "•",
    frontendBase: enabled.frontendBase,
    defaultHash: "",
    healthPath: enabled.publicHealthPath,
    aliases: Object.freeze([]),
    implemented: true,
    enabled: true,
  }));
}

export const FEATURE_DEFINITIONS = Object.freeze(PROJECTED_DEFINITIONS);

function configuredHref(definition, config) {
  if (config.featureHrefs?.[definition.id]) return config.featureHrefs[definition.id];
  return `${definition.frontendBase}${definition.defaultHash}`;
}

export function featureRegistry(config = {}) {
  return FEATURE_DEFINITIONS.map((definition) => Object.freeze({
    ...definition,
    href: definition.enabled ? configuredHref(definition, config) : undefined,
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
