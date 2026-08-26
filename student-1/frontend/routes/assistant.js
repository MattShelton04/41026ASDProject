import { createAiChat, createAssistantClient } from "../ai-chat/index.js";
import {
  FEATURE_ASSISTANT_SCOPES,
  assistantContextFromHash,
  featureAssistantSuggestions,
} from "../integration/assistant.js";

function activityHref(runId) {
  const integrated = window.location.pathname.startsWith("/features/data-platform/");
  const root = window.PROPERTYSCOPE_AGENT_ACTIVITY_URL
    || (integrated ? "/operations/ai-mode/" : `${window.location.protocol}//${window.location.hostname}:5005/operations/ai-mode/`);
  const url = new URL(root, window.location.href);
  url.searchParams.set("feature_key", "student-1-propertyscope-data-platform");
  url.searchParams.set("feature_label", "Property data");
  url.searchParams.set("return_to", "/features/data-platform/#assistant");
  url.searchParams.set("run", runId);
  return url.href;
}

export function createFeatureAssistantRoute({ view, announce = () => {} }) {
  let active = null;
  return {
    render() {
      active?.destroy();
      active = createAiChat({
        root: view,
        client: createAssistantClient({ apiRoot: "/api/data-platform/v1/assistant" }),
        initialScope: "feature",
        scopes: FEATURE_ASSISTANT_SCOPES,
        suggestions: featureAssistantSuggestions,
        context: assistantContextFromHash(location.hash),
        activityHref,
        announce,
        title: "Ask about Property data",
        description: "Ask a general question or inspect a page-linked property, update or dataset. This assistant is separate from the fixed Data review workflow and each message creates one durable activity run.",
      });
      return active;
    },
    destroy() { active?.destroy(); active = null; },
  };
}
