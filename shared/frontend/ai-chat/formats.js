const PREFERRED_RESULT_KEYS = Object.freeze([
  ["summary", "Answer"],
  ["findings", "Key findings"],
  ["recommended_next_step", "Useful next step"],
  ["safety_note", "What did not change"],
  ["evidence", "Sources used"],
]);

export function humaniseAssistantValue(value) {
  const text = String(value ?? "").replaceAll("_", " ").replaceAll("-", " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Unknown";
}

export function formatAssistantDate(value) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function shortRunId(value) {
  const text = String(value || "");
  return text ? `${text.slice(0, 8)}…` : "Pending";
}

function stringValues(value) {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return [String(value)];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => stringValues(item)).slice(0, 20);
  }
  return [];
}

export function answerSections(result) {
  if (!result || typeof result !== "object") return [];
  const sections = [];
  const consumed = new Set();
  for (const [key, label] of PREFERRED_RESULT_KEYS) {
    const values = stringValues(result[key]);
    if (values.length) sections.push({ key, label, values });
    consumed.add(key);
  }
  for (const [key, value] of Object.entries(result)) {
    if (consumed.has(key)) continue;
    const values = stringValues(value);
    if (values.length) sections.push({ key, label: humaniseAssistantValue(key), values });
  }
  return sections.slice(0, 8);
}

/**
 * Project completed visible answers into bounded conversational context.
 * The backend validates the same envelope; this browser bound keeps accidental
 * transcript growth out of each new durable run request.
 */
export function completedTurnHistory(turns = [], { maxMessages = 8 } = {}) {
  const messages = [];
  for (const turn of turns) {
    if (String(turn?.run?.status || "").toLowerCase() !== "succeeded") continue;
    const sections = answerSections(turn.run?.final_result);
    if (!sections.length) continue;
    const user = String(turn.message || "").trim().slice(0, 2_000);
    const assistant = sections
      .map((section) => `${section.label}: ${section.values.join("; ")}`)
      .join("\n")
      .trim()
      .slice(0, 2_000);
    if (!user || !assistant) continue;
    messages.push({ role: "user", content: user }, { role: "assistant", content: assistant });
  }
  const bounded = Math.max(0, Math.min(8, Number(maxMessages) || 0));
  const evenBound = bounded - (bounded % 2);
  if (!evenBound) return [];
  const selected = messages.slice(-evenBound);
  const perMessageLimit = Math.min(2_000, Math.floor(8_000 / selected.length));
  return selected.map((message) => ({ ...message, content: message.content.slice(0, perMessageLimit) }));
}

export function evidenceSteps(detail, events = []) {
  const steps = Array.isArray(detail?.steps) && detail.steps.length ? detail.steps : events;
  return steps.map((step) => {
    const call = step.input?.tool_call;
    const result = step.output?.tool_result || step.input?.tool_result;
    const plan = step.output?.plan;
    const adaptation = step.output?.adaptation;
    if (call?.tool_name) {
      return {
        phase: "Source check",
        label: humaniseAssistantValue(call.tool_name),
        summary: result?.outcome === "succeeded"
          ? "Recorded an allowlisted source result."
          : result?.error?.message || step.error?.message || (["failed", "cancelled"].includes(result?.outcome || step.status) ? "The source check did not complete." : "Waiting for the recorded source result."),
        status: result?.outcome || step.status,
        references: Array.isArray(result?.evidence_references) ? result.evidence_references : [],
      };
    }
    if (plan) {
      return {
        phase: "Plan",
        label: plan.goal || "Evidence plan",
        summary: `${plan.actions?.length || 0} bounded source check${plan.actions?.length === 1 ? "" : "s"}`,
        status: step.status,
        references: [],
      };
    }
    if (adaptation) {
      return {
        phase: "Decision",
        label: humaniseAssistantValue(adaptation.decision),
        summary: adaptation.justification || "The assistant recorded its next decision.",
        status: step.status,
        references: [],
      };
    }
    return {
      phase: humaniseAssistantValue(step.phase || step.event_type || "Activity"),
      label: humaniseAssistantValue(step.status || "Recorded"),
      summary: step.summary || step.message || "A durable activity event was recorded.",
      status: step.status,
      references: [],
    };
  }).slice(-24);
}

export function normalizeTurnDetail(payload) {
  if (!payload || typeof payload !== "object") return {};
  if (payload.run && typeof payload.run === "object") {
    return { ...payload.run, steps: payload.steps || payload.run.steps || [], reviews: payload.reviews || [] };
  }
  if (payload.agent_run && typeof payload.agent_run === "object") return payload.agent_run;
  return payload;
}
