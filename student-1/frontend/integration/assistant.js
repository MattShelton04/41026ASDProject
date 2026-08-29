/** Feature-owned vocabulary and exact page-context projection for Shared AI chat. */

export const FEATURE_ASSISTANT_SCOPES = Object.freeze([
  { id: "feature", label: "Property data", description: "Property records, sources, updates, releases, quality and coverage." },
]);

const UUID_INPUT_PATTERN = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}";

export const FEATURE_ASSISTANT_CONTEXTS = Object.freeze([
  {
    id: "general",
    label: "General Property data question",
    description: "Ask without linking a specific page record.",
    context: {},
  },
  {
    id: "release",
    label: "Dataset release",
    description: "Link the exact candidate, accepted or historical release you want explained.",
    context: { route: "releases/detail" },
    parameter: {
      name: "release_id",
      label: "Release ID",
      placeholder: "00000000-0000-4000-8000-000000000000",
      pattern: UUID_INPUT_PATTERN,
      help: "Copy the release ID from its Published data page.",
    },
  },
  {
    id: "run",
    label: "Data update",
    description: "Link the exact update whose saved progress or outcome you want explained.",
    context: { route: "runs/detail" },
    parameter: {
      name: "ingestion_run_id",
      label: "Update ID",
      placeholder: "00000000-0000-4000-8000-000000000000",
      pattern: UUID_INPUT_PATTERN,
      help: "Copy the update ID from its Update history page.",
    },
  },
  {
    id: "property",
    label: "Property record",
    description: "Link an exact accepted property record from Property search.",
    context: { route: "properties/detail" },
    parameter: {
      name: "property_ref",
      label: "Property reference",
      placeholder: "00000000-0000-4000-8000-000000000000",
      pattern: UUID_INPUT_PATTERN,
      help: "Copy the property reference from its property detail page.",
    },
  },
]);

export function featureAssistantSuggestions() {
  return [
    "Which Property data sources are available?",
    "Explain candidate and accepted datasets.",
    "Find an accepted property record in Parramatta.",
  ];
}

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CONTEXT_PARAMETERS = Object.freeze({
  "releases/detail": "release_id",
  "runs/detail": "ingestion_run_id",
  "properties/detail": "property_ref",
});

export function assistantContextFromHash(hash = "") {
  const query = new URLSearchParams(String(hash).split("?")[1] || "");
  const route = query.get("route");
  const parameter = CONTEXT_PARAMETERS[route];
  const value = parameter ? query.get(parameter) : "";
  return parameter && value && UUID_PATTERN.test(value)
    ? { route, [parameter]: value }
    : {};
}
