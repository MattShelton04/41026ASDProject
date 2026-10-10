import assert from "node:assert/strict";
import test from "node:test";
import {
  createReleaseReadinessReview,
  READINESS_REVIEW_STATUSES,
  RELEASE_REVIEW_API_ROOT,
  readinessReviewHash,
  readinessReviewInput,
  readinessReviewRunId,
} from "../../frontend/integration/release-review.js";

const RELEASE_ID = "36460dde-c3fe-4ca4-8e5e-f3c12c645bcd";
const RUN_ID = "c17c66cc-6b40-4685-909a-440401ae8ec7";

function documentDouble() {
  const node = (tag) => ({
    tag, className: "", id: "", attributes: {}, children: [],
    setAttribute(name, value) { this.attributes[name] = value; },
    append(...items) { this.children.push(...items); },
  });
  return { createElement: node };
}

test("only a canonical run ID in the release hash reopens a recorded review", () => {
  assert.equal(readinessReviewRunId(`#releases/${RELEASE_ID}?review=${RUN_ID.toUpperCase()}`), RUN_ID);
  assert.equal(readinessReviewRunId(`#releases/${RELEASE_ID}`), null);
  assert.equal(readinessReviewRunId(`#releases/${RELEASE_ID}?review=../agent-runs`), null);
  assert.equal(readinessReviewHash(RELEASE_ID, RUN_ID), `#releases/${RELEASE_ID}?review=${RUN_ID}`);
  assert.equal(readinessReviewHash(RELEASE_ID, "not-a-run"), `#releases/${RELEASE_ID}`);
});

test("the page supplies the exact release and a bounded dataset identifier", () => {
  assert.deepEqual(readinessReviewInput({ id: RELEASE_ID, dataset_id: "nsw-amenities" }), { release_id: RELEASE_ID, dataset_id: "nsw-amenities" });
  assert.deepEqual(readinessReviewInput({ id: RELEASE_ID }), { release_id: RELEASE_ID });
  assert.equal(readinessReviewInput({ id: RELEASE_ID, dataset_id: "x".repeat(400) }).dataset_id.length, 150);
  assert.ok(READINESS_REVIEW_STATUSES.has("awaiting_review"));
  assert.ok(!READINESS_REVIEW_STATUSES.has("accepted"));
});

test("the readiness review mounts the shared panel against the feature proxy only", () => {
  const calls = {};
  const changes = [];
  let destroyed = false;
  const review = createReleaseReadinessReview({
    release: { id: RELEASE_ID, dataset_id: "nsw-amenities", status: "awaiting_review" },
    runId: RUN_ID,
    announce: () => {},
    onRunChange: (run) => changes.push(run.id),
    document: documentDouble(),
    createClient: (options) => { calls.client = options; return { destroy() {} }; },
    createPanel: (options) => {
      calls.panel = options;
      return { run: { id: RUN_ID }, focus() { calls.focused = true; }, destroy() { destroyed = true; } };
    },
  });
  assert.deepEqual(calls.client, { apiRoot: RELEASE_REVIEW_API_ROOT });
  assert.equal(calls.panel.root, review.host.children[0]);
  assert.deepEqual(calls.panel.hiddenInputs, ["release_id", "dataset_id"]);
  assert.deepEqual(calls.panel.initialInput, { release_id: RELEASE_ID, dataset_id: "nsw-amenities" });
  assert.equal(calls.panel.runId, RUN_ID);
  assert.equal(calls.panel.requestedBy, "property-data-release-review");
  assert.match(calls.panel.description, /Publishing stays the separate Publish action/);
  assert.match(calls.panel.labels.decisionSafety, /never publishes the release/);
  assert.match(calls.panel.labels.outcomeSafety, /did not publish the release/);
  calls.panel.onRunChange({ id: RUN_ID, state: "awaiting_human" });
  calls.panel.onRunChange(null);
  assert.deepEqual(changes, [RUN_ID]);
  assert.equal(review.releaseId, RELEASE_ID);
  assert.equal(review.run.id, RUN_ID);
  review.focus();
  assert.equal(calls.focused, true);
  review.destroy();
  assert.equal(destroyed, true);
});
