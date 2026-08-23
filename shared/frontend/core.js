export { append, el } from "./browser/index.js";
import { append, createTableRegion, el } from "./browser/index.js?v=2";

export function humanise(value) {
  if (value === null || value === undefined || value === "") return "Unknown";
  const text = String(value).replaceAll("_", " ").replaceAll("-", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function formatDate(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-AU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatNumber(value) {
  if (value === null || value === undefined || value === "") return "Unknown";
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("en-AU").format(number) : String(value);
}

export function parseShellRoute(hash = "") {
  const value = String(hash).replace(/^#\/?/, "").split("?")[0];
  if (["features", "system-status", "evidence", "release-roadmap"].includes(value)) return value;
  return "home";
}

export function badge(label, tone = "unknown") {
  return el("span", `ps-badge ps-badge--${tone}`, label);
}

export function panel(title, description = "") {
  const card = el("section", "ps-card dashboard-panel");
  const body = el("div", "ps-card__body");
  const heading = el("div", "dashboard-panel__heading");
  append(heading, el("h2", "", title));
  if (description) append(heading, el("p", "", description));
  append(body, heading);
  append(card, body);
  return { card, body };
}

export function notice(tone, title, message) {
  const box = el("div", `dashboard-notice dashboard-notice--${tone}`);
  append(box, el("strong", "", title), el("p", "", message));
  return box;
}

export function pageHeader(eyebrow, title, description, actions = []) {
  const header = el("header", "dashboard-header");
  const copy = el("div");
  append(copy, el("p", "ps-eyebrow", eyebrow), el("h1", "", title), el("p", "dashboard-header__lede", description));
  const actionGroup = el("div", "dashboard-header__actions");
  append(actionGroup, ...actions);
  append(header, copy, actionGroup);
  return header;
}

export function link(label, href, className = "") {
  const anchor = el("a", className, label);
  anchor.href = href;
  return anchor;
}

export function table(headers, rows, rowRenderer, captionText = "") {
  const tableNode = el("table", "dashboard-table");
  const tableLabel = captionText || "Data results";
  append(tableNode, el("caption", "ps-sr-only", tableLabel));
  const head = el("thead");
  const headRow = el("tr");
  for (const header of headers) {
    const heading = el("th", "", header);
    heading.scope = "col";
    append(headRow, heading);
  }
  append(head, headRow);
  const body = el("tbody");
  for (const row of rows) append(body, rowRenderer(row));
  append(tableNode, head, body);
  return createTableRegion(tableNode, tableLabel, { className: "dashboard-table-wrap" });
}

export function cell(content, className = "") {
  const td = el("td", className);
  append(td, content instanceof Node ? content : document.createTextNode(String(content ?? "Unknown")));
  return td;
}

export function requestId() {
  return globalThis.crypto?.randomUUID?.() || `shell-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function requestJson(path, { timeoutMs = 6000 } = {}) {
  const controller = new AbortController();
  const id = requestId();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      headers: { Accept: "application/json", "X-Request-ID": id },
      signal: controller.signal,
    });
    const responseId = response.headers.get("X-Request-ID") || id;
    let body = null;
    try { body = await response.json(); } catch { /* handled as a safe dependency error */ }
    if (!response.ok || body === null) {
      const error = new Error(body?.detail || body?.title || `HTTP ${response.status}`);
      error.requestId = responseId;
      error.status = response.status;
      throw error;
    }
    return { body, requestId: responseId };
  } catch (error) {
    if (error.name === "AbortError") {
      const timeout = new Error(`Timed out after ${timeoutMs / 1000} seconds`);
      timeout.requestId = id;
      throw timeout;
    }
    if (!error.requestId) error.requestId = id;
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export async function requestText(path, { timeoutMs = 6000 } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      headers: { Accept: "text/plain" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } catch (error) {
    if (error.name === "AbortError") throw new Error(`Timed out after ${timeoutMs / 1000} seconds`);
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export function loadingState(message) {
  const state = el("div", "dashboard-loading");
  state.setAttribute("role", "status");
  state.setAttribute("aria-live", "polite");
  append(state, el("span", "dashboard-loading__mark"), el("span", "", message));
  return state;
}
