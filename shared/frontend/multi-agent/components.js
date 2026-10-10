/** Stateless renderers for one workflow run. Every untrusted value is set as text, never HTML. */
import { append, el } from "../browser/index.js";
import { DEFAULT_MULTI_AGENT_LABELS, humaniseValue, workflowStatus } from "./definitions.js";
import {
  evidenceExcerpt, formatDuration, formatTimestamp, groupFindings, provenanceLabel, workerStepViews,
} from "./projections.js";

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

function section(className, heading, level = "h4") {
  const host = el("section", `ps-multi-agent__section ${className}`);
  append(host, el(level, "ps-multi-agent__section-title", heading));
  return host;
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

export function renderTimeline(items, { elapsed = [] } = {}) {
  const list = el("ol", "ps-multi-agent__timeline");
  list.setAttribute("aria-label", "Workflow stages");
  for (const item of items) {
    const row = el("li", `ps-multi-agent__stage ps-multi-agent__stage--${item.status}`);
    row.dataset.stage = item.stage;
    row.dataset.status = item.status;
    const marker = el("span", "ps-multi-agent__stage-marker");
    marker.setAttribute("aria-hidden", "true");
    const copy = el("div", "ps-multi-agent__stage-copy");
    const head = el("div", "ps-multi-agent__stage-head");
    append(head, el("strong", "", item.label), el("span", "ps-multi-agent__stage-round", `Round ${item.round}`));
    append(copy, head, el("span", "ps-multi-agent__stage-status", item.statusLabel));
    const timing = el("span", "ps-multi-agent__stage-timing");
    if (item.durationMs !== null) timing.textContent = formatDuration(item.durationMs);
    else if (item.startedAt && (item.status === "running" || item.status === "waiting")) {
      timing.dataset.elapsedStart = item.startedAt;
      elapsed.push(timing);
    }
    if (item.startedAt) timing.title = `Started ${formatTimestamp(item.startedAt)}`;
    if (timing.textContent || timing.dataset.elapsedStart) append(copy, timing);
    if (item.detail) append(copy, el("span", "ps-multi-agent__stage-detail", item.detail));
    append(row, marker, copy);
    append(list, row);
  }
  return list;
}

export function renderPlan(plan, context) {
  const labels = context?.labels || DEFAULT_MULTI_AGENT_LABELS;
  const host = section("ps-multi-agent__plan", labels.plan);
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

export function renderWorker(plan, workerOutput, context, scope = "current") {
  const labels = context?.labels || DEFAULT_MULTI_AGENT_LABELS;
  const host = section("ps-multi-agent__worker", labels.worker);
  if (!workerOutput) {
    append(host, el("p", "ps-multi-agent__empty", "The Worker has not recorded evidence yet."));
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

export function renderReview(review, context, scope = "current") {
  const labels = context?.labels || DEFAULT_MULTI_AGENT_LABELS;
  const host = section("ps-multi-agent__review", labels.review);
  if (!review) {
    append(host, el("p", "ps-multi-agent__empty", "The Reviewer has not reported yet."));
    return host;
  }
  const recommendation = el("p", "ps-multi-agent__recommendation");
  const option = labels.decisionOptions?.[review.recommendation];
  append(recommendation, el("span", "", "Recommends "), badge(option?.label || humaniseValue(review.recommendation), review.recommendation === "approve" ? "confirmed" : review.recommendation === "reject" ? "danger" : "partial"));
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
  const details = disclosure(context, `superseded-${attempt.round}`, "ps-multi-agent__superseded", `Round ${attempt.round} (superseded)`);
  append(details, el("p", "ps-multi-agent__note", "A person requested a correction, so this round's evidence and review were replaced. They remain here for comparison."));
  append(details, renderWorker(plan, attempt.worker_output, context, `round-${attempt.round}`), renderReview(attempt.review, context, `round-${attempt.round}`));
  return details;
}

export function renderDecisionLog(decisions, context) {
  const labels = context?.labels || DEFAULT_MULTI_AGENT_LABELS;
  if (!Array.isArray(decisions) || !decisions.length) return null;
  const host = section("ps-multi-agent__decisions", labels.decisions);
  const list = el("ol", "ps-multi-agent__decision-log");
  for (const decision of decisions) {
    const item = el("li", "ps-multi-agent__decision-entry");
    item.dataset.decision = decision.decision;
    const head = el("div", "ps-multi-agent__decision-head");
    const option = labels.decisionOptions?.[decision.decision];
    append(head, el("strong", "", option?.label || humaniseValue(decision.decision)), el("span", "", `Round ${decision.round} · ${decision.actor}`));
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

export function renderHistory(view, labels = DEFAULT_MULTI_AGENT_LABELS) {
  const host = el("div", "ps-multi-agent__history-body");
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
  const counts = Object.entries(view.eventCounts);
  if (counts.length) {
    append(host, el("p", "ps-multi-agent__label", `Coordination audit · ${view.audit.length} event${view.audit.length === 1 ? "" : "s"}`));
    const list = el("ul", "ps-multi-agent__audit");
    for (const [event, count] of counts) {
      const item = el("li");
      append(item, el("code", "", event), el("span", "", ` × ${count}`));
      append(list, item);
    }
    append(host, list);
  }
  return host;
}
