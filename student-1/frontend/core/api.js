import { RequestTimeoutError, withRequestLifecycle } from "./request.js";

export const API_BASE = "/api/data-platform/v1";

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
  const {
    timeoutMs = 10000, headers = {}, body, signal = null, signals = [], ...rest
  } = options;
  const requestId = headers["X-Request-ID"] || headers["X-Request-Id"] || newRequestId();
  try {
    const response = await withRequestLifecycle((requestSignal) => fetcher(
      path.startsWith("/") ? path : `${API_BASE}/${path}`,
      {
        ...rest,
        headers: {
          Accept: "application/json",
          "X-Request-ID": requestId,
          ...(body === undefined ? {} : { "Content-Type": "application/json" }),
          ...headers,
        },
        body: body === undefined || typeof body === "string" ? body : JSON.stringify(body),
        signal: requestSignal,
      },
    ), { signal, signals, timeoutMs });
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
    if (error instanceof RequestTimeoutError) throw new ApiError(`The request timed out after ${timeoutMs / 1000} seconds.`, { requestId });
    if (error.name === "AbortError") throw error;
    if (error instanceof ApiError) throw error;
    throw new ApiError("The data service could not be reached.", { requestId });
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
