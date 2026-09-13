import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { requestActiveDialogClose, runDialogForm } from "../../frontend/components/dialogs.js";
import {
  createDrawerController,
  createTableRegion,
  createToastController,
} from "../../../shared/frontend/browser/index.js";

import {
  ApiError,
  actionAvailability,
  collection,
  confidenceLabel,
  createGenerationGuard,
  createLatestRequestGuard,
  coverageRows,
  displayName,
  durationMilliseconds,
  entity,
  formatBytes,
  formatDuration,
  humanise,
  FieldValidationError,
  formState,
  formStateChanged,
  isPsiJob,
  isSchoolsJob,
  INTERRUPTED_DETAIL_RECONCILIATION_LIMIT,
  liveProfileLabel,
  nextAgentPollDelay,
  nextPollDelay,
  nextRunDetailPollDelay,
  parseJsonField,
  parseIntegerField,
  parseJsonTextList,
  propertySearchQuery,
  psiYearRange,
  queryString,
  releaseComparison,
  retainRecent,
  researchAreaLabel,
  reportReleaseRows,
  requestJson,
  parseRoute,
  routeQuery,
  stateLabel,
} from "../../frontend/core.js";
import {
  acceptedReleaseReferences,
  agentRunReferences,
  createFeature1ShellAdapter,
} from "../../frontend/integration/shell.js";
import {
  assistantContextFromHash, assistantDraftFromHash, FEATURE_ASSISTANT_CONTEXTS,
  FEATURE_ASSISTANT_SCOPES,
} from "../../frontend/integration/assistant.js";
import {
  activePublicationOperation,
  createPublicationAttemptKeys,
  nextPublicationPollDelay,
  PUBLICATION_POLL_LIMIT,
  publicationDisplayState,
  reconcilePublication,
} from "../../frontend/core/publication.js";
import {
  consumerImportStatusPath,
  publicationSuccessMessage,
  reconcilePublicationTimeout,
} from "../../frontend/routes/release-publication.js";
import {
  failureExplanationDraft, reconcileTimelineTask, runFailureSummary,
} from "../../frontend/core/run-failure.js";
import { activityLine, mergeActivity, taskProgress } from "../../frontend/core/run-progress.js";
import { notificationLink, notificationTitle, reconcileNotifications } from "../../frontend/core/notifications.js";
import {
  catalogueIndex,
  groupCatalogueItems,
  groupJobItems,
  presentationFor,
  presentedName,
} from "../../frontend/core/catalogue.js";

test("catalogue presentation groups datasets and preserves customized operation names", () => {
  const payload = {
    groups: [
      { key: "foundational-property", label: "Foundational property data", description: "Core records." },
      { key: "economic-context", label: "Economic context", description: "Economic series." },
    ],
    datasets: [
      {
        source_key: "gnaf-nsw",
        job_profile: "gnaf-update",
        group_key: "foundational-property",
        display_name: "G-NAF addresses",
        purpose: "Foundational address identity and location.",
        default_names: ["G-NAF Open NSW", "Old G-NAF update"],
      },
      {
        source_key: "abs-cpi",
        job_profile: "cpi-update",
        group_key: "economic-context",
        display_name: "Inflation context (ABS CPI)",
        purpose: "Consumer price indexes.",
        default_names: ["Old CPI update"],
      },
    ],
  };
  const index = catalogueIndex(payload);
  assert.equal(presentationFor(index, "gnaf-nsw").display_name, "G-NAF addresses");
  assert.equal(presentedName(presentationFor(index, "gnaf-nsw"), "G-NAF Open NSW"), "G-NAF addresses");
  assert.equal(presentedName(presentationFor(index, "gnaf-nsw"), "Team custom G-NAF"), "Team custom G-NAF");
  assert.deepEqual(
    groupCatalogueItems([{ source_key: "abs-cpi" }, { source_key: "gnaf-nsw" }], payload, (item) => item.source_key).map((group) => group.label),
    ["Foundational property data", "Economic context"],
  );
  const groupedJobs = groupJobItems([
    { profile_key: "cpi-update", name: "Old CPI update" },
    { profile_key: "gnaf-update", name: "My address update" },
  ], payload);
  assert.equal(groupedJobs[0].items[0].item.name, "My address update");
  assert.equal(presentedName(groupedJobs[0].items[0].presentation, "My address update"), "My address update");
  assert.equal(presentedName(groupedJobs[1].items[0].presentation, "Old CPI update"), "Inflation context (ABS CPI)");
});

test("progress separates worker liveness from advancement and ignores old queued counters", () => {
  const now = Date.parse("2026-09-09T12:00:00Z");
  const task = { status: "running", started_at: now - 300000, heartbeat_at: now - 2000, progress_updated_at: now - 1000, progress_changed_at: now - 180000, progress_rows: 50, progress_total_rows: 100 };
  assert.equal(taskProgress(task, now).stalled, true);
  assert.equal(taskProgress(task, now).stale, false);
  assert.equal(taskProgress(task, now).ratio, .5);
  assert.equal(taskProgress({ ...task, heartbeat_at: now - 60000 }, now).stale, true);
  const pending = taskProgress({ ...task, status: "pending", rows_out: 1000 }, now);
  assert.equal(pending.rows, 0);
  assert.equal(pending.ratio, null);
  assert.equal(pending.elapsed, null);
  assert.equal(taskProgress({ ...task, progress_total_rows: null }, now).ratio, null);
});

test("activity merges overlapping windows, bounds retained entries and exports only display fields", () => {
  const entries = Array.from({ length: 1100 }, (_, id) => ({ id, task_id: "task", stage: "import", status: "running", rows_processed: id }));
  const merged = mergeActivity(entries.slice(0, 900), entries.slice(800));
  assert.equal(merged.length, 1000);
  assert.equal(merged[0].id, 100);
  assert.equal(merged.at(-1).id, 1099);
  assert.equal(activityLine({ ...entries[0], lease_token: "SECRET", error_json: { message: "PRIVATE" } }).includes("SECRET"), false);
  assert.equal(activityLine({ ...entries[0], error_json: { message: "PRIVATE" } }).includes("PRIVATE"), false);
});

