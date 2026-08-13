import assert from "node:assert/strict";
import test from "node:test";

import {
  ApiError,
  actionAvailability,
  collection,
  coverageRows,
  entity,
  formatBytes,
  nextPollDelay,
  parseJsonField,
  queryString,
  requestJson,
  stateLabel,
} from "../../frontend/core.js";

function response(body, { status = 200, headers = {} } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => headers[name] || headers[name.toLowerCase()] || null },
    json: async () => body,
  };
}

test("collection and entity tolerate the documented response envelopes", () => {
  const items = [{ id: "one" }, { id: "two" }];
  assert.deepEqual(collection({ items, count: 2 }), items);
  assert.deepEqual(collection({ quality_results: items }), items);
  assert.deepEqual(collection(items), items);
  assert.deepEqual(collection({ other: items }), []);
  assert.deepEqual(entity({ property: items[0], identifiers: [] }, "property"), items[0]);
  assert.deepEqual(entity({ release: items[1], receipts: [] }, "release"), items[1]);
});

test("requestJson adds correlation and idempotency-compatible JSON headers", async () => {
  let observed;
  const result = await requestJson(async (url, options) => {
    observed = { url, options };
    return response({ id: "created" }, { status: 201, headers: { "X-Request-ID": "server-request" } });
  }, "/api/data-platform/v1/sources", { method: "POST", body: { name: "Fixture" }, headers: { "Idempotency-Key": "idem-1" } });

  assert.equal(observed.url, "/api/data-platform/v1/sources");
  assert.equal(observed.options.method, "POST");
  assert.equal(observed.options.headers.Accept, "application/json");
  assert.equal(observed.options.headers["Content-Type"], "application/json");
  assert.ok(observed.options.headers["X-Request-ID"]);
  assert.equal(observed.options.headers["Idempotency-Key"], "idem-1");
  assert.equal(observed.options.body, JSON.stringify({ name: "Fixture" }));
  assert.equal(result.requestId, "server-request");
});

test("Problem Details are safe errors with request IDs", async () => {
  await assert.rejects(
    requestJson(async () => response(
      { type: "about:blank", title: "Conflict", detail: "Definition is already referenced." },
      { status: 409, headers: { "X-Request-ID": "req-conflict" } },
    ), "/api/data-platform/v1/sources/one", { method: "DELETE" }),
    (error) => error instanceof ApiError
      && error.status === 409
      && error.message === "Definition is already referenced."
      && error.requestId === "req-conflict",
  );
});

test("timeouts abort transport and return a bounded safe error", async () => {
  let aborted = false;
  const never = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => {
      aborted = true;
      const error = new Error("aborted");
      error.name = "AbortError";
      reject(error);
    }, { once: true });
  });
  await assert.rejects(requestJson(never, "/slow", { timeoutMs: 5 }), /timed out after 0.005 seconds/);
  assert.equal(aborted, true);
});

test("query construction excludes empty values and remains encoded", () => {
  assert.equal(queryString({ q: "1 Farrer Place", state: "NSW", status: "" }), "?q=1+Farrer+Place&state=NSW");
});

test("JSON form fields reject arrays and invalid input", () => {
  assert.deepEqual(parseJsonField('{"locality":"Sydney"}', "Scope"), { locality: "Sydney" });
  assert.deepEqual(parseJsonField("", "Scope"), {});
  assert.throws(() => parseJsonField("[]", "Scope"), /Scope must be a JSON object/);
  assert.throws(() => parseJsonField("not json", "Scope"), /Scope must be a JSON object/);
});

test("run action policy exposes only state-safe controls", () => {
  assert.deepEqual(actionAvailability("running"), { cancel: true, resume: false, retry: false, reprocess: false, diagnose: false });
  assert.deepEqual(actionAvailability("interrupted"), { cancel: false, resume: true, retry: false, reprocess: false, diagnose: true });
  assert.deepEqual(actionAvailability("failed"), { cancel: false, resume: false, retry: true, reprocess: true, diagnose: true });
});

test("polling stops for terminal states and backs off when hidden", () => {
  assert.equal(nextPollDelay("running"), 1200);
  assert.equal(nextPollDelay("queued"), 2000);
  assert.equal(nextPollDelay("running", 2), 4800);
  assert.equal(nextPollDelay("running", 0, true), 10000);
  assert.equal(nextPollDelay("succeeded"), null);
  assert.equal(nextPollDelay("failed"), null);
});

test("coverage matrices flatten into accessible table rows", () => {
  assert.deepEqual(coverageRows({ matrix: { crime: { Sydney: "accepted", Dubbo: "partial" } } }), [
    { dataset: "crime", locality: "Sydney", status: "accepted" },
    { dataset: "crime", locality: "Dubbo", status: "partial" },
  ]);
  assert.deepEqual(coverageRows({ items: [{ dataset: "schools", status: "accepted" }] }), [{ dataset: "schools", status: "accepted" }]);
});

test("formatting pairs states with text and handles byte boundaries", () => {
  assert.deepEqual(stateLabel("accepted"), { text: "Accepted", tone: "positive", symbol: "✓" });
  assert.deepEqual(stateLabel("stale"), { text: "Stale", tone: "warning", symbol: "△" });
  assert.equal(formatBytes(1024), "1.00 KB");
  assert.equal(formatBytes(10 * 1024 * 1024), "10.0 MB");
});
