/** Feature-owned vocabulary and exact page-context projection for Shared AI chat. */

export const FEATURE_ASSISTANT_SCOPES = Object.freeze([
  { id: "feature", label: "Property data", description: "Property records, sources, updates, releases, quality and coverage." },
]);

export function featureAssistantSuggestions() {
  return [
    "Which Property data sources are available?",
    "Explain candidate and accepted datasets.",
    "Find an accepted property record in Parramatta.",
  ];
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const ROUTE_PATTERN = /^[a-z0-9/_-]{1,80}$/;

export function assistantContextFromHash(hash = "") {
  const query = new URLSearchParams(String(hash).split("?")[1] || "");
  const context = {};
  const route = query.get("route");
  if (route && ROUTE_PATTERN.test(route)) context.route = route;
  for (const name of ["release_id", "ingestion_run_id", "property_ref"]) {
    const value = query.get(name);
    if (value && UUID_PATTERN.test(value)) context[name] = value;
  }
  return context;
}
