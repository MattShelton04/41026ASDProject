export const ACTIVE_RUN_STATES = new Set([
  "requested", "queued", "planning", "discovering", "acquiring", "staging",
  "normalising", "validating", "building_release", "running", "cancelling", "resuming",
]);
export const TERMINAL_RUN_STATES = new Set(["succeeded", "failed", "cancelled"]);

export function createGenerationGuard() {
  let generation = 0;
  return {
    next() { generation += 1; return generation; },
    current() { return generation; },
    isCurrent(candidate) { return candidate === generation; },
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
