/** Build the audit handoff from the document's actual asset base, not an assumed origin. */
export function propertyActivityUrl(runId = "", {
  baseUrl,
  activityUrl = "",
  returnTo = "/features/data-platform/#properties",
} = {}) {
  const current = new URL(baseUrl);
  const integrated = current.pathname.startsWith("/features/data-platform/");
  const root = activityUrl || (integrated ? "/operations/ai-mode/"
    : `${current.protocol}//${current.hostname}:5100/operations/ai-mode/`);
  const url = new URL(root, current);
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new TypeError("Activity URL must use HTTP or HTTPS");
  }
  url.searchParams.set("feature_key", "student-1-propertyscope-data-platform");
  url.searchParams.set("feature_label", "Property data");
  url.searchParams.set("return_to", returnTo);
  if (runId) url.searchParams.set("run", runId);
  return url.href;
}
