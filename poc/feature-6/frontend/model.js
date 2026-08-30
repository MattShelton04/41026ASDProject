export const ROUTES = Object.freeze([
  "readiness",
  "property",
  "market",
  "place",
  "site",
  "buyer",
  "friction",
]);

export function routeName(hash = "") {
  const candidate = String(hash).replace(/^#/, "").split("?", 1)[0];
  return ROUTES.includes(candidate) ? candidate : "readiness";
}

export function listItems(payload) {
  if (Array.isArray(payload)) return payload;
  return Array.isArray(payload?.items) ? payload.items : [];
}

export function formatCurrency(value) {
  if (value === null || value === undefined || value === "") return "Unavailable";
  const number = Number(value);
  if (!Number.isFinite(number)) return "Unavailable";
  return new Intl.NumberFormat("en-AU", {
    style: "currency",
    currency: "AUD",
    maximumFractionDigits: 0,
  }).format(number);
}

export function evidenceState(section) {
  const state = String(section?.state || section?.status || "unavailable");
  if (["complete", "confirmed", "partial", "needs_verification"].includes(state)) return state;
  return "unavailable";
}

export function evidenceLabel(state) {
  return String(state || "unavailable").replaceAll("_", " ");
}
