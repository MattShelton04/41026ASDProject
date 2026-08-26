import { append, el } from "../browser/index.js";
import { assistantStatus } from "./definitions.js";
import {
  answerSections, evidenceSteps, formatAssistantDate, humaniseAssistantValue, shortRunId,
} from "./formats.js";

export function assistantBadge(status) {
  const definition = assistantStatus(status);
  return el("span", `ps-badge ps-badge--${definition.tone}`, definition.label);
}

function contextChip(name, value) {
  const item = el("span", "ps-ai-chat__context-chip");
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
  const host = el("div", "ps-ai-chat__answer");
  const sections = answerSections(run.final_result);
  if (!sections.length) {
    const status = assistantStatus(run.status);
    append(host, el("p", "ps-ai-chat__progress-copy", status.detail));
    return host;
  }
  for (const section of sections) {
    const block = el("section", `ps-ai-chat__answer-section ps-ai-chat__answer-section--${section.key}`);
    append(block, el("h4", "", section.label));
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

export function renderAssistantTurn(turn, { activityHref, onCancel, onRetry } = {}) {
  const article = el("article", "ps-ai-chat__turn");
  article.dataset.runId = turn.id || "pending";
  const question = el("section", "ps-ai-chat__message ps-ai-chat__message--user");
  append(question, el("span", "ps-ai-chat__speaker", "You"), el("p", "", turn.message));
  const response = el("section", "ps-ai-chat__message ps-ai-chat__message--assistant");
  const header = el("div", "ps-ai-chat__message-head");
  append(header, el("span", "ps-ai-chat__speaker", "PropertyScope assistant"));
  if (turn.run?.status) append(header, assistantBadge(turn.run.status));
  append(response, header);

  if (turn.error) {
    const failure = el("div", "ps-ai-chat__turn-error");
    failure.setAttribute("role", "alert");
    append(failure, el("strong", "", "This turn could not start"), el("p", "", turn.error.message));
    if (turn.error.requestId) append(failure, el("code", "", `Request ${turn.error.requestId}`));
    if (onRetry) {
      const retry = el("button", "ps-button ps-button--small", "Retry turn");
      retry.type = "button";
      retry.addEventListener("click", () => onRetry(turn));
      append(failure, retry);
    }
    append(response, failure);
  } else {
    append(response, answerContent(turn.run || { status: "queued" }));
    if (turn.pollWarning) {
      const warning = el("p", "ps-ai-chat__poll-warning", "Live activity is temporarily unavailable. The durable run is still safe; this view will retry automatically.");
      warning.setAttribute("role", "status");
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
      append(footer, activity);
    }
    if (onCancel && !["succeeded", "failed", "cancelled"].includes(turn.run?.status)) {
      const cancel = el("button", "ps-ai-chat__cancel", "Cancel turn");
      cancel.type = "button";
      cancel.addEventListener("click", () => onCancel(turn));
      append(footer, cancel);
    }
  } else append(footer, el("span", "", "Creating durable run…"));
  append(response, footer);
  append(article, question, response);
  return article;
}
