/** Feature-backend proxy client. The panel never calls the Multi-Agent Server directly. */
import { HttpProblem, requestJsonResponse } from "../browser/index.js";

export class MultiAgentApiError extends HttpProblem {
  constructor(message, options = {}) { super(message, options); this.name = "MultiAgentApiError"; }
}

export async function multiAgentRequest(fetcher, path, options = {}) {
  const { body, requestId } = await requestJsonResponse(fetcher, path, {
    ...options, ErrorClass: MultiAgentApiError,
    unavailableMessage: "The review service could not be reached.",
    timeoutMessage: "The review request timed out.",
  });
  return { body, requestId };
}

function runPath(root, runId, suffix = "") {
  const id = String(runId || "");
  if (!id) throw new TypeError("A workflow run ID is required");
  return `${root}/${encodeURIComponent(id)}${suffix}`;
}

/**
 * Every method resolves to `{body, requestId}` and accepts `{signal}` for caller cancellation.
 * `destroy()` aborts every in-flight request; create one client per mounted panel.
 */
export function createMultiAgentClient({ fetcher = globalThis.fetch.bind(globalThis), apiRoot } = {}) {
  if (!apiRoot) throw new TypeError("createMultiAgentClient requires the feature backend apiRoot");
  const root = String(apiRoot).replace(/\/$/, "");
  const lifecycle = new AbortController();
  const request = (path, { signal = null, ...options } = {}) => multiAgentRequest(fetcher, path, {
    ...options,
    signals: [lifecycle.signal, signal].filter(Boolean),
  });
  return Object.freeze({
    apiRoot: root,
    getTemplate: (options = {}) => request(`${root}/template`, options),
    listRuns: ({ limit = 20, state = "", ...options } = {}) => {
      const query = new URLSearchParams({ limit: String(limit) });
      if (state) query.set("state", state);
      return request(`${root}?${query}`, options);
    },
    startRun: (input, { requestedBy = "", ...options } = {}) => request(root, {
      ...options, method: "POST", timeoutMs: 15000,
      body: requestedBy ? { input, requested_by: requestedBy } : { input },
    }),
    getRun: (runId, options = {}) => request(runPath(root, runId), options),
    decide: (runId, decision, options = {}) => request(runPath(root, runId, "/decision"), {
      ...options, method: "POST", body: decision, timeoutMs: 15000,
    }),
    cancel: (runId, { actor = "", ...options } = {}) => request(runPath(root, runId, "/cancel"), {
      ...options, method: "POST", body: actor ? { actor } : {},
    }),
    getHistory: (runId, options = {}) => request(runPath(root, runId, "/history"), options),
    destroy: () => lifecycle.abort(),
  });
}
