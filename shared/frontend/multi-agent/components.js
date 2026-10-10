/** Stateless renderers for one workflow run. Every untrusted value is set as text, never HTML. */
import { append, el } from "../browser/index.js";
import { DEFAULT_MULTI_AGENT_LABELS, humaniseValue, workflowStatus } from "./definitions.js";
import {
  evidenceExcerpt, formatDuration, formatTimestamp, groupFindings, provenanceLabel, workerStepViews,
} from "./projections.js";
import { decisionLabel, eventSentence, formatClock } from "./timeline.js";

const TONES = { completed: "confirmed", succeeded: "confirmed", pass: "confirmed", running: "info", waiting: "partial", pending: "planned", skipped: "planned", failed: "danger", fail: "danger", timed_out: "danger", rejected: "danger", cancelled: "planned", not_evaluated: "planned" };

/** Shared render context: labels plus per-panel disclosure memory that survives re-rendering. */
export function createRenderContext(labels = DEFAULT_MULTI_AGENT_LABELS) {
  return { labels, disclosures: new Map() };
}

export function badge(text, tone = "info") {
  return el("span", `ps-badge ps-multi-agent__badge ps-multi-agent__badge--${tone}`, text);
}

export function statusBadge(state, labels = DEFAULT_MULTI_AGENT_LABELS) {
  const status = workflowStatus(state, labels);
  const node = badge(status.label, status.tone);
  node.dataset.state = status.key;
  return node;
}

function outcomeBadge(value) { return badge(humaniseValue(value), TONES[value] || "info"); }

/** A native disclosure whose open state is remembered by key across polls. */
function disclosure(context, key, className, summary) {
  const details = el("details", className);
  details.dataset.disclosure = key;
  details.open = Boolean(context?.disclosures?.get(key));
  details.addEventListener("toggle", () => context?.disclosures?.set(key, details.open));
  const label = el("summary", "");
  append(label, ...(Array.isArray(summary) ? summary : [summary]));
  append(details, label);
  return details;
}

// Inside a drawer the drawer's summary names the section, so the heading is left out.
function section(className, heading, { titled = true, level = "h4" } = {}) {
  const host = el("section", `ps-multi-agent__section ${className}`);
  if (titled) append(host, el(level, "ps-multi-agent__section-title", heading));
  return host;
}

/**
 * A closed-by-default drawer whose open state survives re-rendering. Its summary carries a
 * count, which briefly highlights when it changes while the view is live.
 */
export function drawer(context, key, title, count, { className = "", fresh = false } = {}) {
  const details = disclosure(context, key, `ps-multi-agent__drawer ${className}`.trim(), [
    el("strong", "ps-multi-agent__drawer-title", title), el("span", "ps-multi-agent__drawer-count", count),
  ]);
  if (fresh) details.classList.add("is-fresh");
  const body = el("div", "ps-multi-agent__drawer-body");
  append(details, body);
  return { details, body };
}

function json(value) {
  try { return JSON.stringify(value ?? {}, null, 2); } catch { return String(value); }
}

function facts(entries) {
  const list = el("dl", "ps-multi-agent__facts");
  for (const [term, value, code = false] of entries) {
    if (value === null || value === undefined || value === "") continue;
    const row = el("div");
    append(row, el("dt", "", term));
    const definition = el("dd");
    append(definition, code ? el("code", "", value) : document.createTextNode(String(value)));
    append(row, definition);
    append(list, row);
  }
  return list;
}

export function renderProvenance(producedBy) {
  const text = provenanceLabel(producedBy);
  if (!text) return null;
  const node = el("p", `ps-multi-agent__provenance${producedBy?.fallback ? " ps-multi-agent__provenance--fallback" : ""}`);
  append(node, el("span", "ps-multi-agent__provenance-label", "Produced by"), el("span", "", text));
  return node;
}

