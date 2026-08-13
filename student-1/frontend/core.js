export const API_BASE = "/api/data-platform/v1";
export const ACTIVE_RUN_STATES = new Set([
  "requested", "queued", "planning", "discovering", "acquiring", "staging",
  "normalising", "validating", "building_release", "running", "cancelling", "resuming",
]);
export const TERMINAL_RUN_STATES = new Set(["succeeded", "failed", "cancelled"]);

export class ApiError extends Error {
  constructor(message, { status = 0, requestId = "", problem = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.requestId = requestId;
    this.problem = problem;
  }
}

export function newRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function requestJson(fetcher, path, options = {}) {
  const { timeoutMs = 10000, headers = {}, body, ...rest } = options;
  const controller = new AbortController();
  const requestId = headers["X-Request-ID"] || headers["X-Request-Id"] || newRequestId();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(path.startsWith("/") ? path : `${API_BASE}/${path}`, {
      ...rest,
      headers: {
        Accept: "application/json",
        "X-Request-ID": requestId,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...headers,
      },
      body: body === undefined || typeof body === "string" ? body : JSON.stringify(body),
      signal: controller.signal,
    });
    const responseRequestId = response.headers?.get?.("X-Request-ID") || response.headers?.get?.("X-Request-Id") || requestId;
    if (response.status === 204) return { body: null, response, requestId: responseRequestId };
    let parsed = null;
    try { parsed = await response.json(); } catch { /* converted to a safe error below */ }
    if (!response.ok) {
      const message = parsed?.detail || parsed?.message || parsed?.title || `${response.status} request failed`;
      throw new ApiError(message, { status: response.status, requestId: responseRequestId, problem: parsed });
    }
    if (parsed === null) throw new ApiError("The service returned an unreadable response.", { status: response.status, requestId: responseRequestId });
    return { body: parsed, response, requestId: responseRequestId };
  } catch (error) {
    if (error.name === "AbortError") throw new ApiError(`The request timed out after ${timeoutMs / 1000} seconds.`, { requestId });
    if (error instanceof ApiError) throw error;
    throw new ApiError("The data service could not be reached.", { requestId });
  } finally {
    clearTimeout(timer);
  }
}

export function collection(payload) {
  if (Array.isArray(payload)) return payload;
  for (const key of ["items", "results", "sources", "jobs", "runs", "releases", "quality_results", "artifacts"]) {
    if (Array.isArray(payload?.[key])) return payload[key];
  }
  return [];
}

export function entity(payload, preferred = "") {
  if (!payload || typeof payload !== "object") return payload;
  if (preferred && payload[preferred]) return payload[preferred];
  for (const key of ["item", "source", "job", "run", "release", "property", "agent_run"]) {
    if (payload[key] && typeof payload[key] === "object") return payload[key];
  }
  return payload;
}

export function queryString(values) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) {
    if (value !== "" && value !== null && value !== undefined) params.set(key, String(value));
  }
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function humanise(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("en-AU").format(number) : "—";
}

export function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes;
  let unit = -1;
  do { size /= 1024; unit += 1; } while (size >= 1024 && unit < units.length - 1);
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}

export function formatDate(value) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function statusTone(status) {
  const value = String(status || "unknown").toLowerCase();
  if (["accepted", "succeeded", "pass", "passed", "active", "available", "supported", "complete", "completed", "healthy", "published"].includes(value)) return "positive";
  if (["failed", "rejected", "blocked", "unavailable", "cancelled", "error", "unhealthy"].includes(value)) return "negative";
  if (["partial", "warning", "warn", "stale", "candidate", "review", "review_required", "awaiting_review", "cancelling"].includes(value)) return "warning";
  if (ACTIVE_RUN_STATES.has(value) || ["draft", "pending"].includes(value)) return "info";
  return "neutral";
}

export function stateLabel(status) {
  const symbols = { positive: "✓", negative: "!", warning: "△", info: "↻", neutral: "•" };
  const tone = statusTone(status);
  return { text: humanise(status || "Unknown"), tone, symbol: symbols[tone] };
}

