import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  createReleaseReadinessReview,
  forgetReadinessReview,
  READINESS_REVIEW_MEMORY_LIMIT,
  READINESS_REVIEW_STATUSES,
  READINESS_REVIEW_STORAGE_KEY,
  RELEASE_REVIEW_API_ROOT,
  readinessReviewHash,
  readinessReviewInput,
  readinessReviewRunId,
  rememberedReadinessReview,
  rememberReadinessReview,
  resumableReadinessReview,
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

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, String(value)); },
  };
}

function problem(status, name = "ApiError") {
  return Object.assign(new Error(`HTTP ${status}`), { status, name });
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
    storage: memoryStorage(),
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

test("the latest review for each release is remembered, bounded and tolerant of broken storage", () => {
  const storage = memoryStorage();
  assert.equal(rememberedReadinessReview(RELEASE_ID, storage), null);
  rememberReadinessReview(RELEASE_ID, RUN_ID.toUpperCase(), storage);
  assert.equal(rememberedReadinessReview(RELEASE_ID, storage), RUN_ID);
  rememberReadinessReview(RELEASE_ID, "not-a-run", storage);
  assert.equal(rememberedReadinessReview(RELEASE_ID, storage), RUN_ID);
  for (let index = 0; index < READINESS_REVIEW_MEMORY_LIMIT + 5; index += 1) {
    rememberReadinessReview(`release-${index}`, RUN_ID, storage);
  }
  const kept = JSON.parse(storage.getItem(READINESS_REVIEW_STORAGE_KEY));
  assert.equal(Object.keys(kept).length, READINESS_REVIEW_MEMORY_LIMIT);
  assert.equal(rememberedReadinessReview(RELEASE_ID, storage), null, "the oldest release is dropped first");
  assert.equal(rememberedReadinessReview(`release-${READINESS_REVIEW_MEMORY_LIMIT + 4}`, storage), RUN_ID);

  forgetReadinessReview("release-24", "c17c66cc-6b40-4685-909a-000000000000", storage);
  assert.equal(rememberedReadinessReview("release-24", storage), RUN_ID, "only the remembered run is forgotten");
  forgetReadinessReview("release-24", RUN_ID, storage);
  assert.equal(rememberedReadinessReview("release-24", storage), null);

  const corrupt = memoryStorage({ [READINESS_REVIEW_STORAGE_KEY]: "{not json" });
  assert.equal(rememberedReadinessReview(RELEASE_ID, corrupt), null);
  const blocked = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.doesNotThrow(() => rememberReadinessReview(RELEASE_ID, RUN_ID, blocked));
  assert.equal(rememberedReadinessReview(RELEASE_ID, blocked), null);
  assert.equal(rememberedReadinessReview(RELEASE_ID, null), null);
});

test("a remembered review reopens only when the proxy still holds it for this exact release", async () => {
  const release = { id: RELEASE_ID };
  const remembered = () => memoryStorage({ [READINESS_REVIEW_STORAGE_KEY]: JSON.stringify({ [RELEASE_ID]: RUN_ID }) });
  const paths = [];

  let storage = remembered();
  const found = await resumableReadinessReview(release, { storage, request: async (path) => { paths.push(path); return { body: { id: RUN_ID, input: { release_id: RELEASE_ID.toUpperCase() } } }; } });
  assert.equal(found, RUN_ID);
  assert.deepEqual(paths, [`release-reviews/${RUN_ID}`]);

  storage = remembered();
  assert.equal(await resumableReadinessReview(release, { storage, request: async () => ({ body: { input: { release_id: "another-release" } } }) }), null);
  assert.equal(rememberedReadinessReview(RELEASE_ID, storage), null, "a run for another release is forgotten");

  storage = remembered();
  assert.equal(await resumableReadinessReview(release, { storage, request: async () => { throw problem(404); } }), null);
  assert.equal(rememberedReadinessReview(RELEASE_ID, storage), null, "a run the server no longer has is forgotten");

  storage = remembered();
  assert.equal(await resumableReadinessReview(release, { storage, request: async () => { throw problem(503); } }), null);
  assert.equal(rememberedReadinessReview(RELEASE_ID, storage), RUN_ID, "an unavailable server keeps the memory for later");

  storage = remembered();
  await assert.rejects(resumableReadinessReview(release, { storage, request: async () => { throw problem(0, "AbortError"); } }), { name: "AbortError" });

  let called = false;
  assert.equal(await resumableReadinessReview(release, { storage: memoryStorage(), request: async () => { called = true; } }), null);
  assert.equal(called, false, "nothing is requested when no review was started here");
});

test("starting or reopening a review remembers it for the release", () => {
  const storage = memoryStorage();
  let panelOptions = null;
  createReleaseReadinessReview({
    release: { id: RELEASE_ID, dataset_id: "nsw-amenities", status: "awaiting_review" },
    storage,
    document: documentDouble(),
    createClient: () => ({ destroy() {} }),
    createPanel: (options) => { panelOptions = options; return { run: null, focus() {}, destroy() {} }; },
  });
  panelOptions.onRunChange(null);
  assert.equal(rememberedReadinessReview(RELEASE_ID, storage), null);
  panelOptions.onRunChange({ id: RUN_ID, state: "working" });
  assert.equal(rememberedReadinessReview(RELEASE_ID, storage), RUN_ID);
});

test("the release page reopens the remembered review instead of offering a duplicate run", async () => {
  const source = await readFile(new URL("../../frontend/routes/releases.js", import.meta.url), "utf8");
  assert.match(source, /READINESS_REVIEW_STATUSES\.has\(release\.status\) \|\| readinessReview \|\| rememberedReadinessReview\(release\.id\)/);
  assert.match(source, /runId = await resumableReadinessReview\(release, \{ request \}\)/);
  assert.match(source, /review = openReadinessReview\(release, runId\)/);
  assert.match(source, /readinessTrigger\.setAttribute\("aria-busy", "true"\)/);
  assert.match(source, /readinessTrigger\.setAttribute\("aria-controls", "release-readiness-review"\)/);
  assert.match(source, /readinessTrigger\.setAttribute\("aria-expanded", String\(Boolean\(readinessReview\)\)\)/);
});
