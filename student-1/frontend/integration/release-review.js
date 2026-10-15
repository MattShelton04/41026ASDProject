/** Feature-owned mount of the Shared multi-agent panel for one candidate release's readiness review. */
import { createMultiAgentClient, createMultiAgentPanel } from "../multi-agent/index.js";

export const RELEASE_REVIEW_API_ROOT = "/api/data-platform/v1/release-reviews";
// Runs record which surface asked for them; each human decision records its own actor.
export const READINESS_REVIEW_REQUESTER = "property-data-release-review";
export const READINESS_REVIEW_STATUSES = Object.freeze(new Set(["validated", "candidate", "review", "review_required", "awaiting_review"]));

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const READINESS_REVIEW_LABELS = Object.freeze({
  start: "Start readiness review",
  // Deciding records an answer to the agents; it never publishes the release.
  decisionSafety: "This records your decision. It never publishes the release; Publish stays a separate action on this page.",
  outcomeSafety: "Recording a decision did not publish the release. Publish stays a separate action on this page.",
});

/** The recorded run to reopen, from `#releases/{id}?review={run_id}`; anything else is ignored. */
export function readinessReviewRunId(hash = "") {
  const value = new URLSearchParams(String(hash).split("?")[1] || "").get("review") || "";
  return RUN_ID.test(value) ? value.toLowerCase() : null;
}

export function readinessReviewHash(releaseId, runId = null) {
  const base = `#releases/${encodeURIComponent(releaseId)}`;
  return runId && RUN_ID.test(runId) ? `${base}?review=${runId}` : base;
}

// The latest review started for each release, so leaving the page does not lose a running review.
// Browser storage is a per-viewer convenience only: the Multi-Agent Server stays the record.
export const READINESS_REVIEW_STORAGE_KEY = "propertyscope:readiness-reviews";
export const READINESS_REVIEW_MEMORY_LIMIT = 20;

function browserStorage() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

function readMemory(storage) {
  try {
    const value = JSON.parse(storage?.getItem(READINESS_REVIEW_STORAGE_KEY) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}

function writeMemory(storage, memory) {
  try { storage?.setItem(READINESS_REVIEW_STORAGE_KEY, JSON.stringify(memory)); } catch { /* Storage is optional. */ }
}

export function rememberedReadinessReview(releaseId, storage = browserStorage()) {
  const value = readMemory(storage)[String(releaseId)];
  return typeof value === "string" && RUN_ID.test(value) ? value.toLowerCase() : null;
}

export function rememberReadinessReview(releaseId, runId, storage = browserStorage()) {
  if (!releaseId || !RUN_ID.test(String(runId || ""))) return;
  const memory = readMemory(storage);
  delete memory[releaseId];
  memory[releaseId] = String(runId).toLowerCase();
  // Insertion order is recency order; keep only the newest releases.
  const kept = Object.entries(memory).slice(-READINESS_REVIEW_MEMORY_LIMIT);
  writeMemory(storage, Object.fromEntries(kept));
}

export function forgetReadinessReview(releaseId, runId, storage = browserStorage()) {
  const memory = readMemory(storage);
  if (memory[releaseId] !== runId) return;
  delete memory[releaseId];
  writeMemory(storage, memory);
}

/**
 * The remembered review to reopen for this release, checked through the feature proxy first: a run
 * the server no longer has, or one for another release, is forgotten instead of opening as an error.
 * When the server cannot answer, nothing is reopened and the memory is kept for next time.
 */
export async function resumableReadinessReview(release, { request, storage = browserStorage() }) {
  const runId = rememberedReadinessReview(release.id, storage);
  if (!runId) return null;
  try {
    const { body } = await request(`release-reviews/${encodeURIComponent(runId)}`);
    if (String(body?.input?.release_id || "").toLowerCase() === String(release.id).toLowerCase()) return runId;
    forgetReadinessReview(release.id, runId, storage);
    return null;
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    if (error?.status === 404) forgetReadinessReview(release.id, runId, storage);
    return null;
  }
}

/** Template inputs supplied by the page: the exact release and its dataset narrow the queue step. */
export function readinessReviewInput(release) {
  return {
    release_id: release.id,
    ...(release.dataset_id ? { dataset_id: String(release.dataset_id).slice(0, 150) } : {}),
  };
}

/**
 * Mount one panel for one release. The human decides on the agents' recommendation only;
 * publishing remains the page's separate Publish action.
 */
export function createReleaseReadinessReview({
  release,
  runId = null,
  announce,
  onRunChange = () => {},
  storage = browserStorage(),
  document: doc = globalThis.document,
  createClient = createMultiAgentClient,
  createPanel = createMultiAgentPanel,
}) {
  const host = doc.createElement("section");
  host.className = "panel release-readiness-review";
  host.id = "release-readiness-review";
  host.setAttribute("aria-label", "Readiness review");
  const root = doc.createElement("div");
  root.className = "panel-body";
  host.append(root);
  const panel = createPanel({
    root,
    client: createClient({ apiRoot: RELEASE_REVIEW_API_ROOT }),
    initialInput: readinessReviewInput(release),
    hiddenInputs: ["release_id", "dataset_id"],
    requestedBy: READINESS_REVIEW_REQUESTER,
    runId,
    announce,
    title: "Readiness review",
    description: "A Planner, Worker and Reviewer read evidence about this exact version and suggest whether it is ready to publish. You decide. Publishing stays the separate Publish action on this page.",
    labels: READINESS_REVIEW_LABELS,
    onRunChange: (run) => {
      if (!run?.id) return;
      rememberReadinessReview(release.id, run.id, storage);
      onRunChange(run);
    },
  });
  return Object.freeze({
    host,
    releaseId: release.id,
    focus: () => panel.focus(),
    get run() { return panel.run; },
    destroy: () => panel.destroy(),
  });
}