export function renderPlan(plan, context, { titled = true } = {}) {
  const labels = context?.labels || DEFAULT_MULTI_AGENT_LABELS;
  const host = section("ps-multi-agent__plan", labels.plan, { titled });
  if (!plan) {
    append(host, el("p", "ps-multi-agent__empty", "The Planner has not produced a plan yet."));
    return host;
  }
  if (plan.summary) append(host, el("p", "ps-multi-agent__summary", plan.summary));
  const steps = el("ol", "ps-multi-agent__plan-steps");
  for (const step of plan.steps || []) {
    const item = el("li", "ps-multi-agent__plan-step");
    item.dataset.stepId = step.id;
    append(item, el("strong", "ps-multi-agent__step-title", step.title || humaniseValue(step.id)));
    if (step.purpose) append(item, el("p", "", step.purpose));
    append(item, facts([["Step", step.id, true], ["Tool", step.tool, true], ["Expected evidence", step.expected_evidence]]));
    if (step.arguments && Object.keys(step.arguments).length) {
      const args = disclosure(context, `plan-args-${step.id}`, "ps-multi-agent__arguments", "Arguments");
      append(args, el("pre", "ps-multi-agent__code", json(step.arguments)));
      append(item, args);
    }
    append(steps, item);
  }
  append(host, steps);
  if (Array.isArray(plan.evidence_needed) && plan.evidence_needed.length) {
    const needed = disclosure(context, "plan-evidence-needed", "ps-multi-agent__arguments", "Evidence the Planner asked for");
    const list = el("ul");
    for (const entry of plan.evidence_needed) append(list, el("li", "", entry));
    append(needed, list);
    append(host, needed);
  }
  append(host, renderProvenance(plan.produced_by));
  return host;
}

export function renderEvidence(record, context, scope = "current") {
  const outcome = record.outcome || "unknown";
  const details = disclosure(context, `evidence-${scope}-${record.id}`, `ps-multi-agent__evidence ps-multi-agent__evidence--${outcome}`, [
    el("code", "", record.tool_name || "tool"), outcomeBadge(outcome),
  ]);
  details.dataset.evidenceId = record.id || "";
  append(details, facts([
    ["Evidence", record.id, true],
    ["Tool version", record.tool_version],
    ["Transport", record.transport],
    ["Duration", Number.isFinite(record.duration_ms) ? formatDuration(record.duration_ms) : ""],
    ["Result digest", record.result_digest, true],
    ["Error", record.error_code ? `${record.error_code}${record.error_message ? `: ${record.error_message}` : ""}` : ""],
  ]));
  if (record.arguments && Object.keys(record.arguments).length) {
    append(details, el("p", "ps-multi-agent__label", "Arguments"), el("pre", "ps-multi-agent__code", json(record.arguments)));
  }
  const excerpt = evidenceExcerpt(record);
  if (excerpt.text) {
    append(details, el("p", "ps-multi-agent__label", "Recorded excerpt"));
    const pre = el("pre", "ps-multi-agent__code ps-multi-agent__excerpt", excerpt.text);
    pre.tabIndex = 0;
    pre.setAttribute("aria-label", `Recorded excerpt from ${record.tool_name || "tool"}`);
    append(details, pre);
  }
  if (excerpt.truncated) append(details, el("p", "ps-multi-agent__note", "The excerpt is truncated. The result digest identifies the full tool result."));
  return details;
}

export function renderWorker(plan, workerOutput, context, scope = "current", { titled = true, toolCalls = [] } = {}) {
  const labels = context?.labels || DEFAULT_MULTI_AGENT_LABELS;
  const host = section("ps-multi-agent__worker", labels.worker, { titled });
  if (!workerOutput) {
    if (toolCalls.length) append(host, renderToolCalls(toolCalls, plan));
    else append(host, el("p", "ps-multi-agent__empty", "The Worker has not recorded evidence yet."));
    return host;
  }
  if (workerOutput.correction_note) {
    const note = el("div", "ps-multi-agent__correction-note");
    append(note, el("strong", "", "Correction applied"), el("p", "", workerOutput.correction_note));
    append(host, note);
  }
  if (workerOutput.summary) append(host, el("p", "ps-multi-agent__summary", workerOutput.summary));
  for (const view of workerStepViews(plan, workerOutput)) {
    const article = el("article", `ps-multi-agent__step ps-multi-agent__step--${view.status}`);
    article.dataset.stepId = view.step.id;
    const head = el("div", "ps-multi-agent__step-head");
    append(head, el("h5", "ps-multi-agent__step-title", view.step.title || humaniseValue(view.step.id)), outcomeBadge(view.status));
    append(article, head);
    if (view.findings.length) {
      const list = el("ul", "ps-multi-agent__step-findings");
      for (const finding of view.findings) append(list, el("li", "", finding));
      append(article, list);
    } else append(article, el("p", "ps-multi-agent__empty", "No findings were recorded for this step."));
    for (const record of view.evidence) append(article, renderEvidence(record, context, scope));
    append(host, article);
  }
  append(host, renderProvenance(workerOutput.produced_by));
  return host;
}

