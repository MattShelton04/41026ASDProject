/** Feature-owned mount of the Shared multi-agent panel for one saved suburb comparison. */
import { createMultiAgentClient, createMultiAgentPanel } from "../multi-agent/index.js";

export const COMPARISON_REVIEW_API_ROOT = "/api/suburb-analytics/v1/comparison-reviews";
export const COMPARISON_REVIEW_CAPABILITIES_PATH = "/comparison-reviews/capabilities";
export const COMPARISON_REVIEW_REQUESTER = "suburb-analytics-comparison-review";
export const COMPARISON_REVIEW_STORAGE_KEY = "propertyscope:comparison-reviews";
export const COMPARISON_REVIEW_MEMORY_LIMIT = 20;

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function browserStorage() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

function readMemory(storage) {
  try {
    const value = JSON.parse(storage?.getItem(COMPARISON_REVIEW_STORAGE_KEY) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}

function writeMemory(storage, memory) {
  try { storage?.setItem(COMPARISON_REVIEW_STORAGE_KEY, JSON.stringify(memory)); } catch { /* Optional. */ }
}

export function rememberedComparisonReview(comparisonId, storage = browserStorage()) {
  const value = readMemory(storage)[String(comparisonId)];
  return typeof value === "string" && RUN_ID.test(value) ? value.toLowerCase() : null;
}

export function rememberComparisonReview(comparisonId, runId, storage = browserStorage()) {
  if (!comparisonId || !RUN_ID.test(String(runId || ""))) return;
  const memory = readMemory(storage);
  delete memory[comparisonId];
  memory[comparisonId] = String(runId).toLowerCase();
  writeMemory(storage, Object.fromEntries(Object.entries(memory).slice(-COMPARISON_REVIEW_MEMORY_LIMIT)));
}

export function forgetComparisonReview(comparisonId, runId, storage = browserStorage()) {
  const memory = readMemory(storage);
  if (memory[comparisonId] !== runId) return;
  delete memory[comparisonId];
  writeMemory(storage, memory);
}

export async function comparisonReviewEnabled({ request }) {
  try {
    const body = await request(COMPARISON_REVIEW_CAPABILITIES_PATH);
    return body?.comparison_review?.enabled === true;
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    return false;
  }
}

export async function resumableComparisonReview(comparisonId, { request, storage = browserStorage() }) {
  const runId = rememberedComparisonReview(comparisonId, storage);
  if (!runId) return null;
  try {
    const body = await request(`/comparison-reviews/${encodeURIComponent(runId)}`);
    if (String(body?.input?.suburb_comparison_id || "") === String(comparisonId)) return runId;
    forgetComparisonReview(comparisonId, runId, storage);
    return null;
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    if (error?.status === 404) forgetComparisonReview(comparisonId, runId, storage);
    return null;
  }
}

export const COMPARISON_REVIEW_LABELS = Object.freeze({
  start: "Review this comparison",
  decisionSafety:
    "This records your decision. It never changes the saved comparison, its localities or its evidence.",
  outcomeSafety:
    "Recording a decision did not change the saved comparison. Editing it remains a separate action.",
});

export function mountComparisonReview({ root, comparisonId, comparisonName = "", actor = "", runId = null, announce, onRunChange = () => {}, storage = browserStorage() } = {}) {
  if (!root) throw new TypeError("mountComparisonReview requires root");
  if (!comparisonId) throw new TypeError("mountComparisonReview requires comparisonId");
  const client = createMultiAgentClient({ apiRoot: COMPARISON_REVIEW_API_ROOT });
  return createMultiAgentPanel({
    root,
    client,
    initialInput: { suburb_comparison_id: comparisonId },
    hiddenInputs: ["suburb_comparison_id"],
    runId,
    actor,
    title: comparisonName ? `Evidence review: ${comparisonName}` : "",
    requestedBy: COMPARISON_REVIEW_REQUESTER,
    labels: COMPARISON_REVIEW_LABELS,
    announce,
    onRunChange: (run) => {
      if (!run?.id) return;
      rememberComparisonReview(comparisonId, run.id, storage);
      onRunChange(run);
    },
  });
}
