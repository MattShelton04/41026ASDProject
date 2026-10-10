import { ACTIVE_WORKFLOW_STATES } from "./definitions.js";

/**
 * Delay before the next `GET {root}/{run_id}`, or null when the run no longer needs polling.
 * Only agent-owned states poll: `awaiting_human` waits for a person, terminal states never change.
 */
export function nextWorkflowPollDelay(state, failures = 0, hidden = false) {
  const normalized = String(state || "").toLowerCase();
  if (!ACTIVE_WORKFLOW_STATES.has(normalized)) return null;
  const base = normalized === "working" ? 1500 : 1000;
  const backedOff = Math.min(15000, base * (2 ** Math.min(Math.max(0, failures), 4)));
  return hidden ? Math.max(5000, backedOff * 4) : backedOff;
}