test("notifications ignore historical completion then persist and deduplicate observed transitions", () => {
  const run = { id: "one", status: "running", requested_at: "2026-09-09T11:00:00Z" };
  const now = Date.parse("2026-09-09T12:00:00Z");
  const first = reconcileNotifications(null, [run, { ...run, id: "old", status: "failed" }], now);
  assert.equal(first.added.length, 0);
  const done = { ...run, status: "succeeded", finished_at: "2026-09-09T12:01:00Z" };
  const completed = reconcileNotifications(JSON.parse(JSON.stringify(first.state)), [done], now + 60000);
  assert.equal(completed.added.length, 1);
  completed.state.items[0].read = true;
  const repeated = reconcileNotifications(completed.state, [done], now + 90000);
  assert.equal(repeated.added.length, 0);
  assert.equal(repeated.state.items[0].read, true);
});

test("notifications catch short jobs between polls and retain only fifty outcomes", () => {
  const now = Date.parse("2026-09-09T12:00:00Z");
  const first = reconcileNotifications(null, [], now);
  const runs = Array.from({ length: 70 }, (_, id) => ({ id: String(id), status: "failed", requested_at: new Date(now + 1000).toISOString() }));
  const next = reconcileNotifications(first.state, runs, now + 15000);
  assert.equal(next.added.length, 70);
  assert.equal(next.state.items.length, 50);
  assert.equal(reconcileNotifications(next.state, runs, now + 30000).added.length, 0);
});

test("publication and downstream notifications use release links and distinct outcomes", () => {
  const now = Date.parse("2026-09-09T12:00:00Z");
  const state = reconcileNotifications(null, [], now).state;
  const result = reconcileNotifications(state, [{ id: "publication:one", target_id: "release-one", kind: "publication", status: "published", requested_at: "2026-01-01", activity_at: new Date(now + 1000).toISOString() }, { id: "delivery:two", target_id: "release-two", kind: "delivery", status: "failed", activity_at: new Date(now + 1000).toISOString() }], now + 2000);
  assert.equal(result.added.length, 2);
  assert.equal(notificationLink(result.added[0]), "#releases/release-one");
  assert.match(notificationTitle(result.added[1]), /downstream delivery failed/);
  assert.equal(reconcileNotifications(result.state, [], now + 3000).added.length, 0);
});

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

test("publication retries retain one key until the outcome is definitive", () => {
  let sequence = 0;
  const attempts = createPublicationAttemptKeys(() => `request-${++sequence}`);
  const release = { id: "release-1", version: 4 };

  assert.equal(attempts.acquire(release).value, "publish-release-1:v4-request-1");
  assert.equal(attempts.acquire(release).value, "publish-release-1:v4-request-1");
  attempts.clear(release);
  assert.equal(attempts.acquire(release).value, "publish-release-1:v4-request-2");
});

test("publication timeout reconciliation distinguishes durable progress from failure", () => {
  assert.equal(reconcilePublication({ release: { status: "accepted" }, activations: [] }), "completed");
  assert.equal(reconcilePublication({ release: { status: "awaiting_review" }, activations: [{ status: "running" }] }), "pending");
  assert.equal(reconcilePublication({ release: { status: "awaiting_review" }, activations: [{ status: "failed" }] }), "failed");
  assert.equal(reconcilePublication({ release: { status: "awaiting_review" }, activations: [] }), "unknown");
});

test("consumer import delivery states reconcile without claiming activation completed", () => {
  for (const status of [
    "queued", "claimed", "polling", "receipt_pending", "activation_pending", "interrupted",
    "activation_queued",
  ]) {
    assert.equal(reconcilePublication({ consumer_import: { status } }), "pending");
  }
  for (const status of ["failed", "rejected"]) {
    assert.equal(reconcilePublication({
      publication_status: "pending",
      consumer_imports: [{ status }],
    }), "failed");
  }
  assert.equal(reconcilePublication({
    consumer_import: { status: "activation_queued" },
    activation: { status: "running" },
  }), "pending");
  assert.equal(reconcilePublication({
    consumer_import: { status: "activation_queued" },
    activation: { status: "succeeded" },
  }), "completed");
  assert.equal(reconcilePublication({ publication_status: "completed" }), "completed");
  assert.equal(reconcilePublication({
    consumer_imports: [{ status: "failed" }, { status: "polling" }],
  }), "pending");
});

test("publication polling backs off, pauses while hidden, and follows long imports", () => {
  assert.equal(nextPublicationPollDelay(0, "pending"), 1500);
  assert.equal(nextPublicationPollDelay(6, "pending"), 3000);
  assert.equal(nextPublicationPollDelay(18, "pending"), 10000);
  assert.equal(nextPublicationPollDelay(0, "completed"), null);
  assert.equal(nextPublicationPollDelay(0, "failed"), null);
  assert.equal(nextPublicationPollDelay(1, "pending", { visible: false }), null);
  assert.equal(nextPublicationPollDelay(PUBLICATION_POLL_LIMIT, "pending"), 30000);
});

test("a retried consumer delivery takes precedence over its historical failed activation", () => {
  assert.equal(reconcilePublication({
    release: { status: "awaiting_review" },
    activations: [{ status: "failed" }],
    consumer_imports: [{ status: "activation_pending" }],
  }), "pending");
});

test("publication labels reflect approval and background work without changing review controls", () => {
  const release = { status: "awaiting_review" };
  assert.equal(publicationDisplayState(release, "pending"), "publishing");
  assert.equal(publicationDisplayState(release, "failed"), "publication_failed");
  assert.equal(publicationDisplayState(release, "unknown"), "awaiting_review");
  assert.equal(publicationDisplayState({ status: "accepted" }, "completed"), "published");
  assert.equal(release.status, "awaiting_review");
});

test("publication operation selection and status paths use the durable fixed resource", () => {
  const selected = activePublicationOperation({
    consumer_imports: [{ id: "old", status: "failed" }, { id: "new", status: "polling" }],
  });
  assert.equal(selected.id, "new");
  assert.equal(activePublicationOperation({
    consumer_imports: [{ id: "old", status: "polling" }, { id: "new", status: "failed" }],
  }), null);
  const fixed = "/api/data-platform/v1/dataset-releases/release-1/consumer-imports/operation-1";
  assert.equal(consumerImportStatusPath("release-1", "operation-1", fixed), fixed);
  assert.equal(
    consumerImportStatusPath("release-1", "operation-1", "https://untrusted.test/status"),
    fixed,
  );
});

