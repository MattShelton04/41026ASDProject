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
import {
  createReviewCapabilities,
  markReviewActionUnavailable,
  REVIEW_CAPABILITIES_PATH,
  REVIEW_UNAVAILABLE_IDS,
  reviewActionAvailable,
  reviewCapability,
  unavailableReviewExplanations,
} from "../../frontend/integration/review-capabilities.js";

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
});

test("only the reviewable statuses the database allows offer a readiness review", async () => {
  assert.deepEqual([...READINESS_REVIEW_STATUSES].sort(), ["awaiting_review", "candidate"]);
  const schema = await readFile(new URL("../../database/src/propertyscope_data_store/sql/001_initial.sql", import.meta.url), "utf8");
  const allowed = schema.match(/CREATE TABLE ops\.dataset_release[\s\S]*?status TEXT NOT NULL CHECK \(status IN \(([^)]*)\)\)/)[1];
  for (const status of READINESS_REVIEW_STATUSES) assert.match(allowed, new RegExp(`'${status}'`));
  const workflow = await readFile(new URL("../../config/multi-agent/workflow.yaml", import.meta.url), "utf8");
  assert.match(workflow, /path: release\.status, operator: in, value: \[candidate, awaiting_review\]/);
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

function buttonDouble() {
  const attributes = new Map();
  const classes = new Set();
  return {
    attributes,
    classes,
    setAttribute: (name, value) => attributes.set(name, String(value)),
    getAttribute: (name) => attributes.get(name) ?? null,
    removeAttribute: (name) => attributes.delete(name),
    classList: { add: (name) => classes.add(name) },
  };
}

const CLOUD_BASELINE = Object.freeze({
  readiness_review: { enabled: false, detail: "Multi-agent review is not enabled in this deployment." },
  ai_review: { enabled: false, detail: "AI review is not enabled in this deployment." },
});

test("only an explicit disabled answer turns a review action off", () => {
  assert.deepEqual(reviewCapability(CLOUD_BASELINE, "readiness_review"), { enabled: false, detail: "Multi-agent review is not enabled in this deployment." });
  assert.deepEqual(reviewCapability({ ai_review: { enabled: false } }, "ai_review"), { enabled: false, detail: "AI review is not enabled in this deployment." });
  for (const answer of [null, undefined, {}, { readiness_review: { enabled: true, detail: null } }, { readiness_review: "off" }]) {
    assert.deepEqual(reviewCapability(answer, "readiness_review"), { enabled: true, detail: "" });
  }
  assert.deepEqual(unavailableReviewExplanations(CLOUD_BASELINE).map((item) => [item.key, item.id]), [
    ["readiness_review", "readiness-review-unavailable"], ["ai_review", "ai-review-unavailable"],
  ]);
  assert.deepEqual(unavailableReviewExplanations(CLOUD_BASELINE, ["ai_review"]).map((item) => item.key), ["ai_review"]);
  assert.deepEqual(unavailableReviewExplanations({ readiness_review: { enabled: true }, ai_review: { enabled: true } }), []);
});

test("capabilities are asked once, and a failed read is asked again later", async () => {
  const paths = [];
  let fail = true;
  const capabilities = createReviewCapabilities(async (path, options) => {
    paths.push([path, options.timeoutMs]);
    if (fail) throw Object.assign(new Error("HTTP 503"), { status: 503 });
    return { body: { connected_live_profiles: [], review_actions: CLOUD_BASELINE } };
  });
  assert.equal(await capabilities.load(), null, "an unreadable answer keeps both actions offered");
  fail = false;
  assert.deepEqual(await capabilities.load(), CLOUD_BASELINE);
  assert.deepEqual(await capabilities.load(), CLOUD_BASELINE);
  assert.equal(REVIEW_CAPABILITIES_PATH, "runtime-capabilities");
  assert.deepEqual(paths, [[REVIEW_CAPABILITIES_PATH, 4000], [REVIEW_CAPABILITIES_PATH, 4000]]);
  const olderBackend = createReviewCapabilities(async () => ({ body: { connected_live_profiles: [] } }));
  assert.equal(await olderBackend.load(), null, "a backend without review_actions keeps both actions offered");
});

test("a disabled review action stays focusable and is described by its explanation", () => {
  const trigger = buttonDouble();
  trigger.setAttribute("aria-controls", "release-readiness-review");
  trigger.setAttribute("aria-expanded", "false");
  assert.equal(reviewActionAvailable(trigger), true);
  markReviewActionUnavailable(trigger, REVIEW_UNAVAILABLE_IDS.readiness_review);
  assert.equal(reviewActionAvailable(trigger), false);
  assert.equal(trigger.getAttribute("aria-disabled"), "true");
  assert.equal(trigger.getAttribute("aria-describedby"), "readiness-review-unavailable");
  assert.equal(trigger.getAttribute("aria-controls"), null, "a disabled action reveals no panel");
  assert.equal(trigger.getAttribute("aria-expanded"), null);
  assert.ok(trigger.classes.has("is-unavailable"));
});

test("the release page gates both review actions on the deployment's capabilities", async () => {
  const source = await readFile(new URL("../../frontend/routes/releases.js", import.meta.url), "utf8");
  assert.match(source, /reviewCapabilities = createReviewCapabilities\(request\)/);
  assert.match(source, /if \(requestedReviewRun && readinessCapability\.enabled\) openReadinessReview/);
  assert.match(source, /if \(!reviewActionAvailable\(readinessTrigger\)\) return;/);
  assert.match(source, /if \(!readinessCapability\.enabled\) markReviewActionUnavailable\(readinessTrigger, REVIEW_UNAVAILABLE_IDS\.readiness_review\)/);
  assert.match(source, /if \(!reviewActionAvailable\(aiReviewTrigger\)\) return;/);
  assert.match(source, /if \(!aiReviewCapability\.enabled\) markReviewActionUnavailable\(aiReviewTrigger, REVIEW_UNAVAILABLE_IDS\.ai_review\)/);
  assert.match(source, /sentence\.id = explanation\.id/);
  const styles = await readFile(new URL("../../frontend/styles.css", import.meta.url), "utf8");
  assert.match(styles, /\.button\[aria-disabled="true"\] \{ cursor: not-allowed; opacity: \.5; \}/);
});
