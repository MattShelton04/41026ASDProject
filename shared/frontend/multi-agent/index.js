/** Public domain-neutral Multi-Agent workflow panel for Shared and feature frontends. */

export { createMultiAgentClient, multiAgentRequest, MultiAgentApiError } from "./client.js";
export { createMultiAgentPanel } from "./panel.js";
export {
  ACTIVE_WORKFLOW_STATES,
  CANCEL_ACTION,
  DECISION_ACTIONS,
  DEFAULT_MULTI_AGENT_LABELS,
  TERMINAL_WORKFLOW_STATES,
  isActiveWorkflow,
  isTerminalWorkflow,
  mergeLabels,
  shortRunId,
  workflowStatus,
} from "./definitions.js";
export {
  availableDecisions,
  canCancel,
  evidenceExcerpt,
  fieldProblems,
  formatDuration,
  groupFindings,
  historyView,
  problemView,
  provenanceLabel,
  stageTimeline,
  startFields,
  validateDecision,
  validateStartInput,
  workerStepViews,
} from "./projections.js";
export { nextWorkflowPollDelay } from "./polling.js";
export {
  advanceReplay,
  buildTimeline,
  eventSentence,
  laneView,
  mergeHistory,
  nowView,
  relayView,
  snapshotAt,
} from "./timeline.js";