test("publication response messaging distinguishes completed from queued work", () => {
  assert.equal(
    publicationSuccessMessage({
      publication_status: "completed",
      activation: { status: "succeeded" },
    }),
    "Publication completed",
  );
  assert.equal(
    publicationSuccessMessage({
      publication_status: "pending",
      activation: { status: "queued" },
    }),
    "Publication queued",
  );
  assert.throws(
    () => publicationSuccessMessage({ activation: { status: "failed" } }),
    /fresh retry is safe/,
  );
});

test("failed publication timeout reconciliation permits a fresh retry", async () => {
  const cleared = [];
  const timeoutError = Object.assign(new Error("The request timed out after 10 seconds."), {
    status: 0,
  });

  await assert.rejects(
    reconcilePublicationTimeout({
      release: { id: "release-1", version: 4 },
      request: async () => ({
        body: {
          release: { status: "awaiting_review" },
          activations: [{ status: "failed" }],
        },
        requestId: "reconcile-request",
      }),
      publicationKeys: { clear: (identity) => cleared.push(identity) },
      key: { identity: "release-1:v4", value: "publish-release-1:v4-request-1" },
      showToast: () => assert.fail("failed publication must not show a success toast"),
      timeoutError,
    }),
    (error) => error === timeoutError
      && /Publication verification or activation failed/.test(error.message)
      && /fresh retry is safe/.test(error.message)
      && !/outcome is not known/.test(error.message),
  );
  assert.deepEqual(cleared, ["release-1:v4"]);
});

test("publication timeout reconciliation recognizes durable consumer delivery", async () => {
  const cleared = [];
  const toasts = [];
  const timeoutError = Object.assign(new Error("The request timed out after 10 seconds."), {
    status: 0,
  });
  const body = await reconcilePublicationTimeout({
    release: { id: "release-1", version: 4 },
    request: async () => ({
      body: {
        release: { status: "awaiting_review" },
        consumer_imports: [{ id: "operation-1", status: "polling" }],
      },
      requestId: "reconcile-request",
    }),
    publicationKeys: { clear: (identity) => cleared.push(identity) },
    key: { identity: "release-1:v4", value: "publish-release-1:v4-request-1" },
    showToast: (message) => toasts.push(message),
    timeoutError,
  });
  assert.equal(body.consumer_imports[0].status, "polling");
  assert.deepEqual(cleared, ["release-1:v4"]);
  assert.match(toasts[0], /durable artifact verification and accepted-version activation/);
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
  assert.deepEqual(parseRoute("#assistant"), { route: "assistant", id: "", action: "" });
  assert.deepEqual(parseRoute("#not-a-route"), { route: "properties", id: "", action: "" });
  assert.deepEqual(parseRoute(""), { route: "properties", id: "", action: "" });
  assert.equal(routeQuery("#sources?q=crime+data&status=active").get("q"), "crime data");
});

test("Feature 1 assistant wrapper projects only allowlisted typed page context", () => {
  const context = assistantContextFromHash("#assistant?route=runs/detail&ingestion_run_id=10000000-0000-4000-8000-000000000004&unknown=ignored&release_id=bad");
  assert.deepEqual(context, {
    route: "runs/detail",
    ingestion_run_id: "10000000-0000-4000-8000-000000000004",
  });
  assert.deepEqual(FEATURE_ASSISTANT_SCOPES.map((scope) => scope.id), ["feature"]);
  assert.deepEqual(FEATURE_ASSISTANT_CONTEXTS.map((contextOption) => contextOption.id), [
    "general", "release", "run", "property",
  ]);
  assert.deepEqual(FEATURE_ASSISTANT_CONTEXTS.slice(1).map((contextOption) => contextOption.context.route), [
    "releases/detail", "runs/detail", "properties/detail",
  ]);
  assert.deepEqual(assistantContextFromHash("#assistant?route=runs/detail&release_id=10000000-0000-4000-8000-000000000004"), {});
  assert.deepEqual(assistantContextFromHash("#assistant?route=made-up&ingestion_run_id=10000000-0000-4000-8000-000000000004"), {});
  assert.equal(
    assistantDraftFromHash("#assistant?draft=Explain+the+recorded+failure."),
    "Explain the recorded failure.",
  );
  assert.equal(assistantDraftFromHash(`#assistant?draft=${"x".repeat(2100)}`).length, 2000);
});

test("failed update summary prefers specific step evidence over a generic run error", () => {
  const summary = runFailureSummary(
    { error_json: { code: "stage_execution_failed", message: "Generic failure" } },
    [{
      stage: "import",
      status: "failed",
      error_json: {
        code: "canonical_record_invalid",
        message: "Import stopped because record 1978 postcode must contain four digits.",
      },
    }],
  );

  assert.deepEqual(summary, {
    code: "canonical_record_invalid",
    title: "Import could not continue",
    message: "Import stopped because record 1978 postcode must contain four digits.",
    cachedReplayRecommended: false,
  });
});

test("cached replay guidance is limited to the proven PSI postcode compatibility case", () => {
  const summary = runFailureSummary({
    error_json: {
      code: "psi_postcode_placeholder",
      message: "Historical PSI postcodes used short numeric placeholders.",
    },
  });

  assert.equal(summary.cachedReplayRecommended, true);
});

test("terminal parent state closes a stale active timeline task", () => {
  const runError = { code: "task_lease_expired", message: "The worker lease expired." };
  const task = reconcileTimelineTask(
    {
      status: "interrupted",
      last_activity_at: "2026-09-01T00:20:20+10:00",
      error_json: runError,
    },
    {
      status: "running",
      lease_expires_at: "2026-09-01T00:25:20+10:00",
      stage: "import",
    },
  );

  assert.equal(task.status, "interrupted");
  assert.equal(task.finished_at, "2026-09-01T00:25:20+10:00");
  assert.equal(task.error_json, runError);
});

test("failure explanation draft carries classified evidence and a read-only instruction", () => {
  const draft = failureExplanationDraft(
    { error_json: { code: "stage_execution_failed" } },
    [{
      stage: "quality",
      status: "failed",
      error_json: { code: "blocking_quality_failure", message: "A blocking check failed." },
    }],
  );

  assert.match(draft, /quality stage/i);
  assert.match(draft, /blocking_quality_failure/);
  assert.match(draft, /Do not retry, change, or publish data/);
});