function renderFinding(finding) {
  const item = el("li", `ps-multi-agent__finding ps-multi-agent__finding--${finding.outcome} ps-multi-agent__finding--${finding.severity}`);
  item.dataset.findingId = finding.id || "";
  const head = el("div", "ps-multi-agent__finding-head");
  append(head, el("span", `ps-multi-agent__severity ps-multi-agent__severity--${finding.severity}`, humaniseValue(finding.severity)), outcomeBadge(finding.outcome));
  if (finding.source === "model") append(head, el("span", "ps-multi-agent__finding-source", "Model finding"));
  append(item, head, el("p", "ps-multi-agent__finding-message", finding.message));
  if (finding.recommendation) {
    const recommendation = el("p", "ps-multi-agent__finding-recommendation");
    append(recommendation, el("strong", "", "Recommendation: "), document.createTextNode(finding.recommendation));
    append(item, recommendation);
  }
  const references = [...(finding.step_ids || []).map((id) => `step ${id}`), ...(finding.evidence_ids || [])];
  if (references.length) append(item, el("code", "ps-multi-agent__reference", references.join(" · ")));
  return item;
}

export function renderReview(review, context, scope = "current", { titled = true, round = 1 } = {}) {
  const labels = context?.labels || DEFAULT_MULTI_AGENT_LABELS;
  const host = section("ps-multi-agent__review", labels.review, { titled });
  if (!review) {
    append(host, el("p", "ps-multi-agent__empty", "The Reviewer has not reported yet."));
    return host;
  }
  const recommendation = el("p", "ps-multi-agent__recommendation");
  append(recommendation, el("span", "", "Recommends "), badge(decisionLabel(review.recommendation, round, labels), review.recommendation === "approve" ? "confirmed" : review.recommendation === "reject" ? "danger" : "partial"));
  recommendation.dataset.recommendation = review.recommendation || "";
  append(host, recommendation);
  if (review.summary) append(host, el("p", "ps-multi-agent__summary", review.summary));
  const groups = groupFindings(review.findings);
  const counts = Object.entries(groups.failedBySeverity).map(([severity, count]) => `${count} ${severity}`).join(", ");
  append(host, el("p", "ps-multi-agent__finding-counts", groups.failed.length ? `${groups.failed.length} failed check${groups.failed.length === 1 ? "" : "s"} (${counts}); ${groups.passed.length} passed.` : `All ${groups.passed.length} recorded check${groups.passed.length === 1 ? "" : "s"} passed.`));
  if (groups.failed.length || groups.notEvaluated.length) {
    const list = el("ul", "ps-multi-agent__findings");
    for (const finding of [...groups.failed, ...groups.notEvaluated]) append(list, renderFinding(finding));
    append(host, list);
  }
  if (groups.passed.length) {
    const passed = disclosure(context, `passed-${scope}`, "ps-multi-agent__passed", `${groups.passed.length} passed check${groups.passed.length === 1 ? "" : "s"}`);
    const list = el("ul", "ps-multi-agent__findings");
    for (const finding of groups.passed) append(list, renderFinding(finding));
    append(passed, list);
    append(host, passed);
  }
  append(host, renderProvenance(review.produced_by));
  return host;
}

