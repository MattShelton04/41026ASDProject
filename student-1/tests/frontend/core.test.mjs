import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  ApiError,
  actionAvailability,
  collection,
  coverageRows,
  entity,
  formatBytes,
  isPsiJob,
  isSchoolsJob,
  nextPollDelay,
  parseJsonField,
  psiYearRange,
  queryString,
  releaseComparison,
  reportReleaseRows,
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

test("successful no-content deletion does not attempt to parse a body", async () => {
  const result = await requestJson(async () => ({
    ok: true,
    status: 204,
    headers: { get: () => "delete-request" },
    json: async () => { throw new Error("must not parse"); },
  }), "/api/data-platform/v1/dataset-releases/release-1", { method: "DELETE" });
  assert.equal(result.body, null);
  assert.equal(result.requestId, "delete-request");
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

test("job source detection and explicit year partitions are bounded", () => {
  assert.equal(isPsiJob({ profile_key: "nsw-psi-sales-year" }), true);
  assert.equal(isPsiJob({ adapter_key: "schools-csv" }), false);
  assert.equal(isSchoolsJob({ import_profile_key: "schools-master" }), true);
  assert.equal(isSchoolsJob({ adapter_key: "gnaf-bulk" }), false);
  assert.deepEqual(psiYearRange("2024", "2026", { maximum: 2027 }), [2024, 2025, 2026]);
  assert.throws(() => psiYearRange(2027, 2024, { maximum: 2027 }), /valid range/);
  assert.throws(() => psiYearRange(1989, 2024, { maximum: 2027 }), /1990/);
});

test("run action policy exposes only state-safe controls", () => {
  assert.deepEqual(actionAvailability("running"), { cancel: true, resume: false, retry: false, reprocess: false, diagnose: false });
  assert.deepEqual(actionAvailability("interrupted"), { cancel: false, resume: true, retry: false, reprocess: false, diagnose: true });
  assert.deepEqual(actionAvailability("failed"), { cancel: false, resume: false, retry: true, reprocess: true, diagnose: true });
});

test("polling stops for terminal states and backs off when hidden", () => {
  assert.equal(nextPollDelay("running"), 1200);
  assert.equal(nextPollDelay("acquiring"), 1200);
  assert.equal(nextPollDelay("building_release"), 1200);
  assert.equal(nextPollDelay("queued"), 2000);
  assert.equal(nextPollDelay("running", 2), 4800);
  assert.equal(nextPollDelay("running", 0, true), 10000);
  assert.equal(nextPollDelay("succeeded"), null);
  assert.equal(nextPollDelay("failed"), null);
});

test("the application shell exposes keyboard landmarks, live status and native dialogs", async () => {
  const html = await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8");
  assert.match(html, /href="#main-content">Skip to main content/);
  assert.match(html, /<nav>/);
  assert.match(html, /<main id="main-content" tabindex="-1">/);
  assert.match(html, /id="live-region"[^>]+aria-live="polite"/);
  assert.match(html, /<dialog id="entity-dialog"/);
  assert.match(html, /<dialog id="action-dialog"/);
  assert.match(html, /value="cancel" formnovalidate/);
  assert.match(html, /id="entity-save"[^>]+type="submit"/);
  assert.match(html, /id="action-confirm"[^>]+type="submit"/);
  assert.doesNotMatch(html, /<script(?![^>]+src=)/);
  assert.doesNotMatch(html, /style="/);
});

test("the frontend proxy keeps browser traffic on the public backend boundary", async () => {
  const nginx = await readFile(new URL("../../frontend/nginx.conf", import.meta.url), "utf8");
  assert.match(nginx, /location \/api\/data-platform\//);
  assert.match(nginx, /proxy_pass http:\/\/propertyscope-backend:5201/);
  assert.doesNotMatch(nginx, /propertyscope-database/);
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

test("release comparison keeps candidate and accepted evidence visibly distinct", () => {
  const rows = releaseComparison(
    { schema_version: "v2", record_count: 98, content_sha256: "candidate", coverage_json: { complete: false } },
    { schema_version: "v1", record_count: 100, content_sha256: "accepted", coverage_json: { complete: true } },
  );
  assert.deepEqual(rows.map((row) => row.field), ["Schema version", "Record count", "Content checksum", "Coverage"]);
  assert.equal(rows.every((row) => row.changed), true);
  assert.deepEqual(releaseComparison({}, null), []);
});

test("report-section release evidence is bounded and defensively normalized", () => {
  const releases = [{ dataset_id: "crime", release_status: "accepted" }];
  assert.deepEqual(reportReleaseRows({ property_ref: "property-1", release_evidence: releases }), releases);
  assert.deepEqual(reportReleaseRows({ property_ref: "property-1" }), []);
  assert.deepEqual(reportReleaseRows(null), []);
});

test("release CRUD and report-section routes are represented in the browser client", async () => {
  const source = await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8");
  assert.match(source, /Create draft release/);
  assert.match(source, /method: item \? "PUT" : "POST"/);
  assert.match(source, /method: "DELETE"/);
  assert.match(source, /properties\/\$\{encodeURIComponent\(summary\.property_ref\)\}\/report-section/);
  assert.match(source, /Candidate comparison/);
  assert.match(source, /Quality review/);
  assert.match(source, /item\.release_version \|\| item\.dataset_release_id/);
  assert.match(source, /badge\(item\.coverage_status\)/);
});

test("operator UI exposes working submit controls, backfills and durable histories", async () => {
  const source = await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8");
  assert.match(source, /search\.type = "submit"/);
  assert.match(source, /apply\.type = "submit"/);
  assert.match(source, /button\("Run now"/);
  assert.match(source, /button\("Backfill"/);
  assert.match(source, /PSI source year/);
  assert.match(source, /Preview deterministic plan/);
  assert.match(source, /link\("Run history"/);
});

test("AI diagnosis history is loaded from the durable shared service projection", async () => {
  const source = await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8");
  assert.match(source, /request\("agent-runs\?limit=50"\)/);
  assert.match(source, /panel\("Diagnosis history"/);
  assert.match(source, /`#ai\/\$\{run\.id\}`/);
  assert.match(source, /selectedAgentRun/);
});
