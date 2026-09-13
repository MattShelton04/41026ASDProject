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
  review_required: { label: "Needs human review", detail: "A protected proposal is paused for human review. No approval is implied.", tone: "partial" },
  succeeded: { label: "Complete", detail: "The answer and its activity record are available.", tone: "confirmed" },
  failed: { label: "Could not complete", detail: "The recorded activity shows where the turn stopped.", tone: "danger" },
  cancelled: { label: "Cancelled", detail: "This turn is cancelled. Recorded activity shows any checks completed before it stopped.", tone: "unknown" },
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

export function normalizeAssistantContexts(contexts = []) {
  if (!Array.isArray(contexts)) return [];
  return contexts.flatMap((item) => {
    if (!item || typeof item.id !== "string" || !item.id
      || typeof item.label !== "string" || !item.label
      || !item.context || typeof item.context !== "object" || Array.isArray(item.context)) return [];
    const parameter = item.parameter;
    if (parameter !== undefined && (!parameter
      || typeof parameter.name !== "string" || !parameter.name
      || typeof parameter.label !== "string" || !parameter.label)) return [];
    return [Object.freeze({
      id: item.id,
      label: item.label,
      description: typeof item.description === "string" ? item.description : "",
      context: Object.freeze({ ...item.context }),
      parameter: parameter ? Object.freeze({
        name: parameter.name,
        label: parameter.label,
        placeholder: typeof parameter.placeholder === "string" ? parameter.placeholder : "",
        pattern: typeof parameter.pattern === "string" ? parameter.pattern : "",
        help: typeof parameter.help === "string" ? parameter.help : "",
        searchParameter: typeof parameter.searchParameter === "string" ? parameter.searchParameter : "",
      }) : null,
    })];
  });
}

/** Feature-owned search text stays distinct from exact entity identity. */
export function assistantContextFromInput(definition, rawValue) {
  const value = String(rawValue || "").trim();
  const parameter = definition.parameter;
  if (!value || !parameter) return { ...definition.context };
  const exact = !parameter.searchParameter || !parameter.pattern || new RegExp(`^(?:${parameter.pattern})$`).test(value);
  return { ...definition.context, [exact ? parameter.name : parameter.searchParameter]: value };
}
