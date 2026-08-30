import { RequestTimeoutError, withRequestLifecycle } from "../browser/index.js";

export class AssistantApiError extends Error {
  constructor(message, { status = 0, requestId = "", problem = null } = {}) {
    super(message);
    this.name = "AssistantApiError";
    this.status = status;
    this.requestId = requestId;
    this.problem = problem;
  }
}

function requestId() {
  return globalThis.crypto?.randomUUID?.() || `assistant-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function assistantRequest(fetcher, path, {
  timeoutMs = 10000, body, headers = {}, signal = null, signals = [], ...options
} = {}) {
  const id = requestId();
  try {
    const response = await withRequestLifecycle((requestSignal) => fetcher(path, {
      ...options,
      headers: {
        Accept: "application/json",
        "X-Request-ID": id,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: requestSignal,
    }), { signal, signals, timeoutMs });
    const responseId = response.headers?.get?.("X-Request-ID") || id;
    let payload = null;
    try { payload = await response.json(); } catch { /* converted below */ }
    if (!response.ok || payload === null) {
      throw new AssistantApiError(
        payload?.detail || payload?.title || `Assistant request failed with HTTP ${response.status}`,
        { status: response.status, requestId: responseId, problem: payload },
      );
    }
    return { body: payload, requestId: responseId };
  } catch (error) {
    if (error instanceof RequestTimeoutError) throw new AssistantApiError("The assistant request timed out.", { requestId: id });
    if (error.name === "AbortError") throw error;
    if (error instanceof AssistantApiError) throw error;
    throw new AssistantApiError("The assistant service could not be reached.", { requestId: id });
  }
}

export function createAssistantClient({ fetcher = globalThis.fetch.bind(globalThis), apiRoot = "/api/assistant/v1" } = {}) {
  const root = apiRoot.replace(/\/$/, "");
  const lifecycle = new AbortController();
  const request = (path, options = {}) => assistantRequest(fetcher, path, {
    ...options,
    signals: [lifecycle.signal, ...(options.signals || [])],
  });
  return Object.freeze({
    capabilities: () => request(`${root}/capabilities`),
    createTurn: (turn) => request(`${root}/turns`, { method: "POST", body: turn, timeoutMs: 15000 }),
    getTurn: (runId) => request(`${root}/turns/${encodeURIComponent(runId)}`),
    getEvents: (runId, after = 0) => request(`${root}/turns/${encodeURIComponent(runId)}/events?after=${after}&limit=100`),
    cancelTurn: (runId) => request(`${root}/turns/${encodeURIComponent(runId)}/cancel`, { method: "POST" }),
    destroy: () => lifecycle.abort(),
  });
}
