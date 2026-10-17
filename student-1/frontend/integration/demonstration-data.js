/** A quiet page notice while every published dataset is still the seeded demonstration baseline. */
import { collection } from "../core/api.js";

// Accepted releases only, summarised: the seeded baseline is marked `coverage_json.synthetic`.
export const DEMONSTRATION_BASELINE_PATH = "dataset-releases?lifecycle=published&view=summary&limit=100";
export const DEMONSTRATION_BASELINE_MESSAGE = "Demonstration data. Every published dataset here is the seeded demonstration baseline: a small set of synthetic records, not complete NSW publisher data.";
// Pages that present published data to a reader.
export const DEMONSTRATION_NOTICE_ROUTES = Object.freeze(new Set(["overview", "properties", "data-products", "coverage"]));
export const DEMONSTRATION_CHECK_INTERVAL_MS = 60_000;

/** Active only when there is published data and all of it is the seeded baseline. */
export function demonstrationBaseline(releases = []) {
  const accepted = releases.filter((release) => release?.status === "accepted");
  const seeded = accepted.filter((release) => release.coverage_json?.synthetic === true);
  return Object.freeze({
    active: accepted.length > 0 && seeded.length === accepted.length,
    accepted: accepted.length,
    seeded: seeded.length,
  });
}

/**
 * Mount the notice once before `#view` and call `update(route)` after each route change. The
 * published-release summary is re-read at most once a minute; a failed read hides the notice.
 */
export function createDemonstrationNotice({
  request,
  document: doc = globalThis.document,
  now = () => Date.now(),
  intervalMs = DEMONSTRATION_CHECK_INTERVAL_MS,
}) {
  const element = doc.createElement("p");
  element.className = "notice info demonstration-baseline";
  element.id = "demonstration-baseline-notice";
  element.setAttribute("role", "note");
  element.hidden = true;
  element.textContent = DEMONSTRATION_BASELINE_MESSAGE;
  let cached = null;
  let generation = 0;

  function baseline() {
    if (cached && now() - cached.at < intervalMs) return cached.promise;
    const entry = { at: now(), promise: null };
    entry.promise = request(DEMONSTRATION_BASELINE_PATH, { timeoutMs: 4000 }).then(
      ({ body }) => demonstrationBaseline(collection(body)),
      () => {
        if (cached === entry) cached = null;
        return null;
      },
    );
    cached = entry;
    return entry.promise;
  }

  async function update(route) {
    const current = ++generation;
    if (!DEMONSTRATION_NOTICE_ROUTES.has(route)) {
      element.hidden = true;
      return;
    }
    const state = await baseline();
    if (current !== generation) return;
    element.hidden = !state?.active;
  }

  return Object.freeze({ element, update });
}
