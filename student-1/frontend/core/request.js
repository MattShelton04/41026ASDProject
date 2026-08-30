/** Abort and timeout lifecycle for the independently deployed Feature 1 frontend. */

export class RequestTimeoutError extends Error {
  constructor(timeoutMs, options = {}) {
    super(`Request timed out after ${timeoutMs} ms`, options);
    this.name = "RequestTimeoutError";
    this.timeoutMs = timeoutMs;
  }
}

function abortSources(signal, signals) {
  return [signal, ...(signals || [])].filter(Boolean);
}

export async function withRequestLifecycle(
  operation,
  { signal = null, signals = [], timeoutMs = 0 } = {},
) {
  const controller = new AbortController();
  const sources = abortSources(signal, signals);
  let timedOut = false;
  const listeners = new Map();

  for (const source of sources) {
    if (source.aborted) {
      controller.abort(source.reason);
      break;
    }
    const listener = () => controller.abort(source.reason);
    source.addEventListener("abort", listener, { once: true });
    listeners.set(source, listener);
  }

  const timeout = Number.isFinite(timeoutMs) && timeoutMs > 0
    ? setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, timeoutMs)
    : null;

  try {
    return await operation(controller.signal);
  } catch (error) {
    if (timedOut) throw new RequestTimeoutError(timeoutMs, { cause: error });
    throw error;
  } finally {
    if (timeout !== null) clearTimeout(timeout);
    for (const [source, listener] of listeners) source.removeEventListener("abort", listener);
  }
}

