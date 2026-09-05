import assert from "node:assert/strict";
import { test } from "node:test";
import {
  HttpProblem, RequestTimeoutError, createJsonClient, requestJsonResponse, withRequestLifecycle,
} from "./index.js";

const response = (body, status = 200, headers = new Headers()) => ({
  ok: status >= 200 && status < 300, status, headers, json: async () => body,
});

test("JSON requests cover the body read, not just response headers", async () => {
  await assert.rejects(requestJsonResponse(async () => ({
    ...response(null), json: () => new Promise(() => {}),
  }), "/api/example", { timeoutMs: 10 }), (error) => error instanceof HttpProblem && /timed out/.test(error.message));
});

test("pre-aborted requests never invoke their operation", async () => {
  const owner = new AbortController(); owner.abort(); let calls = 0;
  await assert.rejects(withRequestLifecycle(() => { calls += 1; }, { signal: owner.signal }), { name: "AbortError" });
  assert.equal(calls, 0);
});

test("aborting a caller bounds an operation even when a test double ignores the signal", async () => {
  const owner = new AbortController();
  const pending = withRequestLifecycle(() => new Promise(() => {}), { signal: owner.signal });
  owner.abort();
  await assert.rejects(pending, { name: "AbortError" });
});

test("duplicated abort sources install one listener and clean it after completion", async () => {
  const owner = new AbortController(); let added = 0; let removed = 0;
  const source = {
    get aborted() { return owner.signal.aborted; },
    addEventListener(...args) { added += 1; owner.signal.addEventListener(...args); },
    removeEventListener(...args) { removed += 1; owner.signal.removeEventListener(...args); },
  };
  assert.equal(await withRequestLifecycle(async () => 42, { signal: source, signals: [source, source] }), 42);
  assert.equal(added, 1); assert.equal(removed, 1);
});

test("timeout has a distinct type and retains its duration", async () => {
  await assert.rejects(withRequestLifecycle(() => new Promise(() => {}), { timeoutMs: 10 }),
    (error) => error instanceof RequestTimeoutError && error.timeoutMs === 10);
});

test("JSON headers merge case-insensitively without dropping idempotency or request identity", async () => {
  let options;
  await requestJsonResponse(async (_path, value) => { options = value; return response({}); }, "/api/example", {
    method: "POST", body: { value: 3 }, headers: { "x-request-id": "request-1", "Idempotency-Key": "retry-1", accept: "application/problem+json" },
  });
  assert.equal(options.headers["X-Request-ID"], "request-1");
  assert.equal(options.headers["Idempotency-Key"], "retry-1");
  assert.equal(options.headers.Accept, "application/problem+json");
  assert.equal(options.body, '{"value":3}');
  assert.equal(Object.keys(options.headers).filter((key) => key.toLowerCase() === "x-request-id").length, 1);
});

test("Headers objects and raw JSON strings are supported", async () => {
  let options;
  await requestJsonResponse(async (_path, value) => { options = value; return response({}); }, "/", {
    body: '{"already":"encoded"}', headers: new Headers({ "X-Request-ID": "headers-object" }),
  });
  assert.equal(options.headers["X-Request-ID"], "headers-object");
  assert.equal(options.body, '{"already":"encoded"}');
});

test("204 deletes succeed without attempting JSON decoding", async () => {
  const result = await requestJsonResponse(async () => ({ ...response(null, 204), json: () => { throw new Error("must not read"); } }), "/", { method: "DELETE" });
  assert.equal(result.body, null);
});

test("successful but unreadable JSON is not mistaken for empty data", async () => {
  await assert.rejects(requestJsonResponse(async () => ({ ...response(null), json: async () => { throw new SyntaxError("HTML"); } }), "/"),
    (error) => error.status === 200 && /unreadable/.test(error.message));
});

test("HTTP problems retain response correlation, status, code and detail", async () => {
  const problem = { code: "stale_version", detail: "Reload before saving." };
  await assert.rejects(requestJsonResponse(async () => response(problem, 409, new Headers({ "X-Request-ID": "response-1" })), "/"),
    (error) => error.status === 409 && error.requestId === "response-1" && error.code === "stale_version" && error.problem === problem);
});

