export const ACTIVE_RUN_STATES = new Set([
  "requested", "queued", "planning", "discovering", "acquiring", "staging",
  "normalising", "validating", "building_release", "running", "cancelling", "resuming",
]);
export const TERMINAL_RUN_STATES = new Set(["succeeded", "failed", "cancelled"]);
export const INTERRUPTED_DETAIL_RECONCILIATION_LIMIT = 12;
export const ACTIVE_AGENT_STATES = new Set([
  "queued", "planning", "ready", "acting", "observing", "adapting", "review_required",
]);

export function createGenerationGuard() {
  let generation = 0;
  let controller = new AbortController();
  const capture = () => {
    const candidate = generation;
    return Object.freeze({
      generation: candidate,
      signal: controller.signal,
      isCurrent: () => candidate === generation,
    });
  };
  const advance = () => {
    controller.abort();
    controller = new AbortController();
    generation += 1;
    return generation;
  };
  return {
    next: advance,
    begin() { advance(); return capture(); },
    capture,
    current() { return generation; },
    signal() { return controller.signal; },
    isCurrent(candidate) { return candidate === generation; },
  };
}

export function createLatestRequestGuard() {
  let sequence = 0;
  let controller = null;
  const begin = () => {
    controller?.abort();
    controller = new AbortController();
    const candidate = ++sequence;
    const requestController = controller;
    return Object.freeze({
      sequence: candidate,
      signal: requestController.signal,
      isCurrent: () => candidate === sequence,
      finish: () => {
        if (controller === requestController) controller = null;
      },
    });
  };
  return {
    next() { return begin().sequence; },
    begin,
    cancel() {
      sequence += 1;
      controller?.abort();
      controller = null;
    },
    isCurrent(candidate) { return candidate === sequence; },
  };
}

export function retainRecent(cache, key, value, limit = 4) {
  cache.delete(key);
  cache.set(key, value);
  while (cache.size > limit) cache.delete(cache.keys().next().value);
  return value;
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

export function nextRunDetailPollDelay(
  status,
  failures = 0,
  hidden = false,
  interruptedAttempts = 0,
) {
  const state = String(status || "").toLowerCase();
  const activeDelay = nextPollDelay(state, failures, hidden);
  if (activeDelay !== null) return activeDelay;
  if (state !== "interrupted" || interruptedAttempts >= INTERRUPTED_DETAIL_RECONCILIATION_LIMIT) {
    return null;
  }
  const backedOff = Math.min(60000, 15000 * (2 ** Math.min(failures, 2)));
  return hidden ? Math.max(60000, backedOff) : backedOff;
}

export function nextAgentPollDelay(status, failures = 0, hidden = false) {
  const state = String(status || "").toLowerCase();
  if (!ACTIVE_AGENT_STATES.has(state)) return null;
  const base = state === "queued" ? 1500 : state === "review_required" ? 5000 : 800;
  const backedOff = Math.min(15000, base * (2 ** Math.min(failures, 4)));
  return hidden ? Math.max(5000, backedOff * 4) : backedOff;
}
