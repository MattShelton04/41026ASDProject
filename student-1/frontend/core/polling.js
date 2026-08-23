export const ACTIVE_RUN_STATES = new Set([
  "requested", "queued", "planning", "discovering", "acquiring", "staging",
  "normalising", "validating", "building_release", "running", "cancelling", "resuming",
]);
export const TERMINAL_RUN_STATES = new Set(["succeeded", "failed", "cancelled"]);
export const ACTIVE_AGENT_STATES = new Set([
  "queued", "planning", "ready", "acting", "observing", "adapting", "review_required",
]);

export function createGenerationGuard() {
  let generation = 0;
  return {
    next() { generation += 1; return generation; },
    current() { return generation; },
    isCurrent(candidate) { return candidate === generation; },
  };
}

export function createLatestRequestGuard() {
  let sequence = 0;
  return {
    next() { sequence += 1; return sequence; },
    isCurrent(candidate) { return candidate === sequence; },
  };
}

export function actionAvailability(status) {
  const state = String(status || "").toLowerCase();
  return {
    cancel: ACTIVE_RUN_STATES.has(state) && state !== "cancelling",
    resume: ["interrupted", "paused"].includes(state),
    retry: ["failed", "cancelled"].includes(state),
    reprocess: ["failed", "succeeded", "cancelled"].includes(state),
    diagnose: !ACTIVE_RUN_STATES.has(state),
  };
}

export function nextPollDelay(status, failures = 0, hidden = false) {
  if (!ACTIVE_RUN_STATES.has(String(status || "").toLowerCase())) return null;
  const base = status === "queued" || status === "requested" ? 2000 : 1200;
  const backedOff = Math.min(15000, base * (2 ** Math.min(failures, 3)));
  return hidden ? Math.max(10000, backedOff * 3) : backedOff;
}

export function nextAgentPollDelay(status, failures = 0, hidden = false) {
  const state = String(status || "").toLowerCase();
  if (!ACTIVE_AGENT_STATES.has(state)) return null;
  const base = state === "queued" ? 1500 : state === "review_required" ? 5000 : 800;
  const backedOff = Math.min(15000, base * (2 ** Math.min(failures, 4)));
  return hidden ? Math.max(5000, backedOff * 4) : backedOff;
}
