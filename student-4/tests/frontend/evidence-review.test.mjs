import assert from "node:assert/strict";
import test from "node:test";

import {
  EVIDENCE_REVIEW_API_ROOT,
  EVIDENCE_REVIEW_CAPABILITIES_PATH,
  EVIDENCE_REVIEW_MEMORY_LIMIT,
  EVIDENCE_REVIEW_STORAGE_KEY,
  evidenceReviewEnabled,
  forgetEvidenceReview,
  mountEvidenceReview,
  rememberedEvidenceReview,
  rememberEvidenceReview,
  resumableEvidenceReview,
} from "../../frontend/integration/evidence-review.js";

const REVIEW_ID = "d4000000-0000-0000-0000-000000000001";
const OTHER_REVIEW_ID = "d4000000-0000-0000-0000-000000000002";
const RUN_ID = "68c410ca-cdd9-4268-bbaa-30de64d0b50c";

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, String(value)); },
  };
}

function brokenStorage() {
  return {
    getItem() { throw new Error("storage is blocked"); },
    setItem() { throw new Error("storage is blocked"); },
  };
}

function httpError(status) {
  return Object.assign(new Error(`status ${status}`), { status });
}

test("the proxy root is this feature's route, never the host server", () => {
  assert.equal(EVIDENCE_REVIEW_API_ROOT, "/api/due-diligence/v1/evidence-reviews");
});

test("the latest review for each site review is remembered, bounded and tolerant of broken storage", () => {
  const storage = memoryStorage();
  assert.equal(rememberedEvidenceReview(REVIEW_ID, storage), null);

  rememberEvidenceReview(REVIEW_ID, RUN_ID.toUpperCase(), storage);
  assert.equal(rememberedEvidenceReview(REVIEW_ID, storage), RUN_ID);

  // A value that is not a run identifier never replaces a good one.
  rememberEvidenceReview(REVIEW_ID, "not-a-run", storage);
  assert.equal(rememberedEvidenceReview(REVIEW_ID, storage), RUN_ID);

  for (let index = 0; index < EVIDENCE_REVIEW_MEMORY_LIMIT + 5; index += 1) {
    rememberEvidenceReview(`review-${index}`, RUN_ID, storage);
  }
  const kept = JSON.parse(storage.getItem(EVIDENCE_REVIEW_STORAGE_KEY));
  assert.equal(Object.keys(kept).length, EVIDENCE_REVIEW_MEMORY_LIMIT);
  // Insertion order is recency order, so the oldest reviews are the ones dropped.
  assert.ok(!(REVIEW_ID in kept));

  assert.doesNotThrow(() => rememberEvidenceReview(REVIEW_ID, RUN_ID, brokenStorage()));
  assert.equal(rememberedEvidenceReview(REVIEW_ID, brokenStorage()), null);
  assert.equal(rememberedEvidenceReview(REVIEW_ID, memoryStorage({ [EVIDENCE_REVIEW_STORAGE_KEY]: "{oops" })), null);
});

test("forgetting only removes the run that is still remembered", () => {
  const storage = memoryStorage();
  rememberEvidenceReview(REVIEW_ID, RUN_ID, storage);
  forgetEvidenceReview(REVIEW_ID, "11111111-1111-4111-8111-111111111111", storage);
  assert.equal(rememberedEvidenceReview(REVIEW_ID, storage), RUN_ID);
  forgetEvidenceReview(REVIEW_ID, RUN_ID, storage);
  assert.equal(rememberedEvidenceReview(REVIEW_ID, storage), null);
});

test("a remembered run reopens only for the site review it belongs to", async () => {
  const storage = memoryStorage();
  assert.equal(await resumableEvidenceReview(REVIEW_ID, { request: async () => assert.fail("no request"), storage }), null);

  rememberEvidenceReview(REVIEW_ID, RUN_ID, storage);
  const paths = [];
  const owned = async (path) => { paths.push(path); return { input: { site_review_id: REVIEW_ID.toUpperCase() } }; };
  assert.equal(await resumableEvidenceReview(REVIEW_ID, { request: owned, storage }), RUN_ID);
  assert.deepEqual(paths, [`/evidence-reviews/${RUN_ID}`]);

  const foreign = async () => ({ input: { site_review_id: OTHER_REVIEW_ID } });
  assert.equal(await resumableEvidenceReview(REVIEW_ID, { request: foreign, storage }), null);
  assert.equal(rememberedEvidenceReview(REVIEW_ID, storage), null);
});

test("a deleted run is forgotten, but an unreachable server keeps the memory", async () => {
  const storage = memoryStorage();
  rememberEvidenceReview(REVIEW_ID, RUN_ID, storage);
  assert.equal(await resumableEvidenceReview(REVIEW_ID, { request: async () => { throw httpError(503); }, storage }), null);
  assert.equal(rememberedEvidenceReview(REVIEW_ID, storage), RUN_ID);

  assert.equal(await resumableEvidenceReview(REVIEW_ID, { request: async () => { throw httpError(404); }, storage }), null);
  assert.equal(rememberedEvidenceReview(REVIEW_ID, storage), null);

  rememberEvidenceReview(REVIEW_ID, RUN_ID, storage);
  const aborted = Object.assign(new Error("aborted"), { name: "AbortError" });
  await assert.rejects(resumableEvidenceReview(REVIEW_ID, { request: async () => { throw aborted; }, storage }), aborted);
});

test("reviews are enabled only on a clear yes from the capability route", async () => {
  const asked = [];
  const answer = (body) => async (path) => { asked.push(path); return body; };
  assert.equal(await evidenceReviewEnabled({ request: answer({ evidence_review: { enabled: true } }) }), true);
  assert.deepEqual(asked, [EVIDENCE_REVIEW_CAPABILITIES_PATH]);
  assert.equal(await evidenceReviewEnabled({ request: answer({ evidence_review: { enabled: false } }) }), false);
  assert.equal(await evidenceReviewEnabled({ request: answer({ evidence_review: { enabled: "yes" } }) }), false);
  assert.equal(await evidenceReviewEnabled({ request: answer({}) }), false);
  // A deployment too old to publish the route, or a server fault, counts as disabled.
  assert.equal(await evidenceReviewEnabled({ request: async () => { throw httpError(404); } }), false);
  const aborted = Object.assign(new Error("aborted"), { name: "AbortError" });
  await assert.rejects(evidenceReviewEnabled({ request: async () => { throw aborted; } }), aborted);
});

test("mounting requires a root and the site review on screen", () => {
  assert.throws(() => mountEvidenceReview({ siteReviewId: REVIEW_ID }), /requires root/);
  assert.throws(() => mountEvidenceReview({ root: {} }), /requires siteReviewId/);
});