test("JSON form fields reject arrays and invalid input", () => {
  assert.deepEqual(parseJsonField('{"locality":"Sydney"}', "Scope"), { locality: "Sydney" });
  assert.deepEqual(parseJsonField("", "Scope"), {});
  assert.throws(() => parseJsonField("[]", "Scope"), /Scope must be a JSON object/);
  assert.throws(() => parseJsonField("not json", "Scope"), /Scope must be a JSON object/);
});

test("Feature 1 form parsers reject coercion and explain the required correction", () => {
  assert.equal(propertySearchQuery("  11 Example Street  "), "11 Example Street");
  assert.equal(propertySearchQuery("Parramatta"), "Parramatta");
  assert.equal(propertySearchQuery("2000"), "2000");
  assert.throws(() => propertySearchQuery("x"), /2 to 200 characters/);
  for (const query of ["Sydney NSW", "Glebe", "Ryde", "St Marys", "Sydney 2000"]) {
    assert.equal(propertySearchQuery(query), query);
  }
  assert.throws(() => propertySearchQuery("street"), /distinctive locality/);
  assert.equal(parseIntegerField("12", "Rows", { minimum: 1 }), 12);
  assert.throws(() => parseIntegerField("12.5", "Rows", { minimum: 1 }), /whole number/);
  assert.throws(() => parseIntegerField("", "Rows", { minimum: 1 }), /at least 1/);
  assert.deepEqual(parseJsonTextList('["feature-1"]', "Research areas"), ["feature-1"]);
  assert.throws(() => parseJsonTextList("[]", "Research areas"), /non-empty JSON list/);
  assert.throws(() => parseJsonTextList('["a","b"]', "Research areas", "target_features", { maximum: 1 }), /at most 1/);
  assert.throws(() => parseJsonTextList('["a","a"]', "Research areas", "target_features", { unique: true }), /duplicate/);
  assert.throws(
    () => parseJsonField("[]", "Scope", "advanced_scope"),
    (error) => error instanceof FieldValidationError && error.fieldName === "advanced_scope" && /JSON object/.test(error.message),
  );
});

class FakeControl extends EventTarget {
  constructor({ name = "", value = "", type = "text", valid = true, label = name } = {}) {
    super();
    this.name = name;
    this.value = value;
    this.type = type;
    this.valid = valid;
    this.label = label;
    this.disabled = false;
    this.checked = false;
    this.dataset = {};
    this.style = {};
    this.attributes = new Map();
    this.offsetWidth = 120;
    this.textContent = "Save changes";
    this.focused = false;
    this.id = "";
  }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) || null; }
  removeAttribute(name) { this.attributes.delete(name); }
  setCustomValidity(message) { this.validationMessage = message; if (message) this.valid = false; else this.valid = true; }
  reportValidity() { this.reported = true; return this.valid; }
  focus() { this.focused = true; }
  closest() { return { querySelector: () => ({ textContent: this.label }) }; }
}

class FakeForm extends EventTarget {
  constructor(controls) {
    super();
    this.controls = controls;
    this.attributes = new Map();
    this.elements = [...controls];
    this.elements.namedItem = (name) => controls.find((control) => control.name === name) || null;
  }

  checkValidity() { return this.controls.every((control) => control.valid !== false); }
  querySelector(selector) {
    if (selector === ":invalid") return this.controls.find((control) => control.valid === false) || null;
    if (selector.includes("input:not")) return this.controls.find((control) => !control.disabled) || null;
    return null;
  }
  querySelectorAll(selector) { return selector.includes('value="cancel"') ? this.controls.filter((control) => control.value === "cancel") : []; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
}

class FakeDialog extends EventTarget {
  showModal() { this.open = true; }
  close(value = "") { this.returnValue = value; this.open = false; this.dispatchEvent(new Event("close")); }
}

function submitEvent(submitter) {
  const event = new Event("submit", { cancelable: true });
  Object.defineProperty(event, "submitter", { value: submitter });
  return event;
}

function fakeDialogFixture({ value = "unchanged", valid = true } = {}) {
  const field = new FakeControl({ name: "notes", value, valid, label: "Operator notes (required)" });
  const submit = new FakeControl({ name: "", type: "submit" }); submit.value = "save";
  const cancel = new FakeControl({ name: "", type: "submit" }); cancel.value = "cancel";
  const form = new FakeForm([field, submit, cancel]);
  const dialog = new FakeDialog();
  const errorHost = new FakeControl(); errorHost.textContent = "";
  return { field, submit, cancel, form, dialog, errorHost };
}

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(value) { this.values.add(value); }
  remove(value) { this.values.delete(value); }
  contains(value) { return this.values.has(value); }
}

class FakeElement extends EventTarget {
  constructor(ownerDocument = null) {
    super();
    this.ownerDocument = ownerDocument;
    this.attributes = new Map();
    this.classList = new FakeClassList();
    this.dataset = {};
    this.children = [];
    this.hidden = false;
    this.inert = false;
  }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  append(...children) { this.children.push(...children); }
  focus() { if (this.ownerDocument) this.ownerDocument.activeElement = this; this.focused = true; }
  querySelector() { return this.focusables?.[0] || null; }
  querySelectorAll() { return this.focusables || []; }
}

class FakeDocument extends EventTarget {
  constructor() {
    super();
    this.body = new FakeElement(this);
    this.activeElement = null;
  }
  createElement() { return new FakeElement(this); }
}

test("the mobile drawer removes closed links from the focus order and restores focus on Escape", async () => {
  const documentNode = new FakeDocument();
  const drawer = new FakeElement(documentNode);
  const first = new FakeElement(documentNode);
  const last = new FakeElement(documentNode);
  drawer.focusables = [first, last];
  const toggle = new FakeElement(documentNode);
  const scrim = new FakeElement(documentNode);
  const media = new EventTarget();
  media.matches = true;
  const controller = createDrawerController({ drawer, toggle, scrim, mediaQuery: media });
  assert.equal(drawer.inert, true);
  assert.equal(drawer.getAttribute("aria-hidden"), "true");
  controller.open();
  await Promise.resolve();
  assert.equal(drawer.inert, false);
  assert.equal(first.focused, true);
  const escape = new Event("keydown", { cancelable: true });
  Object.defineProperty(escape, "key", { value: "Escape" });
  documentNode.dispatchEvent(escape);
  assert.equal(drawer.inert, true);
  assert.equal(toggle.focused, true);
  assert.equal(documentNode.body.classList.contains("ps-drawer-open"), false);
});

