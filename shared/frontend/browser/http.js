/** One bounded JSON transport; feature adapters own their API paths and domain errors. */
import { RequestTimeoutError, withRequestLifecycle } from "./request.js";

export class HttpProblem extends Error {
  constructor(message, { status = 0, requestId = "", problem = null, cause } = {}) {
    super(message, { cause });
    this.name = "HttpProblem";
    this.status = status;
    this.requestId = requestId;
    this.problem = problem;
    this.code = problem?.code || "request_failed";
  }
}

export function newRequestId() {
  return globalThis.crypto?.randomUUID?.() || `web-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function mergedHeaders(input, body) {
  const result = { Accept: "application/json", "X-Request-ID": newRequestId() };
  if (body !== undefined) result["Content-Type"] = "application/json";
  const entries = input instanceof Headers ? input.entries() : Array.isArray(input) ? input : Object.entries(input || {});
  for (const [name, value] of entries) {
    const existing = Object.keys(result).find((key) => key.toLowerCase() === name.toLowerCase());
    result[existing || name] = String(value);
  }
  return result;
}

export async function requestJsonResponse(fetcher, path, {
  timeoutMs = 10000, headers = {}, body, signal = null, signals = [],
  throwHttpErrors = true, ErrorClass = HttpProblem, unavailableMessage = "The service could not be reached.",
  timeoutMessage = `The request timed out after ${timeoutMs / 1000} seconds.`, ...options
} = {}) {
  const requestHeaders = mergedHeaders(headers, body);
  let id = requestHeaders["X-Request-ID"];
  try {
    return await withRequestLifecycle(async (requestSignal) => {
      const response = await fetcher(path, {
        ...options, headers: requestHeaders, signal: requestSignal,
        body: body === undefined || typeof body === "string" ? body : JSON.stringify(body),
      });
      id = response.headers?.get?.("X-Request-ID") || id;
      if (response.status === 204) return { body: null, response, requestId: id };
      let payload;
      try { payload = await response.json(); } catch (cause) {
        requestSignal.throwIfAborted();
        throw new ErrorClass("The service returned an unreadable response.", {
          status: response.status, requestId: id, cause,
        });
      }
      requestSignal.throwIfAborted();
      if ((throwHttpErrors && !response.ok) || payload === null) {
        throw new ErrorClass(payload?.detail || payload?.message || payload?.title || `HTTP ${response.status} request failed`, {
          status: response.status, requestId: id, problem: payload,
        });
      }
      return { body: payload, response, requestId: id };
    }, { signal, signals, timeoutMs });
  } catch (error) {
    if (error instanceof RequestTimeoutError) throw new ErrorClass(timeoutMessage, { requestId: id, cause: error });
    if ([signal, ...signals].some((source) => source?.aborted) || error?.name === "AbortError") throw error;
    if (error instanceof ErrorClass) throw error;
    throw new ErrorClass(unavailableMessage, { requestId: id, cause: error });
  }
}

export function createJsonClient({ baseUrl = "", fetcher = (...args) => globalThis.fetch(...args), ...defaults } = {}) {
  return async (path, options = {}) => (await requestJsonResponse(fetcher, `${baseUrl}${path}`, { ...defaults, ...options })).body;
}
