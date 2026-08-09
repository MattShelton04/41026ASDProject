export const ACTIVE_STATUSES = new Set([
  "queued", "planning", "ready", "acting", "observing", "adapting",
]);
export const TERMINAL_STATUSES = new Set(["succeeded", "failed", "cancelled"]);
export const MAX_EVENT_ITEMS = 200;
export const MAX_HISTORY_PAGES = 3;

const ACTIVE_FILTER = [...ACTIVE_STATUSES];
const FILTER_GROUPS = Object.freeze({
  all: [],
  active: ACTIVE_FILTER,
  review: ["review_required"],
  failed: ["failed"],
});

export class RequestTimeoutError extends Error {
  constructor(timeoutMs) {
    super(`Request timed out after ${timeoutMs} ms`);
    this.name = "RequestTimeoutError";
  }
}

export class GenerationGuard {
  constructor() { this.current = 0; }
  advance() { this.current += 1; return this.current; }
  isCurrent(generation) { return generation === this.current; }
}

export function statusesForFilter(name) {
  return [...(FILTER_GROUPS[name] || FILTER_GROUPS.all)];
}

export function filterForStatuses(statuses) {
  const normalized = [...new Set(statuses)].sort().join(",");
  for (const [name, values] of Object.entries(FILTER_GROUPS)) {
    if ([...values].sort().join(",") === normalized) return name;
  }
  return "all";
}

export function restoreCursor(value) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 0 ? parsed : 0;
}

export function mergeEventPage(existing, incoming, limit = MAX_EVENT_ITEMS) {
  const byId = new Map(existing.map((event) => [event.id, event]));
  for (const event of incoming) byId.set(event.id, event);
  const items = [...byId.values()].sort((left, right) => left.id - right.id).slice(-limit);
  return {
    items,
    cursor: items.length ? items[items.length - 1].id : 0,
  };
}

export function shouldRefreshDetail({ force = false, eventCount = 0, hasDetail = false }) {
  return force || eventCount > 0 || !hasDetail;
}

export function nextDetailDelay(status, failures = 0, hidden = false) {
  if (TERMINAL_STATUSES.has(status)) return null;
  let base = 800;
  if (status === "queued") base = 1500;
  if (status === "review_required") base = 5000;
  const backedOff = Math.min(15000, base * (2 ** Math.min(failures, 4)));
  return hidden ? Math.max(5000, backedOff * 4) : backedOff;
}

export function nextListDelay(runs, failures = 0, hidden = false) {
  const hasActive = runs.some((run) => ACTIVE_STATUSES.has(run.status));
  const base = hasActive ? 2000 : 10000;
  const backedOff = Math.min(30000, base * (2 ** Math.min(failures, 3)));
  return hidden ? Math.max(30000, backedOff * 3) : backedOff;
}

export async function requestJson(fetcher, url, options = {}) {
  const {
    headers = {}, signal: externalSignal, timeoutMs = 8000, ...requestOptions
  } = options;
  const controller = new AbortController();
  let timedOut = false;
  const onExternalAbort = () => controller.abort();
  if (externalSignal?.aborted) controller.abort();
  externalSignal?.addEventListener("abort", onExternalAbort, { once: true });
  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    const response = await fetcher(url, {
      ...requestOptions,
      headers: { Accept: "application/json", ...headers },
      signal: controller.signal,
    });
    if (response.status === 304) return { response, body: null };
    let body;
    try {
      body = await response.json();
    } catch {
      throw new Error(`${response.status}: response was not JSON`);
    }
    if (!response.ok) {
      throw new Error(`${response.status}: ${body.detail || body.code || "request failed"}`);
    }
    return { response, body };
  } catch (error) {
    if (timedOut) throw new RequestTimeoutError(timeoutMs);
    throw error;
  } finally {
    clearTimeout(timeout);
    externalSignal?.removeEventListener("abort", onExternalAbort);
  }
}
