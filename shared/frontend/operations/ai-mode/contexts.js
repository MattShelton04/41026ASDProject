/** Bounded metadata for feature-owned transitions into the Shared activity view. */

const CONTEXTS = Object.freeze({
  "student-1-propertyscope-data-platform": Object.freeze({
    key: "student-1-propertyscope-data-platform",
    label: "Property data",
    returnTo: "/features/data-platform/#properties",
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
  if (!context || label !== context.label || returnTo !== context.returnTo) return null;
  return context;
}