test("shared feedback and table helpers are bounded", () => {
  const toast = new FakeElement();
  const controller = createToastController(toast, { duration: 20 });
  controller.show("Saved", { tone: "success" });
  assert.equal(toast.textContent, "Saved");
  assert.equal(toast.dataset.visible, "true");
  assert.equal(toast.hidden, false);
  controller.hide();
  assert.equal(toast.hidden, false);
  assert.equal(toast.dataset.visible, "false");
  assert.equal(toast.textContent, "");
  const documentNode = new FakeDocument();
  const table = new FakeElement(documentNode);
  const region = createTableRegion(table, "Saved updates", { className: "table-wrap" });
  assert.equal(region.getAttribute("role"), "region");
  assert.match(region.getAttribute("aria-label"), /Saved updates.*Scroll horizontally/);
  assert.equal(region.children.at(-1), table);
});

test("dialog keyboard submission is single-flight and closes only after success", async () => {
  const originalWindow = globalThis.window;
  globalThis.window = { confirm: () => true };
  const fixture = fakeDialogFixture();
  let calls = 0;
  let release;
  const operation = new Promise((resolve) => { release = resolve; });
  const result = runDialogForm({
    ...fixture,
    submitButton: fixture.submit,
    acceptedValue: "save",
    progressLabel: "Saving…",
    onSubmit: async () => { calls += 1; await operation; },
  });
  fixture.form.dispatchEvent(submitEvent(fixture.submit));
  fixture.form.dispatchEvent(submitEvent(fixture.submit));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls, 1);
  assert.equal(fixture.dialog.open, true);
  assert.equal(fixture.submit.disabled, true);
  assert.equal(fixture.submit.textContent, "Saving…");
  release();
  assert.equal(await result, true);
  assert.equal(fixture.dialog.open, false);
  globalThis.window = originalWindow;
});

test("dialog validation focuses the first invalid field before allowing retry", async () => {
  const originalWindow = globalThis.window;
  globalThis.window = { confirm: () => true };
  const fixture = fakeDialogFixture({ valid: false });
  let calls = 0;
  const result = runDialogForm({ ...fixture, submitButton: fixture.submit, acceptedValue: "save", onSubmit: async () => { calls += 1; } });
  fixture.form.dispatchEvent(submitEvent(fixture.submit));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(calls, 0);
  assert.equal(fixture.field.focused, true);
  assert.match(fixture.errorHost.textContent, /correct Operator notes/);
  fixture.field.valid = true;
  fixture.form.dispatchEvent(submitEvent(fixture.submit));
  assert.equal(await result, true);
  assert.equal(calls, 1);
  globalThis.window = originalWindow;
});

test("recoverable server failure retains values and supports retry without double submit", async () => {
  const originalWindow = globalThis.window;
  globalThis.window = { confirm: () => true };
  const fixture = fakeDialogFixture({ value: "carefully entered evidence" });
  let calls = 0;
  const result = runDialogForm({
    ...fixture,
    submitButton: fixture.submit,
    acceptedValue: "save",
    onSubmit: async () => {
      calls += 1;
      if (calls === 1) throw Object.assign(new Error("Conflict with a newer version."), { requestId: "req-conflict" });
    },
  });
  fixture.form.dispatchEvent(submitEvent(fixture.submit));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(fixture.dialog.open, true);
  assert.equal(fixture.field.value, "carefully entered evidence");
  assert.match(fixture.errorHost.textContent, /values are still here/);
  assert.match(fixture.errorHost.textContent, /req-conflict/);
  fixture.form.dispatchEvent(submitEvent(fixture.submit));
  assert.equal(await result, true);
  assert.equal(calls, 2);
  globalThis.window = originalWindow;
});

test("Escape and close warn only after meaningful values change", async () => {
  let allowDiscard = false;
  let prompts = 0;
  const fixture = fakeDialogFixture();
  const initial = formState(fixture.form);
  const result = runDialogForm({ ...fixture, submitButton: fixture.submit, acceptedValue: "save", onSubmit: async () => {} });
  const unchangedCancel = new Event("cancel", { cancelable: true });
  fixture.dialog.dispatchEvent(unchangedCancel);
  assert.equal(await result, false);
  assert.equal(prompts, 0);
  assert.equal(formStateChanged(initial, formState(fixture.form)), false);

  const dirtyFixture = fakeDialogFixture();
  const dirtyResult = runDialogForm({
    ...dirtyFixture,
    submitButton: dirtyFixture.submit,
    acceptedValue: "save",
    confirmDiscard: async () => { prompts += 1; return allowDiscard; },
    onSubmit: async () => {},
  });
  dirtyFixture.field.value = "changed by keyboard";
  dirtyFixture.dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(dirtyFixture.dialog.open, true);
  assert.equal(prompts, 1);
  allowDiscard = true;
  dirtyFixture.form.dispatchEvent(submitEvent(dirtyFixture.cancel));
  await Promise.resolve();
  assert.equal(await dirtyResult, false);
  assert.equal(prompts, 2);
});

test("dirty dialogs use the native discard confirmation without losing the open form", async () => {
  const fixture = fakeDialogFixture();
  let resolveDiscard;
  let prompts = 0;
  const result = runDialogForm({
    ...fixture,
    submitButton: fixture.submit,
    acceptedValue: "save",
    confirmDiscard: () => {
      prompts += 1;
      return new Promise((resolve) => { resolveDiscard = resolve; });
    },
    onSubmit: async () => {},
  });
  fixture.field.value = "changed by keyboard";
  fixture.dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
  await Promise.resolve();
  assert.equal(fixture.dialog.open, true);
  assert.equal(prompts, 1);
  fixture.dialog.dispatchEvent(new Event("cancel", { cancelable: true }));
  assert.equal(prompts, 1);
  resolveDiscard(true);
  assert.equal(await result, false);
});

