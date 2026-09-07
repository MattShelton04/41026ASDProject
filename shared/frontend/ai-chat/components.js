import { append, el } from "../browser/index.js";
import { assistantStatus, ACTIVE_ASSISTANT_STATES } from "./definitions.js";
import { isGroundedAnswer, renderGroundedAnswer } from "./grounding.js";
import {
  answerSections, evidenceSteps, formatAssistantDate, humaniseAssistantValue, shortRunId,
} from "./formats.js";

export function assistantBadge(status) {
  const definition = assistantStatus(status);
  return el("span", `ps-badge ps-badge--${definition.tone}`, definition.label);
}

function contextChip(name, value) {
  const item = el("span", "ps-ai-chat__context-chip");
  item.title = `${humaniseAssistantValue(name)}: ${String(value)}`;
  append(item, el("b", "", humaniseAssistantValue(name)), el("code", "", String(value)));
  return item;
}

export function contextSummary(context = {}) {
  const host = el("div", "ps-ai-chat__context");
  const entries = Object.entries(context).filter(([, value]) => value !== null && value !== undefined && value !== "");
  append(host, el("span", "ps-ai-chat__context-label", entries.length ? "Page context" : "Context"));
  if (!entries.length) append(host, el("span", "ps-ai-chat__context-empty", "No page entity attached"));
  else for (const [name, value] of entries) append(host, contextChip(name, value));
  return host;
}

function answerContent(run) {
  if (isGroundedAnswer(run.final_result)) return renderGroundedAnswer(run.final_result);
  const host = el("div", "ps-ai-chat__answer");
  const sections = answerSections(run.final_result);
  if (!sections.length) {
    const status = assistantStatus(run.status);
    const progress = el("p", "ps-ai-chat__progress-copy", status.detail);
    if (ACTIVE_ASSISTANT_STATES.has(String(run.status || "").toLowerCase()) && run.status !== "review_required") {
      const dots = el("span", "ps-ai-chat__typing-dots");
      dots.setAttribute("aria-hidden", "true");
      append(dots, el("i"), el("i"), el("i"));
      append(progress, dots);
    }
    append(host, progress);
    return host;
  }
  for (const section of sections) {
    const block = el("section", `ps-ai-chat__answer-section ps-ai-chat__answer-section--${section.key}`);
    append(block, el("h3", "", section.label));
    if (section.values.length === 1) append(block, el("p", "", section.values[0]));
    else {
      const list = el("ul");
      for (const value of section.values) append(list, el("li", "", value));
      append(block, list);
    }
    append(host, block);
  }
  return host;
}

function evidenceDisclosure(turn) {
  const steps = evidenceSteps(turn.run, turn.events);
  const details = el("details", "ps-ai-chat__evidence");
  details.dataset.disclosure = "evidence";
  const summary = el("summary", "", `Evidence and activity · ${steps.length} recorded step${steps.length === 1 ? "" : "s"}`);
  append(details, summary);
  if (!steps.length) append(details, el("p", "ps-ai-chat__empty-evidence", "No detailed activity has been recorded yet."));
  else {
    const list = el("ol", "ps-ai-chat__timeline");
    for (const step of steps) {
      const item = el("li");
      const marker = el("span", `ps-ai-chat__timeline-marker ps-ai-chat__timeline-marker--${step.status || "unknown"}`);
      marker.setAttribute("aria-hidden", "true");
      const copy = el("div");
      append(copy, el("span", "ps-ai-chat__timeline-phase", step.phase), el("strong", "", step.label), el("p", "", step.summary));
      if (step.references.length) append(copy, el("code", "ps-ai-chat__reference", step.references.join(" · ")));
      append(item, marker, copy);
      append(list, item);
    }
    append(details, list);
  }
  return details;
}

