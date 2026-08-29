/** Public domain-neutral AI chat package for Shared and feature frontends. */

export { createAssistantClient, assistantRequest, AssistantApiError } from "./client.js?v=3";
export { createAiChat } from "./controller.js?v=3";
export { createFeatureAssistant, featureActivityHref } from "./feature-route.js?v=3";
export {
  ACTIVE_ASSISTANT_STATES,
  DEFAULT_ASSISTANT_SCOPES,
  TERMINAL_ASSISTANT_STATES,
  assistantStatus,
  defaultSuggestions,
  findAssistantScope,
  normalizeAssistantContexts,
  normalizeAssistantScopes,
} from "./definitions.js?v=3";
export {
  answerSections,
  completedTurnHistory,
  evidenceSteps,
  formatAssistantDate,
  humaniseAssistantValue,
  normalizeTurnDetail,
  shortRunId,
} from "./formats.js?v=3";
export { mergeAssistantEvents, nextAssistantPollDelay, restoreEventCursor } from "./polling.js?v=3";
