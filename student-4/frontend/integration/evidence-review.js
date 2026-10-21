/** Feature-owned mount of the Shared multi-agent panel for one saved site review. */
import { createMultiAgentClient, createMultiAgentPanel } from "../multi-agent/index.js";

export const EVIDENCE_REVIEW_API_ROOT = "/api/due-diligence/v1/evidence-reviews";
// Runs record which surface asked for them; each human decision records its own actor.
export const EVIDENCE_REVIEW_REQUESTER = "due-diligence-evidence-review";
export const EVIDENCE_REVIEW_CAPABILITIES_PATH = "/evidence-reviews/capabilities";

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// The latest review started for each site review, so leaving the page does not lose a running
// workflow. Browser storage is a per-viewer convenience only: the Multi-Agent Server stays the
// record.
export const EVIDENCE_REVIEW_STORAGE_KEY = "propertyscope:evidence-reviews";
export const EVIDENCE_REVIEW_MEMORY_LIMIT = 20;

function browserStorage() {
  try { return globalThis.localStorage ?? null; } catch { return null; }
}

function readMemory(storage) {
  try {
    const value = JSON.parse(storage?.getItem(EVIDENCE_REVIEW_STORAGE_KEY) || "{}");
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  } catch { return {}; }
}

function writeMemory(storage, memory) {
  try { storage?.setItem(EVIDENCE_REVIEW_STORAGE_KEY, JSON.stringify(memory)); } catch { /* Storage is optional. */ }
}

export function rememberedEvidenceReview(siteReviewId, storage = browserStorage()) {
  const value = readMemory(storage)[String(siteReviewId)];
  return typeof value === "string" && RUN_ID.test(value) ? value.toLowerCase() : null;
}

export function rememberEvidenceReview(siteReviewId, runId, storage = browserStorage()) {
  if (!siteReviewId || !RUN_ID.test(String(runId || ""))) return;
  const memory = readMemory(storage);
  delete memory[siteReviewId];
  memory[siteReviewId] = String(runId).toLowerCase();
  // Insertion order is recency order; keep only the newest reviews.
  writeMemory(storage, Object.fromEntries(Object.entries(memory).slice(-EVIDENCE_REVIEW_MEMORY_LIMIT)));
}

export function forgetEvidenceReview(siteReviewId, runId, storage = browserStorage()) {
  const memory = readMemory(storage);
  if (memory[siteReviewId] !== runId) return;
  delete memory[siteReviewId];
  writeMemory(storage, memory);
}

/**
 * The run to reopen for this site review, checked through the feature proxy first: a run the
 * server no longer has, or one belonging to another review, is forgotten instead of opening as an
 * error. When the server cannot answer, nothing is reopened and the memory is kept for next time.
 */
export async function resumableEvidenceReview(siteReviewId, { request, storage = browserStorage() }) {
  const runId = rememberedEvidenceReview(siteReviewId, storage);
  if (!runId) return null;
  try {
    const body = await request(`/evidence-reviews/${encodeURIComponent(runId)}`);
    if (String(body?.input?.site_review_id || "").toLowerCase() === String(siteReviewId).toLowerCase()) return runId;
    forgetEvidenceReview(siteReviewId, runId, storage);
    return null;
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    // The proxy answers 404 for a deleted run and for one that is not this feature's review.
    if (error?.status === 404) forgetEvidenceReview(siteReviewId, runId, storage);
    return null;
  }
}

/**
 * Whether this deployment enables evidence readiness reviews, asked before the panel is mounted.
 *
 * The Multi-Agent Server is a host process, so a Compose-only stack - CI's visual capture and
 * the cloud baseline with the AI tier off - has no server to reach. Asking first keeps the page
 * quiet there and tells the reader why the card is empty. Anything other than a clear "enabled"
 * counts as disabled, including a deployment too old to publish this route.
 */
export async function evidenceReviewEnabled({ request }) {
  try {
    const body = await request(EVIDENCE_REVIEW_CAPABILITIES_PATH);
    return body?.evidence_review?.enabled === true;
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    return false;
  }
}

export const EVIDENCE_REVIEW_LABELS = Object.freeze({
  start: "Review evidence readiness",
  // Deciding records an answer to the agents. It never edits the site review or its evidence.
  decisionSafety:
    "This records your decision. It never changes the saved site review, its checklist or its saved questions.",
  outcomeSafety:
    "Recording a decision did not change the site review. Saving questions stays a separate action on this page.",
});

/**
 * Mount the evidence readiness panel for one site review.
 *
 * A panel belongs to the review it was created for: the Release 1 review-scoping rule carries
 * over, so opening another review destroys this panel and mounts a new one rather than
 * re-pointing it. The caller owns teardown through the returned handle.
 */
export function mountEvidenceReview({
  root,
  siteReviewId,
  reviewLabel = "",
  actor = "",
  runId = null,
  announce,
  onRunChange = () => {},
  storage = browserStorage(),
} = {}) {
  if (!root) throw new TypeError("mountEvidenceReview requires root");
  if (!siteReviewId) throw new TypeError("mountEvidenceReview requires siteReviewId");

  const client = createMultiAgentClient({ apiRoot: EVIDENCE_REVIEW_API_ROOT });
  return createMultiAgentPanel({
    root,
    client,
    // The review is supplied by the page, so it is submitted and listed but never editable: a
    // workflow must not be started for a review other than the one on screen.
    initialInput: { site_review_id: siteReviewId },
    hiddenInputs: ["site_review_id"],
    runId,
    actor,
    title: reviewLabel ? `Evidence readiness: ${reviewLabel}` : "",
    requestedBy: EVIDENCE_REVIEW_REQUESTER,
    labels: EVIDENCE_REVIEW_LABELS,
    announce,
    onRunChange: (run) => {
      if (!run?.id) return;
      rememberEvidenceReview(siteReviewId, run.id, storage);
      onRunChange(run);
    },
  });
}
