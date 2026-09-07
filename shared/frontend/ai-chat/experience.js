/** Local presentation state only. Never an evidence source, permission or conversation store. */
import { answerSections, evidenceSteps } from "./formats.js";

export function turnPresentationKey(turn) {
  return JSON.stringify({
    id: turn.id, message: turn.message, scope: turn.scopeLabel || turn.scope,
    context: turn.context, status: turn.run?.status,
    created: turn.run?.created_at,
    answer: answerSections(turn.run?.final_result),
    grounding: turn.run?.final_result,
    evidence: evidenceSteps(turn.run, turn.events),
    error: turn.error ? [turn.error.message, turn.error.requestId] : turn.run?.error?.message,
    pollWarning: Boolean(turn.pollWarning), cancelWarning: Boolean(turn.cancelWarning),
    cancelPending: Boolean(turn.cancelPending),
  });
}

export function draftContextKey(namespace, scope, context = {}) {
  if (!namespace) return "";
  const entries = Object.entries(context).filter(([, value]) => value != null && value !== "").sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify([namespace, scope, entries]);
}

/** Bounded, memory-only drafts; no localStorage, cookies, network or cross-refresh retention. */
export function createDraftStore(limit = 12) {
  const values = new Map();
  return Object.freeze({
    read(key) { return key ? values.get(key) || "" : ""; },
    write(key, message) {
      if (!key) return;
      values.delete(key);
      const value = String(message || "").slice(0, 2000);
      if (value) values.set(key, value);
      while (values.size > Math.max(1, limit)) values.delete(values.keys().next().value);
    },
    clear() { values.clear(); },
  });
}

export const assistantDrafts = createDraftStore();
