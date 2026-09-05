/** Stable public JavaScript surface for domain-neutral browser helpers. */

export { append, el, escapeHtml } from "./dom.js";
export {
  createDrawerController,
  createTableRegion,
  createToastController,
  disposeTableRegions,
} from "./interactions.js";
export { RequestTimeoutError, withRequestLifecycle } from "./request.js";

export { HttpProblem, createJsonClient, newRequestId, requestJsonResponse } from "./http.js";
export { abortableDelay, createLatestTask, pollUntilSettled } from "./tasks.js";
export { initialiseFeatureShell, mountFeatureShell, resolveProductHome } from "./shell.js";
