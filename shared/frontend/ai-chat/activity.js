/** Safe presentation of persisted work. Never infer evidence from elapsed time. */
import { append, el } from "../browser/index.js";
import { assistantStatus } from "./definitions.js";
import { humaniseAssistantValue } from "./formats.js";

export function recordedToolChecks(run, labels = {}) {
  const checks = new Map();
  for (const step of Array.isArray(run?.steps) ? run.steps : []) {
    const calls = Array.isArray(step.input?.tool_calls) ? step.input.tool_calls : [step.input?.tool_call].filter(Boolean);
    const results = Array.isArray(step.output?.tool_results) ? step.output.tool_results : [step.output?.tool_result].filter(Boolean);
    const actions = Array.isArray(step.input?.actions) ? step.input.actions : [step.input?.action].filter(Boolean);
    for (const [index, call] of calls.entries()) {
      if (!call?.id || !call.tool_name) continue;
      const result = results.find((item) => item?.call_id === call.id);
      checks.set(call.id, {
        id: call.id, tool: call.tool_name,
        label: labels[call.tool_name] || humaniseAssistantValue(call.tool_name.replace(/\.v\d+$/, "").replaceAll(".", " ")),
        purpose: String(actions[index]?.purpose || "").slice(0, 240),
        status: result?.outcome || (step.status === "running" ? "running" : step.status === "failed" ? "failed" : "pending"),
        durationMs: result?.duration_ms,
        result, startedAt: step.started_at,
      });
    }
  }
  return [...checks.values()];
}

export function activityPresentation(run, labels = {}) {
  const checks = recordedToolChecks(run, labels);
  const active = checks.filter((item) => item.status === "running");
  const done = checks.filter((item) => item.status === "succeeded").length;
  const states = {
    queued: ["Waiting to start", "Your question is queued. You can draft a follow-up while you wait."],
    planning: ["Choosing source checks", "Finding the information needed to answer your question."],
    ready: ["Preparing the next check", "The next source check is ready to run."],
    acting: [active.length > 1 ? `Checking ${active.length} sources` : active[0]?.label || "Checking a source", active.map((item) => item.purpose || item.label).join(" · ") || "Waiting for the source to respond."],
    observing: ["Checking the results", "Recording which checks completed and what they returned."],
    adapting: ["Preparing your answer", "Matching the findings to their supporting evidence."],
  };
  const fallback = assistantStatus(run?.status);
  const [title, detail] = states[run?.status] || [fallback.label, fallback.detail];
  return { title, detail, checks, done, active: Boolean(states[run?.status]) };
}

export function renderActivityProgress(run, labels = {}) {
  const value = activityPresentation(run, labels);
  const host = el("div", "ps-ai-chat__live-activity");
  host.classList.toggle("ps-ai-chat__live-activity--active", value.active);
  const head = el("div", "ps-ai-chat__live-head");
  const mark = el("span", "ps-ai-chat__activity-mark", value.active ? "✳" : "✓");
  mark.setAttribute("aria-hidden", "true");
  const title = el("strong", "", value.title);
  const elapsed = el("span", "ps-ai-chat__elapsed");
  if (run?.created_at && value.active) elapsed.dataset.elapsedStart = run.created_at;
  append(head, mark, title, elapsed);
  append(host, head, el("p", "ps-ai-chat__live-detail", value.detail));
  if (value.checks.length) {
    const list = el("ul", "ps-ai-chat__check-list");
    for (const check of value.checks.slice(-8)) {
      const item = el("li", `ps-ai-chat__check ps-ai-chat__check--${check.status}`);
      const icon = el("span", "", check.status === "succeeded" ? "✓" : check.status === "failed" ? "!" : "○");
      icon.setAttribute("aria-hidden", "true");
      append(item, icon, el("span", "", check.label), el("small", "", check.status === "succeeded" ? "Checked" : check.status === "running" ? "In progress" : humaniseAssistantValue(check.status)));
      append(list, item);
    }
    append(host, list);
  }
  return host;
}

export function toolSourceCard(check) {
  const details = el("details", "ps-ai-chat__source ps-ai-chat__source--tool");
  details.dataset.disclosure = `tool:${check.id}`;
  append(details, el("summary", "", check.label));
  const body = el("div", "ps-ai-chat__source-body");
  append(body, el("span", "ps-badge ps-badge--confirmed", "Recorded source check"));
  if (check.purpose) append(body, el("p", "", check.purpose));
  const fields = el("dl", "ps-ai-chat__source-facts");
  const content = check.result?.content;
  if (content && typeof content === "object" && !Array.isArray(content)) {
    for (const [key, value] of Object.entries(content).filter(([, value]) => value === null || ["string", "number", "boolean"].includes(typeof value)).slice(0, 12)) {
      const row = el("div");
      append(row, el("dt", "", humaniseAssistantValue(key)), el("dd", "", value === null ? "Not recorded" : String(value).slice(0, 1500)));
      append(fields, row);
    }
  }
  append(body, fields);
  const raw = el("details", "ps-ai-chat__recorded-fields");
  raw.dataset.disclosure = `fields:${check.id}`;
  const serialized = JSON.stringify(content ?? {}, null, 2);
  append(raw, el("summary", "", "Recorded fields"), el("pre", "", serialized.length > 12000 ? `${serialized.slice(0, 12000)}\n… Display shortened. Full result is in activity history.` : serialized));
  append(body, raw, el("code", "ps-ai-chat__reference", `Call ${check.id}`));
  if (Number.isFinite(check.durationMs)) append(body, el("span", "ps-ai-chat__grounding-note", `Source responded in ${(check.durationMs / 1000).toFixed(2)} seconds.`));
  append(details, body);
  return details;
}
