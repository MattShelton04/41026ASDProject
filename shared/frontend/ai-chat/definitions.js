export const DEFAULT_ASSISTANT_SCOPES = Object.freeze([
  { id: "application", label: "Application", description: "Application guidance and currently available capabilities." },
]);

export const TERMINAL_ASSISTANT_STATES = new Set(["succeeded", "failed", "cancelled"]);
export const ACTIVE_ASSISTANT_STATES = new Set([
  "queued", "planning", "ready", "acting", "observing", "adapting", "review_required",
]);

const STATUS_DEFINITIONS = Object.freeze({
  queued: { label: "Queued", detail: "Waiting for the assistant worker.", tone: "info" },
  planning: { label: "Planning", detail: "Choosing the smallest useful evidence path.", tone: "info" },
  ready: { label: "Plan ready", detail: "The next source check is ready.", tone: "info" },
  acting: { label: "Checking a source", detail: "Calling an allowlisted PropertyScope tool.", tone: "info" },
  observing: { label: "Recording evidence", detail: "Saving the source result before deciding what follows.", tone: "info" },
  adapting: { label: "Preparing answer", detail: "Comparing the evidence with the question.", tone: "info" },
  review_required: { label: "Needs human review", detail: "A protected proposal is paused; no action has run.", tone: "partial" },
  succeeded: { label: "Complete", detail: "The answer and its activity record are available.", tone: "confirmed" },
  failed: { label: "Could not complete", detail: "The recorded activity shows where the turn stopped.", tone: "danger" },
  cancelled: { label: "Cancelled", detail: "The turn stopped without changing source data.", tone: "unknown" },
});

export function assistantStatus(status) {
  const normalized = String(status || "queued").toLowerCase();
  return STATUS_DEFINITIONS[normalized] || {
    label: "Working",
    detail: "The latest durable state is being checked.",
    tone: "unknown",
  };
}

export function normalizeAssistantScopes(scopes = DEFAULT_ASSISTANT_SCOPES) {
  const valid = scopes.filter((item) => item
    && typeof item.id === "string" && item.id
    && typeof item.label === "string" && item.label
    && typeof item.description === "string" && item.description);
  return valid.length ? valid.map((item) => Object.freeze({ ...item })) : [...DEFAULT_ASSISTANT_SCOPES];
}

export function findAssistantScope(id, scopes = DEFAULT_ASSISTANT_SCOPES) {
  const normalized = normalizeAssistantScopes(scopes);
  return normalized.find((item) => item.id === id) || normalized[0];
}

export function defaultSuggestions() {
  return ["What can this assistant help with?", "Which capabilities are available now?"];
}
