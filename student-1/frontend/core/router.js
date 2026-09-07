export const ROUTES = new Set(["overview", "data-products", "sources", "jobs", "runs", "releases", "quality", "artifacts", "coverage", "properties", "assistant", "ai"]);

export function parseRoute(hash = "") {
  const raw = String(hash).replace(/^#/, "") || "properties";
  const path = raw.split("?")[0];
  let decoded;
  try { decoded = path.split("/").map(decodeURIComponent); }
  catch { return { route: "properties", id: "", action: "" }; }
  const [candidate, id, action] = decoded;
  return { route: ROUTES.has(candidate) ? candidate : "properties", id: id || "", action: action || "" };
}

export function routeQuery(hash = "") {
  return new URLSearchParams(String(hash).split("?")[1] || "");
}

/** Optional navigation memory must never prevent the actual data request. */
export function readHistoryState(browser = globalThis) {
  try {
    const state = browser.history?.state;
    return state && typeof state === "object" ? state : {};
  } catch { return {}; }
}

export function replaceHistoryState(state, url, browser = globalThis) {
  try {
    if (!browser.history?.replaceState) return false;
    browser.history.replaceState(state, "", url);
    return true;
  } catch { return false; }
}