export function parseJsonField(value, label) {
  if (!String(value || "").trim()) return {};
  try {
    const result = JSON.parse(value);
    if (result === null || typeof result !== "object" || Array.isArray(result)) throw new Error();
    return result;
  } catch {
    throw new Error(`${label} must be a JSON object.`);
  }
}

export function psiYearRange(startValue, endValue, { minimum = 1990, maximum = new Date().getFullYear() + 1 } = {}) {
  const start = Number(startValue);
  const end = Number(endValue);
  if (!Number.isInteger(start) || !Number.isInteger(end) || start < minimum || end > maximum || start > end) {
    throw new Error(`PSI years must be a valid range from ${minimum} to ${maximum}.`);
  }
  return Array.from({ length: end - start + 1 }, (_unused, index) => start + index);
}

export function isPsiJob(job) {
  const identity = [job?.profile_key, job?.adapter_key, job?.import_profile_key, job?.dataset_id]
    .map((value) => String(value || "").toLowerCase())
    .join(" ");
  return identity.includes("psi");
}

export function isSchoolsJob(job) {
  const identity = [job?.profile_key, job?.adapter_key, job?.import_profile_key, job?.dataset_id]
    .map((value) => String(value || "").toLowerCase())
    .join(" ");
  return identity.includes("school");
}

export function liveProfileLabel(importProfile) {
  const labels = {
    "schools-master": "Live official Data.NSW schools CSV",
    "bocsar-sparse": "Live official BOCSAR archive",
    "gnaf-nsw": "Live official Geoscape G-NAF bulk archive",
    "psi-sales": "Live NSW Valuer-General yearly archive",
  };
  return labels[String(importProfile || "")] || "Live registered source";
}

export function actionAvailability(status) {
  const state = String(status || "").toLowerCase();
  return {
    cancel: ACTIVE_RUN_STATES.has(state) && state !== "cancelling",
    resume: ["interrupted", "paused"].includes(state),
    retry: ["failed", "cancelled"].includes(state),
    reprocess: ["failed", "succeeded", "cancelled"].includes(state),
    diagnose: !ACTIVE_RUN_STATES.has(state),
  };
}

export function nextPollDelay(status, failures = 0, hidden = false) {
  if (!ACTIVE_RUN_STATES.has(String(status || "").toLowerCase())) return null;
  const base = status === "queued" || status === "requested" ? 2000 : 1200;
  const backedOff = Math.min(15000, base * (2 ** Math.min(failures, 3)));
  return hidden ? Math.max(10000, backedOff * 3) : backedOff;
}

export function coverageRows(payload) {
  if (Array.isArray(payload)) return payload;
  const direct = collection(payload);
  if (direct.length) return direct;
  const matrix = payload?.matrix || payload?.coverage || {};
  const rows = [];
  for (const [dataset, localities] of Object.entries(matrix)) {
    if (Array.isArray(localities)) {
      for (const item of localities) rows.push({ dataset, ...item });
    } else if (localities && typeof localities === "object") {
      for (const [locality, state] of Object.entries(localities)) rows.push({ dataset, locality, ...(typeof state === "object" ? state : { status: state }) });
    }
  }
  return rows;
}

export function releaseComparison(candidate, predecessor) {
  if (!candidate || !predecessor) return [];
  return [
    ["Schema version", candidate.schema_version, predecessor.schema_version],
    ["Record count", candidate.record_count, predecessor.record_count],
    ["Content checksum", candidate.content_sha256, predecessor.content_sha256],
    ["Coverage", candidate.coverage_json, predecessor.coverage_json],
  ].map(([field, candidateValue, predecessorValue]) => ({
    field,
    candidate: candidateValue,
    predecessor: predecessorValue,
    changed: JSON.stringify(candidateValue) !== JSON.stringify(predecessorValue),
  }));
}

export function reportReleaseRows(payload) {
  if (!payload || typeof payload !== "object") return [];
  return Array.isArray(payload.release_evidence) ? payload.release_evidence : [];
}
