/** Workflow vocabulary mirrored from `shared_contracts.multi_agent`; features may relabel it. */

export const ACTIVE_WORKFLOW_STATES = new Set(["planning", "working", "reviewing"]);
export const TERMINAL_WORKFLOW_STATES = new Set([
  "approved", "partially_accepted", "rejected", "corrected", "failed", "cancelled",
]);
// The Multi-Agent Server's `available_actions` vocabulary (state_machine.py).
export const DECISION_ACTIONS = Object.freeze(["approve", "correct", "partial", "reject"]);
export const CANCEL_ACTION = "cancel";
export const STAGE_ORDER = Object.freeze(["planner", "worker", "reviewer", "human"]);
export const SEVERITY_ORDER = Object.freeze(["critical", "high", "medium", "low", "info"]);
export const MAX_WORKFLOW_ROUNDS = 2;
export const DECISION_NOTE_LIMIT = 2000;
export const ACTOR_LIMIT = 100;
export const ACCEPTED_STEP_LIMIT = 10;

const WORKFLOW_STATES = {
  planning: { label: "Planning", detail: "The Planner is choosing the read-only steps for this review.", tone: "info" },
  working: { label: "Gathering evidence", detail: "The Worker is calling the template's read-only tools.", tone: "info" },
  reviewing: { label: "Reviewing", detail: "The Reviewer is checking the evidence against the template's checks.", tone: "info" },
  awaiting_human: { label: "Awaiting your decision", detail: "The agents have finished. Only a person can decide the outcome.", tone: "partial" },
  approved: { label: "Approved", detail: "A person approved the recommendation.", tone: "confirmed" },
  partially_accepted: { label: "Partially accepted", detail: "A person accepted some of the plan steps.", tone: "partial" },
  rejected: { label: "Rejected", detail: "A person rejected the recommendation.", tone: "danger" },
  corrected: { label: "Corrected", detail: "A person recorded a final correction after the second round.", tone: "partial" },
  failed: { label: "Failed", detail: "The workflow stopped before a human decision.", tone: "danger" },
  cancelled: { label: "Cancelled", detail: "The workflow was cancelled.", tone: "planned" },
};

const DECISIONS = {
  approve: { label: "Approve", detail: "Accept the recommendation. A note is optional." },
  correct: { label: "Request a correction", detail: "Send the Worker and Reviewer back once with your note." },
  partial: { label: "Accept part", detail: "Accept only the plan steps you select." },
  reject: { label: "Reject", detail: "Record that the evidence does not support the outcome." },
};

// Round 2 is the correction budget's end: `correct` then closes the run as `corrected`.
const FINAL_CORRECTION = {
  label: "Record a final correction",
  detail: "Ends the run as corrected, with your note as the final correction.",
};

const STAGES = {
  planner: "Planner",
  worker: "Worker",
  reviewer: "Reviewer",
  human: "Human decision",
};

const STAGE_STATUSES = {
  pending: "Not started",
  running: "In progress",
  waiting: "Waiting for a person",
  completed: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

/** Default vocabulary. Every key may be overridden through the panel's `labels` option. */
export const DEFAULT_MULTI_AGENT_LABELS = Object.freeze({
  eyebrow: "Multi-agent review",
  title: "",
  startHeading: "Start a review",
  start: "Start review",
  starting: "Starting review…",
  startAgain: "Start another review",
  loadingTemplate: "Loading the workflow…",
  runHeading: "Review run",
  plan: "Plan",
  worker: "Worker evidence",
  review: "Reviewer recommendation",
  decisions: "Recorded decisions",
  decisionHeading: "Your decision",
  guidance: "Guidance",
  note: "Note",
  noteHelp: "Required unless you approve. Explain what you checked.",
  actor: "Your name",
  actorHelp: "Recorded with the decision.",
  acceptedSteps: "Steps to accept",
  submitDecision: "Record decision",
  submittingDecision: "Recording decision…",
  cancel: "Cancel run",
  cancelling: "Cancelling…",
  history: "View history",
  historyLink: "Open full history",
  pollWarning: "Progress updates are temporarily unavailable. The last recorded state is shown; this view will retry automatically.",
  unavailableTool: "Some tools are unavailable, so the Worker may not be able to gather every step.",
  states: WORKFLOW_STATES,
  decisionOptions: DECISIONS,
  finalCorrection: FINAL_CORRECTION,
  stages: STAGES,
  stageStatuses: STAGE_STATUSES,
});

/** Merge feature overrides one level deep so a feature can relabel a single state. */
export function mergeLabels(overrides = {}) {
  const merged = { ...DEFAULT_MULTI_AGENT_LABELS };
  for (const [key, value] of Object.entries(overrides || {})) {
    if (value === undefined || value === null) continue;
    const base = DEFAULT_MULTI_AGENT_LABELS[key];
    merged[key] = base && typeof base === "object" && typeof value === "object" ? mergeNested(base, value) : value;
  }
  return Object.freeze(merged);
}

function mergeNested(base, value) {
  const result = { ...base };
  for (const [key, item] of Object.entries(value)) {
    result[key] = base[key] && typeof base[key] === "object" && typeof item === "object" ? { ...base[key], ...item } : item;
  }
  return result;
}

export function workflowStatus(state, labels = DEFAULT_MULTI_AGENT_LABELS) {
  const key = String(state || "planning").toLowerCase();
  return { key, ...(labels.states?.[key] || { label: humaniseValue(key), detail: "", tone: "info" }) };
}

export function isActiveWorkflow(state) { return ACTIVE_WORKFLOW_STATES.has(String(state || "")); }
export function isTerminalWorkflow(state) { return TERMINAL_WORKFLOW_STATES.has(String(state || "")); }

export function humaniseValue(value) {
  const text = String(value ?? "").replaceAll(/[_-]+/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

export function shortRunId(id) {
  const text = String(id || "");
  return text.length > 8 ? `${text.slice(0, 8)}…` : text;
}
