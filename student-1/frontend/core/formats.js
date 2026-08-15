import { collection } from "./api.js";
import { ACTIVE_RUN_STATES } from "./polling.js";

export function humanise(value) {
  if (value === null || value === undefined || value === "") return "Not recorded";
  return String(value).replaceAll("_", " ").replace(/\b\w/g, (character) => character.toUpperCase());
}

export function formatNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? new Intl.NumberFormat("en-AU").format(number) : "—";
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

export function statusTone(status) {
  const value = String(status || "unknown").toLowerCase();
  if (["accepted", "succeeded", "pass", "passed", "active", "available", "supported", "complete", "completed", "healthy", "published", "observed", "confirmed"].includes(value)) return "positive";
  if (["failed", "rejected", "blocked", "unavailable", "cancelled", "error", "unhealthy", "source_failed"].includes(value)) return "negative";
  if (["partial", "warning", "warn", "stale", "candidate", "review", "review_required", "awaiting_review", "cancelling", "conflicting"].includes(value)) return "warning";
  if (ACTIVE_RUN_STATES.has(value) || ["draft", "pending"].includes(value)) return "info";
  return "neutral";
}

export function stateLabel(status) {
  const symbols = { positive: "✓", negative: "!", warning: "△", info: "↻", neutral: "•" };
  const tone = statusTone(status);
  return { text: humanise(status || "Unknown"), tone, symbol: symbols[tone] };
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
