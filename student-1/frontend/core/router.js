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
