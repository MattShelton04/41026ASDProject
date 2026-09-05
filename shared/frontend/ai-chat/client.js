import { HttpProblem, requestJsonResponse } from "../browser/index.js";

export class AssistantApiError extends HttpProblem {
  constructor(message, options = {}) { super(message, options); this.name = "AssistantApiError"; }
}

export async function assistantRequest(fetcher, path, options = {}) {
  const { body, requestId } = await requestJsonResponse(fetcher, path, {
    ...options, ErrorClass: AssistantApiError,
    unavailableMessage: "The assistant service could not be reached.",
    timeoutMessage: "The assistant request timed out.",
  });
  return { body, requestId };
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
