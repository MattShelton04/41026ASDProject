/** Feature-owned vocabulary and exact page-context projection for Shared AI chat. */
import { requestJson, collection, entity } from "../core/api.js";
import { createAssistantClient } from "../ai-chat/index.js";
import { propertyActivityUrl } from "./activity.js";

export const FEATURE_ASSISTANT_SCOPES = Object.freeze([
  { id: "feature", label: "Property data", description: "Property records, sources, updates, releases, quality and coverage." },
]);

const UUID_INPUT_PATTERN = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";

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
      label: "Dataset name or release ID",
      placeholder: "Address register, or an exact release GUID",
      pattern: UUID_INPUT_PATTERN,
      searchParameter: "query",
      help: "An ID links directly. A name asks the assistant to search the bounded release inventory and clarify matches.",
    },
  },
  {
    id: "run",
    label: "Data update",
    description: "Link the exact update whose saved progress or outcome you want explained.",
    context: { route: "runs/detail" },
    parameter: {
      name: "ingestion_run_id",
      label: "Update name or ID",
      placeholder: "Government schools, or an exact update GUID",
      pattern: UUID_INPUT_PATTERN,
      searchParameter: "query",
      help: "An ID links directly. A name asks the assistant to search the recent update inventory and clarify matches.",
    },
  },
  {
    id: "property",
    label: "Property record",
    description: "Link an exact accepted property record from Property search.",
    context: { route: "properties/detail" },
    parameter: {
      name: "property_ref",
      label: "Address or property reference",
      placeholder: "A NSW address, or an exact property GUID",
      pattern: UUID_INPUT_PATTERN,
      searchParameter: "query",
      help: "An ID links directly. An address asks the assistant to search accepted records before inspecting a match.",
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

const UUID_PATTERN = new RegExp(`^${UUID_INPUT_PATTERN}$`);
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
  if (!parameter) return {};
  const displayLabel = String(query.get("display_label") || "").trim().slice(0, 200);
  if (value && UUID_PATTERN.test(value)) {
    return { route, [parameter]: value, ...(displayLabel ? { display_label: displayLabel } : {}) };
  }
  const search = String(query.get("query") || "").trim().slice(0, 200);
  return !value && search.length >= 2 ? { route, query: search } : {};
}

export function assistantDraftFromHash(hash = "") {
  const query = new URLSearchParams(String(hash).split("?")[1] || "");
  return String(query.get("draft") || "").trim().slice(0, 2000);
}

export const FEATURE_TOOL_LABELS = Object.freeze({
  "context.retrieve.v1": "Project guidance",
  "property.search.v1": "Search accepted addresses",
  "property.locality_summary.v1": "Count accepted addresses",
  "property.inspect.v1": "Property and sale records",
  "data.coverage.v1": "Published research coverage",
  "data.releases.v1": "Dataset releases",
  "data.runs.v1": "Data updates",
  "data.sources.v1": "Data sources",
  "platform.capabilities.v1": "Available research tools",
  "data.release_inspect.v1": "Release details",
  "data.run_inspect.v1": "Update details",
  "data.run_explain.v1": "Recorded update progress",
  "data.release_compare.v1": "Compare releases",
});

export async function searchAssistantContext(kind, query, { signal, fetcher = (...args) => globalThis.fetch(...args) } = {}) {
  const definition = FEATURE_ASSISTANT_CONTEXTS.find((item) => item.id === kind);
  if (!definition?.parameter) return { items: [] };
  const resource = { property: "properties", release: "dataset-releases", run: "ingestion-runs" }[kind];
  const exact = UUID_PATTERN.test(query);
  const path = exact ? `${resource}/${encodeURIComponent(query)}`
    : kind === "property" ? `properties/search?q=${encodeURIComponent(query)}&state=NSW&limit=8`
      : `${resource}?q=${encodeURIComponent(query)}&limit=50`;
  const { body } = await requestJson(fetcher, path, { signal });
  const rows = exact ? [entity(body)] : collection(body);
  const matches = rows.map((item) => {
    const id = kind === "property" ? item.property_ref : item.id;
    const name = kind === "property" ? item.address_display || item.display_address
      : item.source_name || item.job_name || item.dataset_name || item.dataset_id || item.name || id;
    const label = kind === "property" ? name : `${name} · ${item.status || "recorded"} · ${id}`;
    return { label: String(label || id), context: { ...definition.context, [definition.parameter.name]: id } };
  }).filter((item) => UUID_PATTERN.test(item.context[definition.parameter.name] || ""));
  return { items: matches.slice(0, 8), note: matches.length
    ? "Select a record. These are the first matches from a bounded search."
    : "No matches in this search. Try a fuller name, paste an ID, or keep the name for the assistant to check." };
}

export function propertyAssistantOptions({ announce = null, context = {} } = {}) {
  return {
    client: createAssistantClient({ apiRoot: "/api/data-platform/v1/assistant" }),
    initialScope: "feature", scopes: FEATURE_ASSISTANT_SCOPES,
    contextOptions: FEATURE_ASSISTANT_CONTEXTS, searchContext: searchAssistantContext,
    suggestions: featureAssistantSuggestions, toolLabels: FEATURE_TOOL_LABELS,
    context, announce,
    activityHref: (runId) => propertyActivityUrl(runId, {
      baseUrl: document.baseURI, activityUrl: window.PROPERTYSCOPE_AGENT_ACTIVITY_URL,
      returnTo: `/features/data-platform/${location.hash.startsWith("#ai") ? location.hash : location.hash.startsWith("#assistant") ? "#assistant" : "#properties"}`,
    }),
  };
}
