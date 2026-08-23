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
  entity,
  formatBytes,
  FieldValidationError,
  formState,
  formStateChanged,
  isPsiJob,
  isSchoolsJob,
  liveProfileLabel,
  nextAgentPollDelay,
  nextPollDelay,
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

test("Feature 1 form parsers reject coercion and explain the required correction", () => {
  assert.equal(propertySearchQuery("  11 Example Street  "), "11 Example Street");
  assert.throws(() => propertySearchQuery("x"), /2 to 200 characters/);
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

test("every existing Feature 1 form is wired to explicit retention and submission behavior", async () => {
  const sources = {
    shell: await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8"),
    forms: await readFile(new URL("../../frontend/components/forms.js", import.meta.url), "utf8"),
    entities: await readFile(new URL("../../frontend/routes/entities.js", import.meta.url), "utf8"),
    properties: await readFile(new URL("../../frontend/routes/properties.js", import.meta.url), "utf8"),
    plan: await readFile(new URL("../../frontend/routes/run-plan.js", import.meta.url), "utf8"),
    releases: await readFile(new URL("../../frontend/routes/releases.js", import.meta.url), "utf8"),
    runs: await readFile(new URL("../../frontend/routes/runs.js", import.meta.url), "utf8"),
    ai: await readFile(new URL("../../frontend/routes/ai-diagnosis.js", import.meta.url), "utf8"),
  };
  assert.match(sources.shell, /runDialogForm\(\{/); // source and job create/edit
  assert.match(sources.shell, /propertySearchQuery\(headerPropertyQuery\.value/); // header search
  assert.match(sources.forms, /Reset filters/); // source, job and release filters
  assert.match(sources.forms, /active-filters/);
  assert.match(sources.properties, /propertySearchQuery\(input\.value\)/); // property discovery
  assert.match(sources.properties, /createSubmissionGuard/);
  assert.match(sources.plan, /onConfirm: async \(\) =>/); // run planner and confirmation
  assert.match(sources.plan, /discardMessage: "Discard your changed update scope\?"/);
  assert.match(sources.entities, /onConfirm: \(\) => mutate\(`\$\{kind\}\/\$\{item\.id\}`/);
  assert.match(sources.releases, /runDialogForm\(\{/); // release create/edit
  assert.equal((sources.releases.match(/onConfirm: \(\) => mutate/g) || []).length, 4); // delete, submit, publish, reject
  assert.match(sources.runs, /onConfirm: async \(\) => \{ created = await mutate/);
  assert.match(sources.ai, /createSubmissionGuard/); // AI review
  assert.doesNotMatch(sources.shell, /entityDialog\.close\("save"\)/);
  assert.match(sources.shell, /requestActiveDialogClose/);
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

test("latest-request guards reject slow refreshes after a newer refresh starts", async () => {
  const guard = createLatestRequestGuard();
  const slow = guard.next();
  const fast = guard.next();
  await Promise.resolve();
  assert.equal(guard.isCurrent(slow), false);
  assert.equal(guard.isCurrent(fast), true);
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
  assert.match(app, /confirmDiscard/);
  assert.match(app, /pendingGuardedNavigation\?\.generation !== generation/);
  assert.match(app, /location\.hash = pending\.requestedHash/);
  assert.match(app, /mediaQuery: window\.matchMedia\("\(max-width: 780px\)"\)/);
});

test("property search has an explicit persistent label association", async () => {
  const source = await readFile(new URL("../../frontend/routes/properties.js", import.meta.url), "utf8");
  assert.match(source, /searchField\.htmlFor = "property-search-query"/);
  assert.match(source, /input\.id = "property-search-query"/);
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
  assert.match(nginx, /proxy_pass http:\/\/propertyscope-backend:5201/);
  assert.doesNotMatch(nginx, /propertyscope-database/);
  assert.match(nginx, /https:\/\/tiles\.openfreemap\.org/);
  assert.match(nginx, /worker-src blob:/);
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
  assert.deepEqual(stateLabel("accepted"), { text: "Published", tone: "positive", symbol: "✓" });
  assert.deepEqual(stateLabel("stale"), { text: "Stale", tone: "warning", symbol: "△" });
  assert.equal(formatBytes(1024), "1.00 KB");
  assert.equal(formatBytes(10 * 1024 * 1024), "10.0 MB");
  assert.equal(confidenceLabel(0.85714287), "Strong match (86%)");
  assert.equal(confidenceLabel(null), "Match confidence not supplied");
  assert.equal(researchAreaLabel("feature-1"), "Property data");
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
  assert.match(source, /properties\/\$\{encodedRef\}\/report-section/);
  assert.match(source, /New and published versions/);
  assert.match(source, /Data checks/);
  assert.match(source, /primaryCell\(releaseLink, release\.release_version \|\| "Version not recorded"\)/);
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

test("operator state routes preserve partial evidence and explain lifecycle context", async () => {
  const overview = await readFile(new URL("../../frontend/routes/overview.js", import.meta.url), "utf8");
  const entities = await readFile(new URL("../../frontend/routes/entities.js", import.meta.url), "utf8");
  const releases = await readFile(new URL("../../frontend/routes/releases.js", import.meta.url), "utf8");
  assert.match(overview, /projectOverviewFeeds/);
  assert.match(overview, /allUnavailable/);
  assert.match(overview, /runsAvailable \? active : "Unavailable"/);
  assert.match(overview, /Temporarily unavailable:/);
  assert.doesNotMatch(overview, /request\("overview"\)/);
  assert.match(entities, /Available processing options could not be checked/);
  assert.match(entities, /This data update is disabled/);
  assert.match(releases, /releaseLifecycleContext/);
  assert.match(releases, /primaryCell\(releaseLink, release\.release_version/);
});

test("run polling preserves the rendered view and isolates supporting feed failures", async () => {
  const runs = await readFile(new URL("../../frontend/routes/runs.js", import.meta.url), "utf8");
  assert.match(runs, /Promise\.allSettled/);
  assert.match(runs, /resolveFeed\(tasksResult, cache, "tasks"\)/);
  assert.match(runs, /Showing the last loaded details/);
  assert.match(runs, /captureRefreshState\(view\)/);
  assert.match(runs, /restoreRefreshState\(view, refreshState\)/);
  assert.match(runs, /Refresh delayed · retrying automatically/);
  assert.match(runs, /refreshGuard\.isCurrent\(refresh\)/);
});

test("route lifecycle titles and focuses the first page or error heading", async () => {
  const app = await readFile(new URL("../../frontend/app.js", import.meta.url), "utf8");
  assert.match(app, /view\.querySelector\("h1, h2"\)/);
  assert.match(app, /const retryRoute = \(\) => renderRoute\(\{ focus: true \}\)/);
  assert.equal([...app.matchAll(/rerender: retryRoute/g)].length, 8);
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
  assert.match(source, /refreshGuard\.isCurrent\(refresh\)/);
  assert.match(source, /captureTraceRefreshState\(host\)/);
  assert.match(source, /restoreTraceRefreshState\(host, refreshState\)/);
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
