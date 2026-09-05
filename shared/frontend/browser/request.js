/** Abort/timeout lifecycle. The operation must include consuming the response body. */
export class RequestTimeoutError extends Error {
  constructor(timeoutMs, options = {}) {
    super(`Request timed out after ${timeoutMs} ms`, options);
    this.name = "RequestTimeoutError";
    this.timeoutMs = timeoutMs;
  }
}

export async function withRequestLifecycle(operation, { signal = null, signals = [], timeoutMs = 0 } = {}) {
  const controller = new AbortController();
  const sources = [...new Set([signal, ...signals].filter(Boolean))];
  const listeners = new Map();
  let timer;
  let onAbort;
  let timedOut = false;
  try {
    for (const source of sources) {
      if (source.aborted) {
        controller.abort(source.reason);
        break;
      }
      const listener = () => controller.abort(source.reason);
      source.addEventListener("abort", listener, { once: true });
      listeners.set(source, listener);
    }
    controller.signal.throwIfAborted();
    const aborted = new Promise((_, reject) => {
      onAbort = () => reject(controller.signal.reason);
      controller.signal.addEventListener("abort", onAbort, { once: true });
    });
    if (Number.isFinite(timeoutMs) && timeoutMs > 0) {
      timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeoutMs);
    }
    // The rejection handler also observes an operation that ignores cancellation and rejects later.
    return await Promise.race([operation(controller.signal), aborted]);
  } catch (error) {
    if (timedOut) throw new RequestTimeoutError(timeoutMs, { cause: error });
    throw error;
  } finally {
    clearTimeout(timer);
    if (onAbort) controller.signal.removeEventListener("abort", onAbort);
    for (const [source, listener] of listeners) source.removeEventListener("abort", listener);
  }
}
