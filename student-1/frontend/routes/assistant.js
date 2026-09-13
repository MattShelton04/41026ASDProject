import { createAiChat } from "../ai-chat/index.js";
import { assistantContextFromHash, assistantDraftFromHash, propertyAssistantOptions } from "../integration/assistant.js";

export function createFeatureAssistantRoute({ view, announce = () => {} }) {
  let active = null;
  return {
    render() {
      active?.destroy();
      active = createAiChat({
        ...propertyAssistantOptions({ announce, context: assistantContextFromHash(location.hash) }),
        root: view,
        draftKey: "propertyscope:property-data-assistant",
        initialMessage: assistantDraftFromHash(location.hash),
        title: "What would you like to check?",
        description: "Search property records, compare published sources, or ask about a data update.",
      });
      return active;
    },
    destroy() { active?.destroy(); active = null; },
  };
}