export function renderSuperseded(attempt, plan, context) {
  const labels = context?.labels || DEFAULT_MULTI_AGENT_LABELS;
  const groups = groupFindings(attempt.review?.findings);
  const count = attempt.review ? `${decisionLabel(attempt.review.recommendation, attempt.round, labels)} · ${groups.failed.length} failed` : "No review";
  const { details, body } = drawer(context, `superseded-${attempt.round}`, `Round ${attempt.round} (superseded)`, count, { className: "ps-multi-agent__superseded" });
  append(body, el("p", "ps-multi-agent__note", "A person sent this round back, so its evidence and review were replaced. They remain here for comparison."));
  append(body, renderWorker(plan, attempt.worker_output, context, `round-${attempt.round}`), renderReview(attempt.review, context, `round-${attempt.round}`, { round: attempt.round }));
  return details;
}

/** Tool calls recorded so far this round, before the Worker's findings arrive. */
export function renderToolCalls(toolCalls, plan) {
  const list = el("ul", "ps-multi-agent__tool-calls");
  for (const call of toolCalls) {
    const detail = call.detail || {};
    const step = (plan?.steps || []).find((item) => item.id === detail.step_id);
    const item = el("li", `ps-multi-agent__tool-call ps-multi-agent__tool-call--${detail.outcome || "unknown"}`);
    item.dataset.evidenceId = detail.evidence_id || "";
    append(item, el("strong", "", step?.title || humaniseValue(detail.step_id || "step")), outcomeBadge(detail.outcome || "unknown"));
    append(item, el("code", "ps-multi-agent__reference", [detail.tool_name, detail.evidence_id, formatDuration(detail.duration_ms)].filter(Boolean).join(" · ")));
    append(list, item);
  }
  return list;
}

/** The recorded outcome of a finished run. */
export function renderOutcome(run, labels = DEFAULT_MULTI_AGENT_LABELS) {
  const status = workflowStatus(run.state, labels);
  const host = el("section", `ps-multi-agent__outcome ps-multi-agent__outcome--${status.tone}`);
  host.dataset.state = status.key;
  const final = (run.decisions || []).at(-1) || null;
  append(host, el("p", "ps-multi-agent__kicker", "Outcome"));
  const headline = el("p", "ps-multi-agent__outcome-title", status.label);
  if (final) append(headline, el("span", "ps-multi-agent__outcome-by", ` · ${final.actor}, round ${final.round}`));
  append(host, headline);
  if (final?.note) append(host, el("p", "ps-multi-agent__outcome-note", final.note));
  else append(host, el("p", "ps-multi-agent__outcome-note", status.detail));
  if (final?.accepted_step_ids?.length) {
    const titles = final.accepted_step_ids.map((id) => run.plan?.steps?.find((step) => step.id === id)?.title || id);
    append(host, el("p", "ps-multi-agent__note", `Accepted: ${titles.join(", ")}`));
  }
  if (final) append(host, el("p", "ps-multi-agent__safety", labels.outcomeSafety));
  return host;
}

/** In a replay, the decision a person actually recorded at this point. Nothing is sent. */
export function renderRecordedDecision(point, labels = DEFAULT_MULTI_AGENT_LABELS, onContinue = null) {
  const host = el("div", "ps-multi-agent__recorded");
  append(host, el("h4", "ps-multi-agent__kicker", "What was decided"));
  const decision = point?.decision;
  if (decision) {
    const headline = el("p", "ps-multi-agent__suggest", decisionLabel(decision.decision, point.round, labels));
    headline.dataset.decision = decision.decision;
    const waited = point.decidedAt !== null ? formatDuration(point.decidedAt - (point.stageStart ?? point.at)) : "";
    append(host, headline, el("p", "ps-multi-agent__note", `${decision.actor}${waited ? `, after ${waited}` : ""}`));
    if (decision.note) append(host, el("p", "ps-multi-agent__recorded-note", decision.note));
    append(host, el("p", "ps-multi-agent__safety", labels.outcomeSafety));
  } else append(host, el("p", "ps-multi-agent__note", "The run ended without a decision for this round."));
  if (onContinue) {
    const resume = el("button", "ps-button ps-button--primary ps-button--small", "Continue replay");
    resume.type = "button";
    resume.dataset.action = "replay-continue";
    resume.addEventListener("click", onContinue);
    append(host, resume);
  }
  return host;
}

