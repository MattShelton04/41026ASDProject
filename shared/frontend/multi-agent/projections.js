/** Pure projections from contract-shaped workflow payloads to view models. No DOM, no I/O. */
import {
  ACCEPTED_STEP_LIMIT, ACTOR_LIMIT, CANCEL_ACTION, DECISION_ACTIONS, DECISION_NOTE_LIMIT,
  DEFAULT_MULTI_AGENT_LABELS, MAX_WORKFLOW_ROUNDS, SEVERITY_ORDER, STAGE_ORDER, humaniseValue,
  isTerminalWorkflow,
} from "./definitions.js";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UUID_PATTERN = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";
const DATE = /^\d{4}-\d{2}-\d{2}$/;
const DATE_TIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/;
// Mirrors the contract's actor pattern, which forbids ASCII control characters.
const CONTROL_CHARACTERS = /[\u0000-\u001f\u007f]/;
const DEFAULT_STRING_LIMIT = 1000;
const LONG_TEXT_THRESHOLD = 200;

function durationBetween(start, end) {
  const from = Date.parse(start || "");
  const to = Date.parse(end || "");
  return Number.isFinite(from) && Number.isFinite(to) && to >= from ? to - from : null;
}

export function formatDuration(milliseconds) {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return "";
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  const seconds = milliseconds / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ${Math.round(seconds % 60)} s`;
  return `${Math.floor(seconds / 3600)} h ${Math.floor((seconds % 3600) / 60)} min`;
}

export function formatTimestamp(value) {
  const parsed = Date.parse(value || "");
  if (!Number.isFinite(parsed)) return "";
  return new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeStyle: "medium" }).format(new Date(parsed));
}

/**
 * Recorded stages in order, followed by the stages the current round has yet to reach.
 * A `human` stage that is still running is presented as "waiting" for a person.
 */
export function stageTimeline(run, labels = DEFAULT_MULTI_AGENT_LABELS) {
  const recorded = Array.isArray(run?.stages) ? run.stages : [];
  const items = recorded.map((stage, index) => {
    const status = stage.stage === "human" && stage.status === "running" ? "waiting" : stage.status || "pending";
    return {
      key: `${stage.round || 1}-${stage.stage}-${index}`,
      stage: stage.stage,
      round: Number(stage.round) || 1,
      status,
      label: labels.stages?.[stage.stage] || humaniseValue(stage.stage),
      statusLabel: labels.stageStatuses?.[status] || humaniseValue(status),
      startedAt: stage.started_at || null,
      completedAt: stage.completed_at || null,
      durationMs: durationBetween(stage.started_at, stage.completed_at),
      detail: stage.detail ? humaniseValue(stage.detail) : "",
    };
  });
  if (!run || isTerminalWorkflow(run.state)) return items;
  const round = Number(run.round) || 1;
  const sequence = round === 1 ? STAGE_ORDER : STAGE_ORDER.filter((stage) => stage !== "planner");
  const reached = new Set(items.filter((item) => item.round === round).map((item) => item.stage));
  for (const stage of sequence) {
    if (reached.has(stage)) continue;
    items.push({
      key: `${round}-${stage}-pending`, stage, round, status: "pending",
      label: labels.stages?.[stage] || humaniseValue(stage),
      statusLabel: labels.stageStatuses?.pending || "Not started",
      startedAt: null, completedAt: null, durationMs: null, detail: "",
    });
  }
  return items;
}

/** Only actions the server lists are offered; unknown action strings are ignored. */
export function availableDecisions(run, labels = DEFAULT_MULTI_AGENT_LABELS) {
  const actions = new Set(Array.isArray(run?.available_actions) ? run.available_actions : []);
  const finalRound = (Number(run?.round) || 1) >= MAX_WORKFLOW_ROUNDS;
  return DECISION_ACTIONS.filter((action) => actions.has(action)).map((action) => {
    const definition = action === "correct" && finalRound
      ? labels.finalCorrection
      : labels.decisionOptions?.[action];
    return {
      action,
      label: definition?.label || humaniseValue(action),
      detail: definition?.detail || "",
      submit: definition?.submit || labels.submitDecision || "Record decision",
      note: definition?.note || labels.note || "Note",
      placeholder: definition?.placeholder || "",
      optionalNote: action === "approve",
      suggested: action === run?.review?.recommendation,
    };
  });
}

export function canCancel(run) {
  return Array.isArray(run?.available_actions) && run.available_actions.includes(CANCEL_ACTION);
}

export function planStepIds(run) {
  return (Array.isArray(run?.plan?.steps) ? run.plan.steps : []).map((step) => step.id).filter(Boolean);
}

/** Mirrors `HumanDecisionRequest` and the server's decision rules before anything is sent. */
export function validateDecision(draft = {}, run = null) {
  const errors = {};
  const decision = String(draft.decision || "");
  const offered = availableDecisions(run).map((option) => option.action);
  const note = String(draft.note ?? "").trim();
  const actor = String(draft.actor ?? "").trim();
  const known = new Set(planStepIds(run));
  const accepted = [...new Set((draft.acceptedStepIds || []).map(String))];
  if (!offered.includes(decision)) errors.decision = offered.length ? "Choose one of the available decisions." : "This run is not waiting for a decision.";
  if (decision && decision !== "approve" && !note) errors.note = "Add a note explaining this decision.";
  else if (note.length > DECISION_NOTE_LIMIT) errors.note = `Keep the note within ${DECISION_NOTE_LIMIT} characters.`;
  if (!actor) errors.actor = "Enter the name to record with this decision.";
  else if (actor.length > ACTOR_LIMIT) errors.actor = `Keep the name within ${ACTOR_LIMIT} characters.`;
  else if (CONTROL_CHARACTERS.test(actor)) errors.actor = "The name cannot contain control characters.";
  if (decision === "partial") {
    if (!accepted.length) errors.accepted_step_ids = "Select at least one step to accept.";
    else if (accepted.length > ACCEPTED_STEP_LIMIT) errors.accepted_step_ids = `Select at most ${ACCEPTED_STEP_LIMIT} steps.`;
    else if (accepted.some((id) => !known.has(id))) errors.accepted_step_ids = "Select only steps from this run's plan.";
  }
  const valid = Object.keys(errors).length === 0;
  const body = { decision, note, actor };
  if (decision === "partial") body.accepted_step_ids = accepted;
  return { valid, errors, body: valid ? body : null };
}

function inputControl(field) {
  if (field.type === "boolean") return "checkbox";
  if (Array.isArray(field.enum) && field.enum.length) return "select";
  if (field.type === "integer" || field.type === "number") return "number";
  if (field.format === "date") return "date";
  if (field.format === "uri") return "url";
  return (field.maxLength || DEFAULT_STRING_LIMIT) > LONG_TEXT_THRESHOLD && !field.format ? "textarea" : "text";
}

/** Template inputs → form field definitions; hidden inputs are submitted but never shown. */
export function startFields(descriptor, { hiddenInputs = [], initialInput = {} } = {}) {
  const template = descriptor?.template || descriptor || {};
  const hidden = new Set(hiddenInputs);
  const inputs = Array.isArray(template.inputs) ? template.inputs : [];
  return inputs.filter((input) => input && typeof input.name === "string").map((input) => {
    const field = {
      name: input.name,
      title: input.title || humaniseValue(input.name),
      description: input.description || "",
      type: ["string", "integer", "number", "boolean"].includes(input.type) ? input.type : "string",
      required: input.required !== false,
      format: input.format || null,
      enum: Array.isArray(input.enum) ? input.enum.map(String) : null,
      maxLength: Number.isInteger(input.max_length) ? input.max_length : null,
      minLength: Number.isInteger(input.min_length) ? input.min_length : null,
      minimum: Number.isFinite(input.minimum) ? input.minimum : null,
      maximum: Number.isFinite(input.maximum) ? input.maximum : null,
      pattern: input.pattern || (input.format === "uuid" ? UUID_PATTERN : null),
      hidden: hidden.has(input.name),
    };
    const initial = initialInput?.[input.name];
    field.control = inputControl(field);
    field.initialValue = initial === undefined || initial === null ? (field.type === "boolean" ? false : "") : initial;
    return field;
  });
}

function validateString(field, text) {
  const limit = field.maxLength || DEFAULT_STRING_LIMIT;
  if (text.length > limit) return `Use ${limit} characters or fewer.`;
  if (field.minLength && text.length < field.minLength) return `Use at least ${field.minLength} characters.`;
  if (field.enum && !field.enum.includes(text)) return "Choose one of the listed values.";
  if (field.format === "uuid" && !UUID.test(text)) return "Enter a UUID such as 8c0d7e0e-4a3b-4c55-9a62-0d7c5f0f9a11.";
  if (field.format === "date" && !(DATE.test(text) && Number.isFinite(Date.parse(text)))) return "Enter a date as YYYY-MM-DD.";
  if (field.format === "date-time" && !(DATE_TIME.test(text) && Number.isFinite(Date.parse(text)))) return "Enter a date and time with a time zone, such as 2026-10-01T09:00:00Z.";
  if (field.format === "uri") {
    try { new URL(text); } catch { return "Enter a complete URL."; }
  }
  if (field.pattern && field.format !== "uuid") {
    try { if (!new RegExp(`^(?:${field.pattern})$`).test(text)) return "Use the expected format."; } catch { /* the server re-validates */ }
  }
  return "";
}

/** Coerce raw control values to the template's JSON types; omit empty optional values. */
export function validateStartInput(fields, values = {}) {
  const errors = {};
  const input = {};
  for (const field of fields) {
    const raw = values[field.name];
    if (field.type === "boolean") { input[field.name] = raw === true || raw === "true"; continue; }
    const text = String(raw ?? "").trim();
    if (!text) {
      if (field.required) errors[field.name] = `${field.title} is required.`;
      continue;
    }
    if (field.type === "integer" || field.type === "number") {
      const number = Number(text);
      if (!Number.isFinite(number) || (field.type === "integer" && !Number.isInteger(number))) {
        errors[field.name] = field.type === "integer" ? "Enter a whole number." : "Enter a number.";
      } else if (field.minimum !== null && number < field.minimum) errors[field.name] = `Enter ${field.minimum} or more.`;
      else if (field.maximum !== null && number > field.maximum) errors[field.name] = `Enter ${field.maximum} or less.`;
      else input[field.name] = number;
      continue;
    }
    const message = validateString(field, text);
    if (message) errors[field.name] = message;
    else input[field.name] = text;
  }
  return { valid: Object.keys(errors).length === 0, errors, input };
}

function severityRank(severity) {
  const index = SEVERITY_ORDER.indexOf(severity);
  return index === -1 ? SEVERITY_ORDER.length : index;
}

/** Failed findings first, most severe first; passes and unevaluated checks follow. */
export function groupFindings(findings = []) {
  const list = Array.isArray(findings) ? findings : [];
  const bySeverity = (left, right) => severityRank(left.severity) - severityRank(right.severity);
  const failed = list.filter((finding) => finding.outcome === "fail").sort(bySeverity);
  const notEvaluated = list.filter((finding) => finding.outcome === "not_evaluated").sort(bySeverity);
  const passed = list.filter((finding) => finding.outcome === "pass");
  const failedBySeverity = {};
  for (const finding of failed) failedBySeverity[finding.severity] = (failedBySeverity[finding.severity] || 0) + 1;
  return { failed, notEvaluated, passed, failedBySeverity, total: list.length };
}

/** Join plan steps, Worker step results and evidence records by their recorded IDs. */
export function workerStepViews(plan, workerOutput) {
  const steps = Array.isArray(plan?.steps) ? plan.steps : [];
  const results = new Map((workerOutput?.steps || []).map((result) => [result.step_id, result]));
  const evidence = new Map((workerOutput?.evidence || []).map((record) => [record.id, record]));
  const views = steps.map((step) => {
    const result = results.get(step.id) || null;
    const linked = (result?.evidence_ids || []).map((id) => evidence.get(id)).filter(Boolean);
    const unlinked = (workerOutput?.evidence || []).filter((record) => record.step_id === step.id && !linked.includes(record));
    return { step, result, status: result?.status || "pending", findings: result?.findings || [], evidence: [...linked, ...unlinked] };
  });
  // Worker results for steps a plan no longer lists are still shown rather than dropped.
  for (const [stepId, result] of results) {
    if (steps.some((step) => step.id === stepId)) continue;
    views.push({
      step: { id: stepId, title: humaniseValue(stepId) }, result, status: result.status,
      findings: result.findings || [],
      evidence: (result.evidence_ids || []).map((id) => evidence.get(id)).filter(Boolean),
    });
  }
  return views;
}

/** A bounded, pretty-printed excerpt. The server already bounds it; the panel bounds rendering. */
export function evidenceExcerpt(record, limit = 4000) {
  const value = record?.excerpt;
  if (value === undefined || value === null || (typeof value === "object" && !Object.keys(value).length)) {
    return { text: "", truncated: Boolean(record?.excerpt_truncated) };
  }
  let text;
  try { text = typeof value === "string" ? value : JSON.stringify(value, null, 2); } catch { text = String(value); }
  const clipped = text.length > limit;
  return { text: clipped ? `${text.slice(0, limit)}\n…` : text, truncated: clipped || Boolean(record?.excerpt_truncated) };
}

export function provenanceLabel(producedBy) {
  if (!producedBy) return "";
  const parts = [`${producedBy.provider || "unknown"} · ${producedBy.model || "unknown model"}`];
  if (producedBy.prompt_id) parts.push(`prompt ${producedBy.prompt_id}${producedBy.prompt_version ? ` ${producedBy.prompt_version}` : ""}`);
  if (Number(producedBy.invocations) > 1) parts.push(`${producedBy.invocations} invocations`);
  if (producedBy.fallback) parts.push("deterministic fallback");
  return parts.join(" · ");
}

/** Problem Details (or a transport error) → a stable view model. */
export function problemView(error) {
  const problem = error?.problem && typeof error.problem === "object" ? error.problem : null;
  const errors = Array.isArray(problem?.errors) ? problem.errors.filter((item) => item && item.message) : [];
  return {
    title: problem?.title || (error?.status === 503 ? "The multi-agent service is unavailable" : "The request could not be completed"),
    detail: problem?.detail || (problem ? "" : String(error?.message || "")),
    code: problem?.code || error?.code || "",
    status: Number(problem?.status || error?.status) || 0,
    requestId: problem?.request_id || error?.requestId || "",
    errors: errors.map((item) => ({ field: String(item.field || ""), message: String(item.message), code: String(item.code || "") })),
  };
}

/** Attach server field issues (`input.release_id`, `body.note`, …) to known control names. */
export function fieldProblems(problem, names) {
  const known = new Set(names);
  const result = {};
  for (const issue of problem?.errors || []) {
    const parts = String(issue.field || "").split(/[.[\]/]+/).filter(Boolean);
    const match = [...parts].reverse().find((part) => known.has(part));
    if (match && !result[match]) result[match] = issue.message;
  }
  return result;
}

export function historyView(body) {
  const transitions = (Array.isArray(body?.history) ? body.history : []).map((entry) => ({
    key: String(entry.sequence ?? `${entry.at}-${entry.to_state}`),
    from: entry.from_state || null,
    to: entry.to_state,
    actor: entry.actor || "",
    role: entry.role || "",
    reason: entry.reason || "",
    at: entry.at || "",
    round: Number(entry.round) || 1,
  }));
  const audit = (Array.isArray(body?.audit) ? body.audit : []).map((entry) => ({
    key: String(entry.sequence ?? `${entry.at}-${entry.event}`),
    event: entry.event || "",
    role: entry.role || "",
    actor: entry.actor || "",
    at: entry.at || "",
    round: Number(entry.round) || 1,
    detail: entry.detail && typeof entry.detail === "object" ? entry.detail : {},
  }));
  const counts = {};
  for (const entry of audit) counts[entry.event] = (counts[entry.event] || 0) + 1;
  return { transitions, audit, eventCounts: counts };
}

/** Polls that change nothing visible keep the rendered DOM (and any open disclosures). */
export function runPresentationKey(run) {
  if (!run) return "";
  const { updated_at: _updated, ...visible } = run;
  return JSON.stringify(visible);
}
