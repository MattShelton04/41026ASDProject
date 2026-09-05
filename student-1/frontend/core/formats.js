import { collection } from "./api.js";
import { ACTIVE_RUN_STATES } from "./polling.js";

const PRODUCT_LABELS = Object.freeze({
  "deterministic property critical-path fixture": "Example property records update",
  "deterministic property fixture full refresh": "Example property records update",
  "deterministic synthetic property snapshot": "Example NSW property records",
  "fixture-property": "Example property records",
  "fixture-property-full": "Example property update profile",
  "fixture-snapshot": "Example data source",
  "fixture backed": "Example data",
  "fixture_backed": "Example data",
  "full_refresh": "Replace current data",
  "reprocess_cached": "Recheck downloaded data",
  "backfill": "Load earlier data",
  "candidate": "Ready for review",
  "accepted": "Published",
  "superseded": "Replaced",
  "nsw-psi-sales": "NSW property sales",
  "bocsar-crime": "NSW recorded crime",
  "nsw-government-schools": "NSW government schools",
  "gnaf-nsw": "NSW address records",
  "abs-seifa-2021": "ABS SEIFA 2021",
  "abs-seifa-2021-sal-nsw": "ABS SEIFA 2021 NSW areas",
});

export function displayName(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return PRODUCT_LABELS[String(value).toLowerCase()] || String(value);
}

export function humanise(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  const knownLabel = PRODUCT_LABELS[String(value).toLowerCase()];
  if (knownLabel) return knownLabel;
  const words = String(value).replaceAll("_", " ").replaceAll("-", " ");
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`;
}

export function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("en-AU").format(number) : "—";
}

export function confidenceLabel(value) {
  if (value === null || value === undefined || value === "") return "Match confidence not supplied";
  const score = Number(value);
  if (!Number.isFinite(score)) return "Match confidence not supplied";
  const percentage = Math.round(Math.max(0, Math.min(1, score)) * 100);
  const strength = score >= 0.9 ? "Very strong" : score >= 0.75 ? "Strong" : score >= 0.5 ? "Possible" : "Broad";
  return `${strength} match (${percentage}%)`;
}

export function formatBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes)) return "—";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes;
  let unit = -1;
  do { size /= 1024; unit += 1; } while (size >= 1024 && unit < units.length - 1);
  return `${size.toFixed(size >= 10 ? 1 : 2)} ${units[unit]}`;
}

export function formatDate(value) {
  if (!value) return "Not recorded";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? String(value) : new Intl.DateTimeFormat("en-AU", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function durationMilliseconds(start, end = Date.now()) {
  if (start === null || start === undefined || start === "") return null;
  const started = new Date(start).valueOf();
  const finished = end instanceof Date ? end.valueOf() : new Date(end).valueOf();
  if (!Number.isFinite(started) || !Number.isFinite(finished)) return null;
  return Math.max(0, finished - started);
}

export function formatDuration(start, end = Date.now()) {
  const milliseconds = durationMilliseconds(start, end);
  if (milliseconds === null) return "Not recorded";
  const seconds = Math.round(milliseconds / 1000);
  if (seconds < 1) return "less than 1s";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  if (minutes < 60) return `${minutes}m ${remainingSeconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}

export function statusTone(status) {
  if (status === "publishing") return "info";
  if (status === "publication_failed") return "negative";
  const value = String(status || "unknown").toLowerCase();
  if (["accepted", "succeeded", "pass", "passed", "active", "available", "supported", "complete", "completed", "healthy", "published", "observed", "confirmed", "verified", "imported", "delivered", "unchanged"].includes(value)) return "positive";
  if (["failed", "rejected", "abandoned", "blocked", "unavailable", "cancelled", "error", "unhealthy", "source_failed"].includes(value)) return "negative";
  if (["partial", "warning", "warn", "stale", "candidate", "review", "review_required", "awaiting_review", "cancelling", "conflicting"].includes(value)) return "warning";
  if (ACTIVE_RUN_STATES.has(value) || ["draft", "pending"].includes(value)) return "info";
  return "neutral";
}

export function stateLabel(status) {
  const symbols = { positive: "✓", negative: "!", warning: "△", info: "↻", neutral: "•" };
  const tone = statusTone(status);
  return { text: humanise(status || "Unknown"), tone, symbol: symbols[tone] };
}

const RESEARCH_AREA_LABELS = Object.freeze({
  "feature-1": "Property data",
  "feature-2": "Sales & market",
  "feature-3": "Suburb context",
  "feature-4": "Site & planning",
  "feature-5": "Buyer workspace",
});

export function researchAreaLabel(value) {
  if (!value) return "Not assigned";
  return RESEARCH_AREA_LABELS[String(value).toLowerCase()] || humanise(value);
}

export function coverageRows(payload) {
  const direct = collection(payload);
  if (direct.length) return direct;
  const matrix = payload?.matrix || payload?.coverage || {};
  const rows = [];
  for (const [dataset, localities] of Object.entries(matrix)) {
    if (Array.isArray(localities)) {
      for (const item of localities) rows.push({ dataset, ...item });
    } else if (localities && typeof localities === "object") {
      for (const [locality, state] of Object.entries(localities)) rows.push({ dataset, locality, ...(typeof state === "object" ? state : { status: state }) });
    }
  }
  return rows;
}

export function releaseComparison(candidate, predecessor) {
  if (!candidate || !predecessor) return [];
  return [
    ["Schema version", candidate.schema_version, predecessor.schema_version],
    ["Record count", candidate.record_count, predecessor.record_count],
    ["Content checksum", candidate.content_sha256, predecessor.content_sha256],
    ["Coverage", candidate.coverage_json, predecessor.coverage_json],
  ].map(([field, candidateValue, predecessorValue]) => ({
    field,
    candidate: candidateValue,
    predecessor: predecessorValue,
    changed: JSON.stringify(candidateValue) !== JSON.stringify(predecessorValue),
  }));
}

export function reportReleaseRows(payload) {
  if (!payload || typeof payload !== "object") return [];
  return Array.isArray(payload.release_evidence) ? payload.release_evidence : [];
}
