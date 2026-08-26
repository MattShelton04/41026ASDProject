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

export async function assistantRequest(fetcher, path, { timeoutMs = 10000, body, headers = {}, ...options } = {}) {
  const controller = new AbortController();
  const id = requestId();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(path, {
      ...options,
      headers: {
        Accept: "application/json",
        "X-Request-ID": id,
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
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
    if (error.name === "AbortError") throw new AssistantApiError("The assistant request timed out.", { requestId: id });
    if (error instanceof AssistantApiError) throw error;
    throw new AssistantApiError("The assistant service could not be reached.", { requestId: id });
  } finally {
    clearTimeout(timeout);
  }
}

export function createAssistantClient({ fetcher = globalThis.fetch.bind(globalThis), apiRoot = "/api/assistant/v1" } = {}) {
  const root = apiRoot.replace(/\/$/, "");
  return Object.freeze({
    capabilities: () => assistantRequest(fetcher, `${root}/capabilities`),
    createTurn: (turn) => assistantRequest(fetcher, `${root}/turns`, { method: "POST", body: turn, timeoutMs: 15000 }),
    getTurn: (runId) => assistantRequest(fetcher, `${root}/turns/${encodeURIComponent(runId)}`),
    getEvents: (runId, after = 0) => assistantRequest(fetcher, `${root}/turns/${encodeURIComponent(runId)}/events?after=${after}&limit=100`),
    cancelTurn: (runId) => assistantRequest(fetcher, `${root}/turns/${encodeURIComponent(runId)}/cancel`, { method: "POST" }),
  });
}
