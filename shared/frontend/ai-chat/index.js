/** Public domain-neutral AI chat package for Shared and feature frontends. */

export { createAssistantClient, assistantRequest, AssistantApiError } from "./client.js";
export { createAiChat } from "./controller.js";
export {
  ACTIVE_ASSISTANT_STATES,
  DEFAULT_ASSISTANT_SCOPES,
  TERMINAL_ASSISTANT_STATES,
  assistantStatus,
  defaultSuggestions,
  findAssistantScope,
  normalizeAssistantScopes,
} from "./definitions.js";
export {
  answerSections,
  evidenceSteps,
  formatAssistantDate,
  humaniseAssistantValue,
  normalizeTurnDetail,
  shortRunId,
} from "./formats.js";
export { mergeAssistantEvents, nextAssistantPollDelay, restoreEventCursor } from "./polling.js";
