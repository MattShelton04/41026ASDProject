import { ACTIVE_ASSISTANT_STATES, TERMINAL_ASSISTANT_STATES } from "./definitions.js";

export function restoreEventCursor(value) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0;
}

export function mergeAssistantEvents(existing, incoming, limit = 200) {
  const keyed = new Map(existing.map((event) => [event.id, event]));
  for (const event of incoming) keyed.set(event.id, event);
  const items = [...keyed.values()].sort((left, right) => Number(left.id) - Number(right.id)).slice(-limit);
  return { items, cursor: items.length ? restoreEventCursor(items.at(-1).id) : 0 };
}

export function nextAssistantPollDelay(status, failures = 0, hidden = false) {
  const normalized = String(status || "queued").toLowerCase();
  if (TERMINAL_ASSISTANT_STATES.has(normalized)) return null;
  if (!ACTIVE_ASSISTANT_STATES.has(normalized)) return 2000;
  const base = normalized === "queued" ? 1500 : normalized === "review_required" ? 5000 : 850;
  const backedOff = Math.min(15000, base * (2 ** Math.min(failures, 4)));
  return hidden ? Math.max(5000, backedOff * 4) : backedOff;
}