export function renderAssistantTurn(turn, {
  activityHref, onCancel, onRetry, assistantLabel = "PropertyScope assistant",
} = {}) {
  const article = el("article", "ps-ai-chat__turn");
  article.dataset.runId = turn.id || "pending";
  const question = el("section", "ps-ai-chat__message ps-ai-chat__message--user");
  append(question, el("span", "ps-ai-chat__speaker", "You"), el("p", "", turn.message));
  const response = el("section", "ps-ai-chat__message ps-ai-chat__message--assistant");
  const header = el("div", "ps-ai-chat__message-head");
  const responseHeading = el("h2", "ps-ai-chat__speaker", assistantLabel);
  responseHeading.tabIndex = -1;
  append(header, responseHeading);
  if (turn.run?.status) append(header, assistantBadge(turn.run.status));
  append(response, header);
  const scopeUsed = el("p", "ps-ai-chat__scope-used", `Scope: ${turn.scopeLabel || humaniseAssistantValue(turn.scope)}`);
  append(response, scopeUsed);
  if (Object.values(turn.context || {}).some((value) => value != null && value !== "")) {
    const contextUsed = el("details", "ps-ai-chat__context-used");
    contextUsed.dataset.disclosure = "context";
    append(contextUsed, el("summary", "", "Context used for this answer"), contextSummary(turn.context));
    append(response, contextUsed);
  }

  if (turn.error) {
    const failure = el("div", "ps-ai-chat__turn-error");
    failure.setAttribute("role", "alert");
    append(failure, el("strong", "", "This turn could not start"), el("p", "", turn.error.message));
    if (turn.error.requestId) append(failure, el("code", "", `Request ${turn.error.requestId}`));
    if (onRetry) {
      const retry = el("button", "ps-button ps-button--small", "Prepare question again");
      retry.type = "button";
      retry.dataset.action = "retry";
      retry.addEventListener("click", () => onRetry(turn));
      append(failure, retry);
    }
    append(response, failure);
  } else if (String(turn.run?.status || "").toLowerCase() === "failed") {
    const failure = el("div", "ps-ai-chat__turn-error");
    failure.setAttribute("role", "alert");
    append(
      failure,
      el("strong", "", "The assistant could not complete this turn"),
      el("p", "", String(turn.run?.error?.message || "The run stopped without a recorded answer. Its full activity remains available.")),
    );
    if (onRetry) {
      const retry = el("button", "ps-button ps-button--small", "Prepare question again");
      retry.type = "button"; retry.dataset.action = "retry";
      retry.addEventListener("click", () => onRetry(turn));
      append(failure, retry);
    }
    append(response, failure);
    if (turn.id) append(response, evidenceDisclosure(turn));
  } else {
    append(response, answerContent(turn.run || { status: "queued" }));
    if (turn.pollWarning) {
      const warning = el("p", "ps-ai-chat__poll-warning", "Activity updates are temporarily unavailable. The last recorded state is shown; this view will retry automatically.");
      warning.setAttribute("role", "status");
      append(response, warning);
    }
    if (turn.cancelWarning) {
      const warning = el("p", "ps-ai-chat__poll-warning", "Cancellation could not be confirmed. The last recorded state is shown; try again or open full activity.");
      warning.setAttribute("role", "alert");
      append(response, warning);
    }
    if (turn.id) append(response, evidenceDisclosure(turn));
  }

  const footer = el("footer", "ps-ai-chat__turn-meta");
  if (turn.id) {
    append(footer, el("code", "", `Run ${shortRunId(turn.id)}`));
    if (turn.run?.created_at) append(footer, el("span", "", formatAssistantDate(turn.run.created_at)));
    if (activityHref) {
      const activity = el("a", "", "Open full activity");
      activity.href = activityHref(turn.id);
      activity.dataset.action = "activity";
      append(footer, activity);
    }
    if (onCancel && !["succeeded", "failed", "cancelled"].includes(turn.run?.status)) {
      const cancel = el("button", "ps-ai-chat__cancel", turn.cancelPending ? "Requesting cancellation…" : "Cancel turn");
      cancel.type = "button";
      cancel.dataset.action = "cancel";
      cancel.disabled = Boolean(turn.cancelPending);
      cancel.setAttribute("aria-busy", String(Boolean(turn.cancelPending)));
      cancel.addEventListener("click", () => onCancel(turn));
      append(footer, cancel);
    }
  } else if (!turn.error) {
    const creating = el("span", "ps-ai-chat__creating", "Creating durable run");
    const dots = el("span", "ps-ai-chat__typing-dots");
    dots.setAttribute("aria-hidden", "true");
    append(dots, el("i"), el("i"), el("i"));
    append(creating, dots);
    append(footer, creating);
  }
  append(response, footer);
  append(article, question, response);
  return article;
}