test("transport failures never silently retry mutations", async () => {
  let calls = 0;
  await assert.rejects(requestJsonResponse(async () => { calls += 1; throw new TypeError("network"); }, "/", { method: "POST", body: {} }), HttpProblem);
  assert.equal(calls, 1);
});

test("feature client supplies its namespace without importing feature semantics", async () => {
  let path;
  const client = createJsonClient({ baseUrl: "/api/owned/v1", fetcher: async (value) => { path = value; return response({ items: [] }); } });
  assert.deepEqual(await client("/items"), { items: [] });
  assert.equal(path, "/api/owned/v1/items");
});

// Poll and navigation guards are tested independently from feature business rules.
const { createLatestTask, pollUntilSettled, resolveProductHome } = await import("./index.js");

test("starting a new task aborts and invalidates the previous result", async () => {
  const owner = createLatestTask(); const old = owner.start(); const waiting = old.delay(1000);
  const current = owner.start();
  assert.equal(old.isCurrent(), false); assert.equal(current.isCurrent(), true);
  await assert.rejects(waiting, { name: "AbortError" });
  owner.cancel(); assert.equal(current.isCurrent(), false);
});

test("terminal initial runs do not poll", async () => {
  let calls = 0; const task = createLatestTask().start();
  const result = await pollUntilSettled(async () => { calls += 1; }, {
    task, initial: {status: "timed_out"}, isSettled: (value) => value.status === "timed_out",
  });
  assert.equal(calls, 0); assert.equal(result.status, "timed_out");
});

test("polling has a wall-clock bound even if the reader ignores cancellation", async () => {
  await assert.rejects(pollUntilSettled(() => new Promise(() => {}), {
    task: createLatestTask().start(), timeoutMs: 10, isSettled: () => false,
  }), RequestTimeoutError);
});

test("cancelled polling never renders a late result", async () => {
  const owner = createLatestTask(); const task = owner.start(); let release; let renders = 0;
  const pending = pollUntilSettled(() => new Promise((resolve) => { release = resolve; }), {
    task, isSettled: () => true, onUpdate: () => { renders += 1; },
  });
  owner.cancel(); release({status: "succeeded"});
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(renders, 0);
});

test("polling stops at its attempt budget", async () => {
  let calls = 0;
  await assert.rejects(pollUntilSettled(async () => { calls += 1; return {}; }, {
    task: createLatestTask().start(), isSettled: () => false, maxAttempts: 2, intervalMs: 0,
  }), /polling limit/);
  assert.equal(calls, 2);
});

for (const [href, expected] of [
  ["http://127.0.0.1:5600/#explore", "http://127.0.0.1:5100/"],
  ["http://localhost:5500/", "http://localhost:5100/"],
  ["http://[::1]:5500/", "http://[::1]:5100/"],
  ["http://127.0.0.1:8765/features/data-platform/#properties", "http://127.0.0.1:8765/"],
  ["https://example.test/features/buyer-workspaces/", "https://example.test/"],
  ["https://example.test/", "https://example.test/"],
]) {
  test(`product home resolves ${href} without a hardcoded localhost host`, () => {
    assert.equal(resolveProductHome({href}), expected);
  });
}

test("explicit product deployment base is preserved and unsafe schemes are rejected", () => {
  assert.equal(resolveProductHome({href: "https://feature.test/"}, "https://product.test/app/"), "https://product.test/app/");
  for (const value of ["javascript:alert(1)", "data:text/html,test", "https://user:pass@product.test/"]) {
    assert.throws(() => resolveProductHome({href: "https://feature.test/"}, value), TypeError);
  }
});

test("status-driven adapters can inspect a valid HTTP error body without accepting malformed JSON", async () => {
  const result = await requestJsonResponse(async () => response({code: "invalid"}, 422), "/", {throwHttpErrors: false});
  assert.equal(result.response.status, 422); assert.equal(result.body.code, "invalid");
  await assert.rejects(requestJsonResponse(async () => ({...response({}), json: async () => { throw new Error("invalid"); }}), "/", {throwHttpErrors: false}), /unreadable/);
});

test("template escaping covers text and quoted attributes", async () => {
  const {escapeHtml} = await import("./index.js");
  assert.equal(escapeHtml('<svg onload="x">&\''), "&lt;svg onload=&quot;x&quot;&gt;&amp;&#039;");
});
