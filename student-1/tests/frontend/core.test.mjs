import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  ApiError,
  actionAvailability,
  collection,
  confidenceLabel,
  createGenerationGuard,
  coverageRows,
  displayName,
  entity,
  formatBytes,
  isPsiJob,
  isSchoolsJob,
  liveProfileLabel,
  nextAgentPollDelay,
  nextPollDelay,
  parseJsonField,
  psiYearRange,
  queryString,
  releaseComparison,
  researchAreaLabel,
  reportReleaseRows,
  requestJson,
  parseRoute,
  routeQuery,
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

test("hash routing is isolated, bounded, and preserves encoded query values", () => {
  assert.deepEqual(parseRoute("#runs/run%201"), { route: "runs", id: "run 1", action: "" });
  assert.deepEqual(parseRoute("#data-products/nsw-psi-sales"), { route: "data-products", id: "nsw-psi-sales", action: "" });
  assert.deepEqual(parseRoute("#not-a-route"), { route: "properties", id: "", action: "" });
  assert.deepEqual(parseRoute(""), { route: "properties", id: "", action: "" });
  assert.equal(routeQuery("#sources?q=crime+data&status=active").get("q"), "crime data");
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
  assert.equal(liveProfileLabel("gnaf-nsw"), "Live official Geoscape G-NAF bulk archive");
  assert.equal(liveProfileLabel("bocsar-sparse"), "Live official BOCSAR archive");
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

test("agent polling follows active and review states without refreshing terminal runs", () => {
  assert.equal(nextAgentPollDelay("planning"), 800);
  assert.equal(nextAgentPollDelay("queued"), 1500);
  assert.equal(nextAgentPollDelay("review_required"), 5000);
  assert.equal(nextAgentPollDelay("acting", 2), 3200);
  assert.equal(nextAgentPollDelay("observing", 0, true), 5000);
  assert.equal(nextAgentPollDelay("succeeded"), null);
  assert.equal(nextAgentPollDelay("failed"), null);
});

test("generation guards reject late route and polling work", () => {
  const guard = createGenerationGuard();
  const first = guard.next();
  assert.equal(guard.isCurrent(first), true);
  guard.next();
  assert.equal(guard.isCurrent(first), false);
  assert.equal(guard.current(), 2);
});

test("the application shell exposes keyboard landmarks, live status and native dialogs", async () => {
  const html = await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8");
  const app = await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8");
  assert.match(html, /href="#main-content">Skip to main content/);
  assert.match(html, /<nav>/);
  assert.match(html, /id="header-property-search"/);
  assert.match(html, /aria-label="PropertyScope navigation"/);
  assert.doesNotMatch(html, /Accepted data stays available during review/);
  assert.doesNotMatch(html, /Assisted diagnosis|Advanced operations/);
  assert.match(html, /<main id="main-content" tabindex="-1">/);
  assert.match(html, /id="live-region"[^>]+aria-live="polite"/);
  assert.match(html, /<dialog id="entity-dialog"/);
  assert.match(html, /<dialog id="action-dialog"/);
  assert.match(html, /value="cancel" formnovalidate/);
  assert.match(html, /id="entity-save"[^>]+type="submit"/);
  assert.match(html, /id="action-confirm"[^>]+type="submit"/);
  assert.doesNotMatch(html, /<script(?![^>]+src=)/);
  assert.doesNotMatch(html, /style="/);
  assert.match(html, /href="\.\/design-system\/tokens\.css/);
  assert.match(html, /src="\.\/app\.js/);
  assert.match(app, /pathname\.startsWith\("\/features\/data-platform\/"\)/);
  assert.match(app, /"\/api\/shared-health\/data-platform"/);
  assert.match(app, /request\(healthUrl/);
  assert.match(app, /event\.key === "Escape"/);
  assert.match(app, /closeNavigation\(\{ restoreFocus: true \}\)/);
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
  assert.deepEqual(stateLabel("accepted"), { text: "Published", tone: "positive", symbol: "✓" });
  assert.deepEqual(stateLabel("stale"), { text: "Stale", tone: "warning", symbol: "△" });
  assert.equal(formatBytes(1024), "1.00 KB");
  assert.equal(formatBytes(10 * 1024 * 1024), "10.0 MB");
  assert.equal(confidenceLabel(0.85714287), "Strong match (86%)");
  assert.equal(confidenceLabel(null), "Match confidence not supplied");
  assert.equal(researchAreaLabel("feature-1"), "Property records");
  assert.equal(researchAreaLabel("feature-4"), "Site & planning");
  assert.equal(researchAreaLabel("future-area"), "Future Area");
  assert.equal(displayName("Deterministic property critical-path fixture"), "Example property records update");
  assert.equal(displayName("G-NAF NSW address registry"), "G-NAF NSW address registry");
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
  const source = [
    await readFile(new URL("../../frontend/routes/releases.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/properties.js", import.meta.url), "utf8"),
  ].join("\n");
  assert.match(source, /Create draft version/);
  assert.match(source, /method: item \? "PUT" : "POST"/);
  assert.match(source, /method: "DELETE"/);
  assert.match(source, /properties\/\$\{encodeURIComponent\(propertyRef\)\}\/report-section/);
  assert.match(source, /New and published versions/);
  assert.match(source, /Data checks/);
  assert.doesNotMatch(source, /Deterministic quality review/);
  assert.match(source, /item\.release_version \|\| item\.dataset_release_id/);
  assert.match(source, /badge\(item\.coverage_status\)/);
});

test("release details render bounded paginated dataset records", async () => {
  const releases = await readFile(new URL("../../frontend/routes/releases.js", import.meta.url), "utf8");
  assert.match(releases, /dataset-releases\/\$\{id\}\/records\?limit=25&offset=0/);
  assert.match(releases, /function releasePreviewPanel/);
  assert.match(releases, /No other version is included/);
  assert.match(releases, /Next page/);
});

test("data product catalogue clearly identifies a missing published version", async () => {
  const products = await readFile(new URL("../../frontend/routes/data-products.js", import.meta.url), "utf8");
  assert.match(products, /No published version yet/);
  assert.doesNotMatch(products, /contract-valid release/);
  assert.doesNotMatch(products, /\|\| "None"/);
});

test("operator UI exposes working submit controls, backfills and durable histories", async () => {
  const source = [
    await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/components/forms.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/properties.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/entities.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/run-plan.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/runs.js", import.meta.url), "utf8"),
  ].join("\n");
  assert.match(source, /search\.type = "submit"/);
  assert.match(source, /apply\.type = "submit"/);
  assert.match(source, /button\("Start update"/);
  assert.match(source, /button\("Load earlier data"/);
  assert.match(source, /First annual archive/);
  assert.match(source, /Complete sales history/);
  assert.match(source, /Preview update/);
  assert.match(source, /link\("Update history"/);
  assert.match(source, /`#ai\/release:\$\{linkedRelease\.id\}\?goal=\$\{failed \? "quality" : "compare"\}`/);
});

test("production frontend imports focused core and component modules", async () => {
  const source = [
    await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/releases.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/evidence.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/ai-diagnosis.js", import.meta.url), "utf8"),
  ].join("\n");
  for (const modulePath of [
    "./core/api.js", "./core/dom.js", "./core/formats.js", "./core/forms.js",
    "./core/polling.js", "./core/router.js", "./components/forms.js",
    "./components/layout.js", "./components/states.js", "./components/tables.js",
  ]) assert.match(source, new RegExp(modulePath.replaceAll(".", "\\.")));
  assert.doesNotMatch(source, /from "\.\/core\.js"/);
  assert.match(source, /\.\/routes\/properties\.js/);
  assert.match(source, /\.\/routes\/releases\.js/);
  assert.match(source, /\.\/routes\/evidence\.js/);
  assert.match(source, /\.\/routes\/ai-diagnosis\.js/);
});

test("property discovery consumes shell search queries and stays product-facing", async () => {
  const source = await readFile(new URL("../../frontend/routes/properties.js", import.meta.url), "utf8");
  assert.match(source, /routeQuery\(location\.hash\)\.get\("q"\)/);
  assert.match(source, /if \(input\.value\) queueMicrotask/);
  assert.match(source, /Explore NSW properties/);
  assert.match(source, /which sources and research data are available/);
  assert.doesNotMatch(source, /Feature [1-5]|buyer features|Dossier report/);
  assert.match(source, /#properties\/\$\{encodeURIComponent\(item\.property_ref\)\}/);
  assert.match(source, /Property references and coordinates/);
  assert.match(source, /confidenceLabel/);
  assert.match(source, /Property identifiers and coordinates/);
  assert.doesNotMatch(source, /Advanced identity evidence/);
});

test("live acquisition controls use truthful runtime capability evidence", async () => {
  const app = [
    await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/run-plan.js", import.meta.url), "utf8"),
  ].join("\n");
  assert.match(app, /request\("runtime-capabilities"\)/);
  assert.match(app, /Official source imports are disabled in this workspace/);
  assert.match(app, /implemented_live_profiles/);
  assert.match(app, /liveOption\.disabled = !liveAvailable/);
  assert.match(app, /Maximum addresses/);
  assert.match(app, /cached_source_years/);
  assert.match(app, /Detected official archive years/);
});

test("AI review history is loaded from the shared service projection without redundant consent", async () => {
  const source = await readFile(new URL("../../frontend/routes/ai-diagnosis.js", import.meta.url), "utf8");
  assert.match(source, /request\("agent-runs\?limit=10"\)/);
  assert.match(source, /disclosurePanel\("Recent AI reviews"/);
  assert.match(source, /`#ai\/\$\{run\.id\}`/);
  assert.match(source, /selectedAgentRun/);
  assert.match(source, /OBJECTIVES = Object\.freeze/);
  assert.doesNotMatch(source, /el\("textarea"\)/);
  assert.doesNotMatch(source, /review-acknowledgement|type = "checkbox"/);
  assert.match(source, /url\.searchParams\.set\("run", runId\)/);
  assert.match(source, /nextAgentPollDelay/);
  assert.match(source, /recordedSteps\?\.length \? recordedSteps : events/);
  assert.match(source, /aria-live/);
  assert.match(source, /Recommended next step/);
  assert.match(source, /The review recovered from/);
  assert.match(source, /recommended_next_step/);
  assert.match(source, /function traceStep/);
});

test("specialist detail views require an exact data update", async () => {
  const source = await readFile(new URL("../../frontend/routes/evidence.js", import.meta.url), "utf8");
  assert.match(source, /Choose a data update/);
  assert.match(source, /The selected update has no recorded/);
  assert.match(source, /#\$\{kind\}\/\$\{run\.id\}/);
});
