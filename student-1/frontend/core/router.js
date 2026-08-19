export const ROUTES = new Set(["overview", "data-products", "sources", "jobs", "runs", "releases", "quality", "artifacts", "coverage", "properties", "ai"]);

export function parseRoute(hash = "") {
  const raw = String(hash).replace(/^#/, "") || "overview";
  const path = raw.split("?")[0];
  const [candidate, id, action] = path.split("/").map(decodeURIComponent);
  return { route: ROUTES.has(candidate) ? candidate : "overview", id: id || "", action: action || "" };
}

export function routeQuery(hash = "") {
  return new URLSearchParams(String(hash).split("?")[1] || "");
}
