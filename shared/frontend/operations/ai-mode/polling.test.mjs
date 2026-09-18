import assert from "node:assert/strict";
import test from "node:test";

import {
  GenerationGuard,
  RequestTimeoutError,
  filterForStatuses,
  mergeEventPage,
  nextDetailDelay,
  nextListDelay,
  requestJson,
  restoreCursor,
  shouldRefreshDetail,
  statusesForFilter,
} from "./polling.js";

function response(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

test("adaptive polling is fast only while useful and backs off when hidden", () => {
  assert.equal(nextListDelay([{ status: "planning" }]), 2000);
  assert.equal(nextListDelay([{ status: "succeeded" }]), 10000);
  assert.equal(nextListDelay([{ status: "planning" }], 2), 8000);
  assert.equal(nextListDelay([{ status: "planning" }], 0, true), 30000);

  assert.equal(nextDetailDelay("planning"), 800);
  assert.equal(nextDetailDelay("queued"), 1500);
  assert.equal(nextDetailDelay("review_required"), 5000);
  assert.equal(nextDetailDelay("planning", 2), 3200);
  assert.equal(nextDetailDelay("planning", 0, true), 5000);
  assert.equal(nextDetailDelay("succeeded"), null);
  assert.equal(nextDetailDelay("failed", 3, true), null);
});

test("generation guards reject late out-of-order work", () => {
  const guard = new GenerationGuard();
  const first = guard.advance();
  const second = guard.advance();

  assert.equal(guard.isCurrent(first), false);
  assert.equal(guard.isCurrent(second), true);
});

test("requestJson applies a client timeout and aborts the transport", async () => {
  let observedAbort = false;
  const neverCompletes = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => {
      observedAbort = true;
      const error = new Error("aborted");
      error.name = "AbortError";
      reject(error);
    }, { once: true });
  });

  await assert.rejects(
    requestJson(neverCompletes, "/slow", { timeoutMs: 5 }),
    RequestTimeoutError,
  );
  assert.equal(observedAbort, true);
});

test("external cancellation wins without being reported as a timeout", async () => {
  const controller = new AbortController();
  const neverCompletes = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => {
      const error = new Error("selection changed");
      error.name = "AbortError";
      reject(error);
    }, { once: true });
  });
  const pending = requestJson(neverCompletes, "/obsolete", {
    signal: controller.signal,
    timeoutMs: 1000,
  });
  controller.abort();

  await assert.rejects(pending, { name: "AbortError" });
});

test("requestJson preserves conditional responses and safe API errors", async () => {
  const unchanged = await requestJson(async () => response(null, { status: 304 }), "/detail");
  assert.equal(unchanged.response.status, 304);
  assert.equal(unchanged.body, null);

  await assert.rejects(
    requestJson(async () => response({ code: "unavailable" }, { status: 503 }), "/detail"),
    /503: unavailable/,
  );
  await assert.rejects(
    requestJson(async () => response(null, { status: 502 }), "/detail"),
    /502: request failed/,
  );
});

test("cursor restoration is safe and duplicate events stay bounded", () => {
  assert.equal(restoreCursor("42"), 42);
  assert.equal(restoreCursor("not-a-cursor"), 0);
  assert.equal(restoreCursor("-1"), 0);

  const existing = [{ id: 2, run_version: 2 }, { id: 3, run_version: 3 }];
  const incoming = [{ id: 1, run_version: 1 }, { id: 3, run_version: 30 }, { id: 4, run_version: 4 }];
  const merged = mergeEventPage(existing, incoming, 3);

  assert.deepEqual(merged.items.map((event) => event.id), [2, 3, 4]);
  assert.equal(merged.items[1].run_version, 30);
  assert.equal(merged.cursor, 4);
});

test("terminal events trigger one authoritative detail refresh then stop", () => {
  assert.equal(shouldRefreshDetail({ eventCount: 1, hasDetail: true }), true);
  assert.equal(shouldRefreshDetail({ eventCount: 0, hasDetail: true }), false);
  assert.equal(shouldRefreshDetail({ eventCount: 0, hasDetail: false }), true);
  assert.equal(shouldRefreshDetail({ force: true, eventCount: 0, hasDetail: true }), true);
  assert.equal(nextDetailDelay("cancelled"), null);
});

test("quick-filter status sets round-trip without inventing statuses", () => {
  const active = statusesForFilter("active");
  assert.equal(active.includes("planning"), true);
  assert.equal(active.includes("succeeded"), false);
  assert.equal(filterForStatuses(active), "active");
  assert.deepEqual(statusesForFilter("unknown"), []);
});

test("optional cursor storage tolerates denied access and corrupt values", async () => {
  const { createCursorStore } = await import("./polling.js");
  const denied = createCursorStore(() => { throw new Error("SecurityError"); });
  assert.equal(denied.read("run"), 0);
  assert.doesNotThrow(() => denied.write("run", 42));
  const values = new Map();
  const available = createCursorStore(() => ({getItem: (key) => values.get(key), setItem: (key, value) => values.set(key, value)}));
  available.write("run", 42);
  assert.equal(available.read("run"), 42);
  available.write("run", -8);
  assert.equal(available.read("run"), 0);
});


test("activity handoff preserves only approved assistant return destinations", async () => {
  const { resolveResearchAreaContext, activityAreaLabel } = await import("./contexts.js");
  const params = new URLSearchParams({
    feature_key: "student-1-propertyscope-data-platform", feature_label: "Property data",
    return_to: "/features/data-platform/#assistant",
  });
  assert.equal(resolveResearchAreaContext(params).returnTo, "/features/data-platform/#assistant");
  params.set("return_to", "/#assistant");
  assert.equal(resolveResearchAreaContext(params).returnTo, "/#assistant");
  const review = "/features/data-platform/#ai/577e8221-e393-442f-9e6f-b81505dc24ab";
  for (const safe of [review, review.replace("#ai/", "#ai/release:") + "?goal=quality"]) {
    params.set("return_to", safe);
    assert.equal(resolveResearchAreaContext(params).returnTo, safe);
  }
  for (const unsafe of ["//external.invalid/", "/unapproved", "https://external.invalid/", review + "?next=//external.invalid", review + "/extra", review.replace("577e8221", "invalid"), review + "?goal=publish"]) {
    params.set("return_to", unsafe);
    assert.equal(resolveResearchAreaContext(params), null);
  }
  assert.equal(activityAreaLabel("feature-1"), "Property data");
  assert.equal(activityAreaLabel("unregistered-key"), "unregistered key");
});
