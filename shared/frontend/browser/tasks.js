/** Small lifecycle primitives; feature owners define domain states and renderers. */
import { withRequestLifecycle } from "./request.js";

export function abortableDelay(milliseconds, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(signal.reason); return; }
    const abort = () => { clearTimeout(timer); reject(signal.reason); };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", abort);
      resolve();
    }, milliseconds);
    signal?.addEventListener("abort", abort, { once: true });
  });
}

/** Starting another task invalidates both its network work and its render permission. */
export function createLatestTask() {
  let controller = null;
  return {
    cancel() { controller?.abort(); controller = null; },
    start() {
      controller?.abort();
      const current = new AbortController();
      controller = current;
      return {
        signal: current.signal,
        isCurrent: () => controller === current && !current.signal.aborted,
        delay: (milliseconds) => abortableDelay(milliseconds, current.signal),
      };
    },
  };
}

/** No automatic mutation retries. Read-only polling stops on a deadline or owner exit. */
export async function pollUntilSettled(read, {
  task, initial = null, isSettled, onUpdate = () => {},
  intervalMs = 1000, timeoutMs = 120000, maxAttempts = 120,
}) {
  if (!Number.isInteger(maxAttempts) || maxAttempts < 1) throw new RangeError("maxAttempts must be positive.");
  return withRequestLifecycle(async (signal) => {
    if (initial && isSettled(initial)) return initial;
    for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
      signal.throwIfAborted();
      const result = await read(signal);
      signal.throwIfAborted();
      if (!task.isCurrent()) return null;
      onUpdate(result);
      if (isSettled(result)) return result;
      await abortableDelay(intervalMs, signal);
    }
    throw new Error("The run is still active after the polling limit.");
  }, { signal: task.signal, timeoutMs });
}
