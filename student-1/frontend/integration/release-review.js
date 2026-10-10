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
    onRunChange: (run) => { if (run?.id) onRunChange(run); },
  });
  return Object.freeze({
    host,
    releaseId: release.id,
    focus: () => panel.focus(),
    get run() { return panel.run; },
    destroy: () => panel.destroy(),
  });
}
