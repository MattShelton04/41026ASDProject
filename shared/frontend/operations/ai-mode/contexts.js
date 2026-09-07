/** Bounded metadata for feature-owned transitions into the Shared activity view. */

const CONTEXTS = Object.freeze({
  "student-1-propertyscope-data-platform": Object.freeze({
    key: "student-1-propertyscope-data-platform",
    label: "Property data",
    returnTo: "/features/data-platform/#properties",
    returnPaths: Object.freeze([
      "/features/data-platform/#properties", "/features/data-platform/#assistant",
      "/features/data-platform/#ai", "/#assistant",
    ]),
    aliases: Object.freeze(["feature-1"]),
  }),
});

function safeLocalPath(value) {
  if (typeof value !== "string" || value.length > 160 || !value.startsWith("/") || value.startsWith("//")) return false;
  if (value.includes("\\") || /[\u0000-\u001f\u007f]/.test(value)) return false;
  const base = new URL("https://propertyscope.invalid/");
  const target = new URL(value, base);
  return target.origin === base.origin;
}

export function resolveResearchAreaContext(params) {
  const key = params.get("feature_key") || "";
  const label = params.get("feature_label") || "";
  const returnTo = params.get("return_to") || "";
  if (key.length > 100 || label.length > 80 || !safeLocalPath(returnTo)) return null;
  const context = CONTEXTS[key];
  if (!context || label !== context.label || !context.returnPaths.includes(returnTo)) return null;
  return Object.freeze({ ...context, returnTo });
}

/** Friendly labels do not grant a scope or authorise a return URL. */
const AREA_LABELS = Object.freeze({
  "student-1-propertyscope-data-platform": "Property data",
  "feature-1": "Property data",
  "student-2-market-intelligence": "Market intelligence",
  "feature-2": "Market intelligence",
  "student-3-suburb-analytics": "Suburb context",
  "feature-3": "Suburb context",
  "student-4-due-diligence": "Site due diligence",
  "feature-4": "Site due diligence",
  "student-5-buyer-journey": "Buyer workspaces",
  "feature-5": "Buyer workspaces"
});
export function activityAreaLabel(value) {
  return AREA_LABELS[value] || String(value || "Unknown area").replaceAll("_", " ").replaceAll("-", " ");
}
