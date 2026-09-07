import { propertyActivityUrl } from "../integration/activity.js";
import { createAiChat, createAssistantClient } from "../ai-chat/index.js";
import {
  FEATURE_ASSISTANT_SCOPES,
  FEATURE_ASSISTANT_CONTEXTS,
  assistantContextFromHash,
  assistantDraftFromHash,
  featureAssistantSuggestions,
} from "../integration/assistant.js";

function activityHref(runId) {
  return propertyActivityUrl(runId, {
    baseUrl: document.baseURI,
    activityUrl: window.PROPERTYSCOPE_AGENT_ACTIVITY_URL,
    returnTo: "/features/data-platform/#assistant",
  });
}

export function createFeatureAssistantRoute({ view, announce = () => {} }) {
  let active = null;
  return {
    render() {
      active?.destroy();
      active = createAiChat({
        root: view,
        draftKey: "propertyscope:property-data-assistant",
        client: createAssistantClient({ apiRoot: "/api/data-platform/v1/assistant" }),
        initialScope: "feature",
        scopes: FEATURE_ASSISTANT_SCOPES,
        contextOptions: FEATURE_ASSISTANT_CONTEXTS,
        suggestions: featureAssistantSuggestions,
        context: assistantContextFromHash(location.hash),
        initialMessage: assistantDraftFromHash(location.hash),
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