test("the latest guarded close observes a declined or accepted discard decision", async () => {
  const fixture = fakeDialogFixture();
  let resolveDiscard;
  const decisions = [];
  const result = runDialogForm({
    ...fixture,
    submitButton: fixture.submit,
    acceptedValue: "save",
    confirmDiscard: () => new Promise((resolve) => { resolveDiscard = resolve; }),
    onSubmit: async () => {},
  });
  fixture.field.value = "changed by keyboard";
  assert.equal(requestActiveDialogClose(fixture.dialog, { onDiscardDecision: (value) => decisions.push(["old", value]) }), false);
  await Promise.resolve();
  assert.equal(requestActiveDialogClose(fixture.dialog, { onDiscardDecision: (value) => decisions.push(["latest", value]) }), false);
  resolveDiscard(false);
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(decisions, [["latest", false]]);
  assert.equal(fixture.dialog.open, true);

  assert.equal(requestActiveDialogClose(fixture.dialog, { onDiscardDecision: (value) => decisions.push(["accepted", value]) }), false);
  await Promise.resolve();
  resolveDiscard(true);
  assert.equal(await result, false);
  assert.deepEqual(decisions, [["latest", false], ["accepted", true]]);
});

test("job source detection and explicit year partitions are bounded", () => {
  assert.equal(isPsiJob({ profile_key: "nsw-psi-sales-year" }), true);
  assert.equal(isPsiJob({ adapter_key: "schools-csv" }), false);
  assert.equal(isSchoolsJob({ import_profile_key: "schools-master" }), true);
  assert.equal(isSchoolsJob({ adapter_key: "gnaf-bulk" }), false);
  assert.equal(liveProfileLabel("gnaf-nsw"), "Complete official NSW G-NAF address registry");
  assert.equal(liveProfileLabel("bocsar-sparse"), "Complete official BOCSAR postcode + suburb datasets");
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

test("interrupted detail reconciliation is slow and explicitly bounded", () => {
  assert.equal(nextPollDelay("interrupted"), null);
  assert.equal(nextRunDetailPollDelay("interrupted"), 15000);
  assert.equal(nextRunDetailPollDelay("interrupted", 1), 30000);
  assert.equal(nextRunDetailPollDelay("interrupted", 0, true), 60000);
  assert.equal(nextRunDetailPollDelay(
    "interrupted", 0, false, INTERRUPTED_DETAIL_RECONCILIATION_LIMIT - 1,
  ), 15000);
  assert.equal(nextRunDetailPollDelay(
    "interrupted", 0, false, INTERRUPTED_DETAIL_RECONCILIATION_LIMIT,
  ), null);
  assert.equal(nextRunDetailPollDelay("succeeded"), null);
  assert.equal(nextRunDetailPollDelay("failed"), null);
  assert.equal(nextRunDetailPollDelay("cancelled"), null);
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
  const firstEpoch = guard.capture();
  const secondEpoch = guard.begin();
  assert.equal(guard.isCurrent(first), false);
  assert.equal(firstEpoch.isCurrent(), false);
  assert.equal(secondEpoch.isCurrent(), true);
  assert.equal(secondEpoch.generation, 2);
  assert.equal(guard.current(), 2);
});

test("latest-request guards reject slow refreshes after a newer refresh starts", async () => {
  const guard = createLatestRequestGuard();
  const slow = guard.begin();
  const fast = guard.begin();
  await Promise.resolve();
  assert.equal(slow.signal.aborted, true);
  assert.equal(slow.isCurrent(), false);
  assert.equal(fast.isCurrent(), true);
  fast.finish();
});

test("recent feed caches evict the least recently used run", () => {
  const cache = new Map();
  for (const id of ["run-1", "run-2", "run-3", "run-4"]) {
    retainRecent(cache, id, { id }, 3);
  }
  assert.deepEqual([...cache.keys()], ["run-2", "run-3", "run-4"]);
  retainRecent(cache, "run-2", cache.get("run-2"), 3);
  retainRecent(cache, "run-5", { id: "run-5" }, 3);
  assert.deepEqual([...cache.keys()], ["run-4", "run-2", "run-5"]);
});

test("the application shell exposes keyboard landmarks, live status and native dialogs", async () => {
  const html = await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8");
  const app = await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8");
  assert.match(html, /href="#main-content">Skip to main content/);
  assert.match(html, /<nav>/);
  assert.match(html, /id="header-property-search"/);
  assert.match(html, /aria-label="PropertyScope navigation"/);
  assert.match(html, /Current research area[^<]*<\/b> Property data/);
  assert.match(html, /Search Property data by address or reference/);
  assert.match(html, /Back to research workspace/);
  assert.match(html, /data-icon="mapPin"/);
  assert.match(html, /data-icon="overview"/);
  assert.doesNotMatch(html, /<a href="#properties" aria-current="page">Property search<\/a>/);
  assert.doesNotMatch(html, /Accepted data stays available during review/);
  assert.doesNotMatch(html, /Assisted diagnosis|Advanced operations/);
  assert.match(html, /<main id="main-content" tabindex="-1">/);
  assert.match(html, /id="live-region"[^>]+aria-live="polite"/);
  assert.match(html, /id="toast"[^>]+role="status"(?![^>]+hidden)/);
  assert.match(html, /<dialog id="entity-dialog"/);
  assert.match(html, /<dialog id="action-dialog"/);
  assert.match(html, /<dialog id="discard-dialog"/);
  assert.match(html, /aria-labelledby="action-title" aria-describedby="action-description"/);
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
  assert.match(app, /createDrawerController\(\{/);
  assert.match(app, /hydrateIcons\(\)/);
  assert.match(app, /confirmDiscard/);
  assert.match(app, /pendingGuardedNavigation\?\.generation !== generation/);
  assert.match(app, /location\.hash = pending\.requestedHash/);
  assert.match(app, /mediaQuery: window\.matchMedia\("\(max-width: 780px\)"\)/);
});

test("tables use named contained scroll regions and native links instead of interactive rows", async () => {
  const tables = await readFile(new URL("../../frontend/components/tables.js", import.meta.url), "utf8");
  const runs = await readFile(new URL("../../frontend/routes/runs.js", import.meta.url), "utf8");
  const sharedCore = await readFile(new URL("../../../shared/frontend/core.js", import.meta.url), "utf8");
  assert.match(tables, /createTableRegion\(table, captionText/);
  assert.match(sharedCore, /heading\.scope = "col"/);
  assert.match(runs, /const runLink = link\(/);
  assert.doesNotMatch(runs, /row\.tabIndex|row\.addEventListener/);
});

test("the frontend proxy keeps browser traffic on the public backend boundary", async () => {
  const nginx = await readFile(new URL("../../frontend/nginx.conf", import.meta.url), "utf8");
  assert.match(nginx, /location \/api\/data-platform\//);
  assert.match(nginx, /location \/fragments\/data-platform\//);
  assert.match(nginx, /resolver 127\.0\.0\.11 valid=10s ipv6=off/);
  assert.match(nginx, /set \$data_platform_upstream http:\/\/f1-backend:5201/);
  assert.match(nginx, /proxy_pass \$data_platform_upstream/);
  assert.doesNotMatch(nginx, /propertyscope-database/);
  assert.match(nginx, /https:\/\/tiles\.openfreemap\.org/);
  assert.match(nginx, /worker-src blob:/);
});

test("the frontend exposes only fixed JSON health routes", async () => {
  const nginx = await readFile(new URL("../../frontend/nginx.conf", import.meta.url), "utf8");
  assert.match(nginx, /location = \/health\/live/);
  assert.match(nginx, /location = \/health\/ready/);
  assert.match(nginx, /location ~ \^\/health/);
  assert.match(nginx, /Only \/health\/live and \/health\/ready are supported/);
  assert.match(nginx, /default_type application\/problem\+json/);
  assert.match(nginx, /return 404 '[^']*"code":"route_not_found"/);
  assert.doesNotMatch(nginx, /location \/health\//);
});

test("Source CRUD is exclusively wired through local HTMX fragments", async () => {
  const html = await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8");
  const app = await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8");
  const sourceRoute = await readFile(new URL("../../frontend/routes/sources-htmx.js", import.meta.url), "utf8");
  assert.match(html, /vendor\/htmx-2\.0\.10\.min\.js/);
  assert.match(html, /"allowEval":false/);
  assert.match(app, /route === "sources"\) renderSources\(id\)/);
  assert.doesNotMatch(app, /SOURCE_FIELDS|openEntityDialog\("source"/);
  assert.match(sourceRoute, /\/fragments\/data-platform\/v1\/sources/);
  assert.match(sourceRoute, /htmx:beforeSwap/);
  assert.match(sourceRoute, /contentType\.startsWith\("text\/html"\)/);
  assert.match(sourceRoute, /path\.startsWith\(FRAGMENT_BASE\)/);
  assert.doesNotMatch(sourceRoute, /\/api\/data-platform\/v1\/sources/);
});

test("property discovery uses the shared mapping public entrypoint", async () => {
  const html = await readFile(new URL("../../frontend/index.html", import.meta.url), "utf8");
  const properties = await readFile(new URL("../../frontend/routes/properties.js", import.meta.url), "utf8");
  assert.match(html, /mapping\/mapping\.css/);
  assert.match(properties, /from "\.\.\/mapping\/index\.js"/);
  assert.match(properties, /createOpenFreeMapProvider\(\)/);
  assert.match(properties, /pointFeature\(/);
  assert.doesNotMatch(properties, /map-pin/);
});

test("Feature 1 owns its Shared-shell response and workflow adapter", () => {
  const releases = acceptedReleaseReferences({ items: [{
    id: "release-1", dataset_id: "addresses", target_feature: "feature-1",
    release_version: "2026.08", record_count: 10, content_sha256: "abc", accepted_at: "2026-08-15T00:00:00Z",
  }] });
  assert.deepEqual(releases[0], {
    id: "release-1", dataset: "addresses", area: "Property data", version: "2026.08",
    records: 10, acceptedAt: "2026-08-15T00:00:00Z", coverage: "unknown", hash: "abc",
  });
  const integration = createFeature1ShellAdapter({ propertyDiscovery: "/custom/#properties" });
  assert.equal(
    integration.primarySearchHref("1 Farrer Place", "https://example.test/"),
    "https://example.test/custom/#properties?q=1%20Farrer%20Place",
  );
  assert.equal(integration.statusDependencies({ payload: { dependencies: { database: true } } })[0].rawStatus, true);
  assert.deepEqual(
    integration.statusDependencies({ payload: { checks: { database: { status: "degraded", detail: "Recovery pending" } } } })[0],
    {
      name: "Property data store", kind: "Owned dependency", owner: "Property data service",
      rawStatus: "degraded", detail: "Recovery pending",
    },
  );
  assert.deepEqual(integration.evidence.action, { label: "Open Property data", href: integration.links.dataOperations });
  assert.equal(integration.evidence.agentRuns.href("run-1", "https://example.test/").includes("feature_key=student-1-propertyscope-data-platform"), true);
  assert.equal(agentRunReferences({ items: [{ id: "run-1", feature_key: "feature-1" }, { id: "other", feature_key: "feature-4" }] }).length, 1);
});

test("coverage matrices flatten into accessible table rows", () => {
  assert.deepEqual(coverageRows({ matrix: { crime: { Sydney: "accepted", Dubbo: "partial" } } }), [
    { dataset: "crime", locality: "Sydney", status: "accepted" },
    { dataset: "crime", locality: "Dubbo", status: "partial" },
  ]);
  assert.deepEqual(coverageRows({ items: [{ dataset: "schools", status: "accepted" }] }), [{ dataset: "schools", status: "accepted" }]);
});

test("formatting pairs states with text and handles byte boundaries", () => {
  assert.deepEqual(stateLabel("imported"), { text: "Imported", tone: "positive", symbol: "✓" });
  assert.deepEqual(stateLabel("delivered"), { text: "Delivered", tone: "positive", symbol: "✓" });
  assert.deepEqual(stateLabel("accepted"), { text: "Published", tone: "positive", symbol: "✓" });
  assert.deepEqual(stateLabel("stale"), { text: "Stale", tone: "warning", symbol: "△" });
  assert.equal(formatBytes(1024), "1.00 KB");
  assert.equal(formatBytes(10 * 1024 * 1024), "10.0 MB");
  assert.equal(confidenceLabel(0.85714287), "Strong match (86%)");
  assert.equal(confidenceLabel(null), "Match confidence not supplied");
  assert.equal(researchAreaLabel("feature-1"), "Property data");
  assert.equal(researchAreaLabel("feature-4"), "Site & planning");
  assert.equal(researchAreaLabel("future-area"), "Future area");
  assert.equal(displayName("Deterministic property critical-path fixture"), "Example property records update");
  assert.equal(displayName("G-NAF NSW address registry"), "G-NAF NSW address registry");
  assert.equal(humanise("awaiting_review"), "Awaiting review");
  assert.equal(humanise("full_snapshot"), "Full snapshot");
  assert.equal(durationMilliseconds("2026-08-29T00:00:00Z", "2026-08-29T00:01:05Z"), 65_000);
  assert.equal(formatDuration("2026-08-29T00:00:00Z", "2026-08-29T00:01:05Z"), "1m 5s");
  assert.equal(formatDuration("2026-08-29T00:00:00Z", "2026-08-29T02:03:00Z"), "2h 3m");
  assert.equal(formatDuration(null, "2026-08-29T00:00:00Z"), "Not recorded");
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

test("release details render bounded paginated dataset records", async () => {
  const releases = (await Promise.all(["releases.js", "release-preview.js"].map((name) =>
    readFile(new URL(`../../frontend/routes/${name}`, import.meta.url), "utf8")))).join("\n");
  assert.match(releases, /dataset-releases\/\$\{id\}\/records\?limit=25&offset=0/);
  assert.match(releases, /function releasePreviewPanel/);
  assert.match(releases, /No other version is included/);
  assert.match(releases, /Next page/);
});

test("release publication renders durable delivery evidence and polls only pending work", async () => {
  const releases = await readFile(new URL("../../frontend/routes/releases.js", import.meta.url), "utf8");
  assert.match(releases, /body\.consumer_imports \|\| \[\]/);
  assert.match(releases, /Consumer import operations/);
  assert.match(releases, /publicationInProgress/);
  assert.match(releases, /consumerImportStatusPath\(/);
  assert.match(releases, /request\(statusPath\)/);
  assert.match(releases, /nextPublicationPollDelay\(/);
  assert.match(releases, /visibilitychange/);
  assert.match(releases, /PUBLICATION_POLL_LIMIT/);
  assert.match(releases, /current version remains live/);
  assert.doesNotMatch(releases, /continues in the database loader/);
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

test("live acquisition controls default to full data and offer bounded PSI archive years", async () => {
  const app = [
    await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8"),
    await readFile(new URL("../../frontend/routes/run-plan.js", import.meta.url), "utf8"),
  ].join("\n");
  assert.match(app, /profile: "full-data", all_records: true/);
  assert.match(app, /Complete dataset: all available source records/);
  assert.match(app, /profile: "psi-year-range"/);
  assert.match(app, /First archive year/);
  assert.match(app, /not an exact contract-date range/);
  assert.doesNotMatch(app, /Maximum addresses|maximum-records/);
  assert.doesNotMatch(app, /request\("runtime-capabilities"\)/);
});

test("Feature 1 exports the manifest-declared domain-neutral evidence hook", async () => {
  const adapter = await readFile(
    new URL("../../frontend/integration/shell.js", import.meta.url),
    "utf8",
  );
  assert.match(adapter, /export function createShellEvidenceAdapter/);
});

test("overview problem notice uses a labelled responsive list", async () => {
  const source = await readFile(new URL("../../frontend/routes/overview.js", import.meta.url), "utf8");
  const styles = await readFile(new URL("../../frontend/styles.css", import.meta.url), "utf8");

  assert.match(source, /aria-labelledby.*overview-problems-heading/);
  assert.match(source, /el\("ul", "problem-links"\)/);
  assert.match(source, /append\(item, link/);
  assert.match(styles, /\.overview-problems \{ display: grid;/);
  assert.match(styles, /\.overview-problems \{[^}]*margin-top: var\(--ps-space-4\);/);
  assert.match(styles, /\.problem-links \{ display: grid;/);
});


test("producer publication remains independent of downstream delivery", () => {
  for (const status of ["queued", "polling", "failed", "rejected", "delivered"]) {
    const body = {
      publication_policy: "producer-owned",
      release: { status: "awaiting_review" },
      consumer_imports: [{ status }],
    };
    assert.equal(reconcilePublication(body), "unknown");
    assert.equal(reconcilePublication({ ...body, release: { status: "accepted" } }), "completed");
    assert.equal(reconcilePublication({ ...body, activations: [{ status: "running" }] }), "pending");
    assert.equal(reconcilePublication({ ...body, activations: [{ status: "failed" }] }), "failed");
  }
});

test("activity handoff uses the mounted document base and preserves explicit scope", async () => {
  const { propertyActivityUrl } = await import("../../frontend/integration/activity.js");
  const integrated = new URL(propertyActivityUrl("run-one", {baseUrl: "https://example.test/features/data-platform/#assistant"}));
  assert.equal(integrated.origin, "https://example.test");
  assert.equal(integrated.pathname, "/operations/ai-mode/");
  assert.equal(integrated.searchParams.get("run"), "run-one");
  assert.equal(integrated.searchParams.get("feature_key"), "student-1-propertyscope-data-platform");
  const standalone = new URL(propertyActivityUrl("", {baseUrl: "http://localhost:5010/"}));
  assert.equal(standalone.port, "5100");
  const overridden = new URL(propertyActivityUrl("run", {baseUrl: "https://example.test/", activityUrl: "https://audit.test/operations/ai-mode/"}));
  assert.equal(overridden.origin, "https://audit.test");
  assert.throws(() => propertyActivityUrl("run", {baseUrl: "https://example.test/", activityUrl: "javascript:alert(1)"}), /HTTP/);
});


test("optional history denial cannot stop property search or return-context rendering", async () => {
  const { readHistoryState, replaceHistoryState } = await import("../../frontend/core/router.js");
  const denied = { get history() { throw new Error("History unavailable"); } };
  assert.deepEqual(readHistoryState(denied), {});
  assert.equal(replaceHistoryState({}, "#properties", denied), false);
  assert.equal(replaceHistoryState({}, "#properties", {}), false);
  const calls = [];
  const browser = { history: { state: { query: "2000" }, replaceState: (...args) => calls.push(args) } };
  assert.deepEqual(readHistoryState(browser), { query: "2000" });
  assert.equal(replaceHistoryState({ query: "2010" }, "#properties?q=2010", browser), true);
  assert.deepEqual(calls, [[{ query: "2010" }, "", "#properties?q=2010"]]);
});
