import { HttpProblem, requestJsonResponse } from "../browser/index.js";
export { newRequestId } from "../browser/index.js";

export const API_BASE = "/api/data-platform/v1";
export class ApiError extends HttpProblem {
  constructor(message, options = {}) { super(message, options); this.name = "ApiError"; }
}

export function requestJson(fetcher, path, options = {}) {
  return requestJsonResponse(fetcher, path.startsWith("/") ? path : `${API_BASE}/${path}`, {
    ...options, ErrorClass: ApiError, unavailableMessage: "The data service could not be reached.",
  });
}

/** Correlation suffix for user-facing error or success text; empty when no request ID is known. */
export function requestIdSuffix(source) {
  return source?.requestId ? ` Request ID ${source.requestId}.` : "";
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
