import { createAiChat, createAssistantClient } from "../ai-chat/index.js";
import { notice } from "../core.js";

export const SHARED_ASSISTANT_SCOPES = Object.freeze([
  { id: "application", label: "All of PropertyScope", description: "Website guidance plus every currently available research area." },
  { id: "feature", label: "Property data", description: "Property records, sources, updates, releases, quality and coverage." },
]);

export function sharedAssistantSuggestions(scope) {
  return scope === "application"
    ? ["What can PropertyScope help me research?", "Which research areas are available now?", "How does AI activity stay reviewable?"]
    : ["Which Property data sources are available?", "Explain candidate and accepted datasets.", "Find an accepted property record in Parramatta."];
}

function assistantScope(hash) {
  const value = new URLSearchParams(String(hash).split("?")[1] || "").get("scope");
  return value === "feature" ? "feature" : "application";
}

function activityHref(runId) {
  const params = new URLSearchParams({
    feature_key: "student-1-propertyscope-data-platform",
    feature_label: "Property data",
    return_to: "/#assistant",
    run: runId,
  });
  return `/operations/ai-mode/?${params}`;
}

export function createAssistantRoute({ announce = () => {} } = {}) {
  let active = null;
  return async (root) => {
    active?.destroy();
    const client = createAssistantClient({ apiRoot: "/api/data-platform/v1/assistant" });
    let guide = null;
    try {
      guide = (await client.capabilities()).body;
    } catch { /* rendered as a safe degraded state after the component mounts */ }
    active = createAiChat({
      root,
      client,
      initialScope: assistantScope(location.hash),
      scopes: SHARED_ASSISTANT_SCOPES,
      suggestions: (scope) => guide?.suggested_questions?.length && scope === "application"
        ? guide.suggested_questions.slice(0, 4)
        : sharedAssistantSuggestions(scope),
      activityHref,
      announce,
      title: "Ask PropertyScope",
      description: "Ask about the application or use the currently available Property data tools. Every message creates one durable run with visible status, evidence and a full activity record.",
    });
    if (!guide) {
      root.querySelector(".ps-ai-chat__intro")?.after(
        notice("warning", "Capability guide unavailable", "The assistant can still start a turn, but current scope guidance could not be refreshed."),
      );
    }
    return active;
  };
}