export function renderDecisionLog(decisions, context, { titled = true } = {}) {
  const labels = context?.labels || DEFAULT_MULTI_AGENT_LABELS;
  if (!Array.isArray(decisions) || !decisions.length) return null;
  const host = section("ps-multi-agent__decisions", labels.decisions, { titled });
  const list = el("ol", "ps-multi-agent__decision-log");
  for (const decision of decisions) {
    const item = el("li", "ps-multi-agent__decision-entry");
    item.dataset.decision = decision.decision;
    const head = el("div", "ps-multi-agent__decision-head");
    append(head, el("strong", "", decisionLabel(decision.decision, Number(decision.round) || 1, labels)), el("span", "", `Round ${decision.round} · ${decision.actor}`));
    const time = el("time", "", formatTimestamp(decision.decided_at));
    if (decision.decided_at) time.setAttribute("datetime", decision.decided_at);
    append(head, time);
    append(item, head);
    if (decision.note) append(item, el("p", "", decision.note));
    if (decision.accepted_step_ids?.length) append(item, el("p", "ps-multi-agent__note", `Accepted steps: ${decision.accepted_step_ids.join(", ")}`));
    append(list, item);
  }
  append(host, list);
  return host;
}

export function renderProblem(view, { heading = "" } = {}) {
  const host = el("div", "ps-multi-agent__problem");
  host.setAttribute("role", "alert");
  host.tabIndex = -1;
  if (view.code) host.dataset.code = view.code;
  append(host, el("strong", "ps-multi-agent__problem-title", heading || view.title));
  if (heading && view.title) append(host, el("p", "", view.title));
  if (view.detail) append(host, el("p", "", view.detail));
  if (view.errors.length) {
    const list = el("ul", "ps-multi-agent__problem-errors");
    for (const issue of view.errors) append(list, el("li", "", issue.field ? `${issue.field}: ${issue.message}` : issue.message));
    append(host, list);
  }
  const meta = [view.code && `Code ${view.code}`, view.status && `HTTP ${view.status}`, view.requestId && `Request ${view.requestId}`].filter(Boolean);
  if (meta.length) append(host, el("code", "ps-multi-agent__problem-meta", meta.join(" · ")));
  return host;
}

/** Transitions, then every coordination event as a sentence, timed from the run's start. */
export function renderHistory(view, labels = DEFAULT_MULTI_AGENT_LABELS, { origin = null } = {}) {
  const host = el("div", "ps-multi-agent__history-body");
  const offset = (at) => {
    const parsed = Date.parse(at || "");
    return origin !== null && Number.isFinite(parsed) ? formatClock(parsed - origin) : "";
  };
  if (!view.transitions.length) append(host, el("p", "ps-multi-agent__empty", "No state transitions have been recorded."));
  else {
    const list = el("ol", "ps-multi-agent__transitions");
    for (const entry of view.transitions) {
      const item = el("li");
      const from = entry.from ? workflowStatus(entry.from, labels).label : "Start";
      append(item, el("strong", "", `${from} → ${workflowStatus(entry.to, labels).label}`));
      append(item, el("span", "ps-multi-agent__note", `Round ${entry.round} · ${entry.actor} (${entry.role}) · ${formatTimestamp(entry.at)}`));
      if (entry.reason) append(item, el("p", "", entry.reason));
      append(list, item);
    }
    append(host, list);
  }
  if (view.audit.length) {
    append(host, el("p", "ps-multi-agent__label", `Coordination audit · ${view.audit.length} event${view.audit.length === 1 ? "" : "s"}`));
    const list = el("ol", "ps-multi-agent__audit");
    for (const entry of view.audit) {
      const item = el("li");
      item.dataset.event = entry.event;
      const time = el("time", "ps-multi-agent__audit-time", offset(entry.at));
      if (entry.at) time.setAttribute("datetime", entry.at);
      const sentence = eventSentence({ kind: entry.event, role: entry.role, actor: entry.actor, round: entry.round, detail: entry.detail }, labels);
      append(item, time, el("span", "", sentence), el("code", "ps-multi-agent__audit-event", entry.event));
      append(list, item);
    }
    append(host, list);
  }
  return host;
}
