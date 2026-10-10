import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";

import { MultiAgentApiError } from "./client.js";
import { createMultiAgentPanel } from "./panel.js";

const RUN_ID = "c17c66cc-6b40-4685-909a-440401ae8ec7";
const RELEASE_ID = "cb188a6e-613f-4f4e-b7b0-b827dd573869";

// A deliberately small, text-only DOM double: any attempt to render raw HTML fails a test.
class FakeText {
  constructor(text) { this.nodeType = 3; this.textContent = String(text); this.parent = null; }
}
class FakeElement {
  constructor(tag, documentRef) {
    this.tagName = tag.toUpperCase();
    this.ownerDocument = documentRef;
    this.children = [];
    this.parent = null;
    this.dataset = {};
    this.attributes = new Map();
    this.listeners = new Map();
    this.className = "";
    this.hidden = false;
    this.value = "";
    this.checked = false;
    this.disabled = false;
    this.open = false;
    const properties = new Map();
    // CSSOM custom properties only: the panel positions lane marks with them.
    this.style = { setProperty: (name, value) => properties.set(name, String(value)), getPropertyValue: (name) => properties.get(name) ?? "" };
  }
  get parentElement() { return this.parent; }
  remove() {
    if (this.parent) this.parent.children = this.parent.children.filter((item) => item !== this);
    this.parent = null;
  }
  set innerHTML(_value) { throw new Error("Raw HTML rendering is forbidden"); }
  get classList() {
    const node = this;
    const list = () => node.className.split(/\s+/).filter(Boolean);
    return {
      add: (...names) => { node.className = [...new Set([...list(), ...names])].join(" "); },
      remove: (...names) => { node.className = list().filter((name) => !names.includes(name)).join(" "); },
      contains: (name) => list().includes(name),
    };
  }
  get firstChild() { return this.children[0] || null; }
  get textContent() { return this.children.map((child) => child.textContent).join(""); }
  set textContent(value) { this.replaceChildren(); if (value !== "") this.append(new FakeText(value)); }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  removeAttribute(name) { this.attributes.delete(name); }
  append(...nodes) {
    for (const node of nodes) {
      const child = typeof node === "string" ? new FakeText(node) : node;
      child.parent?.children && (child.parent.children = child.parent.children.filter((item) => item !== child));
      child.parent = this;
      this.children.push(child);
    }
  }
  replaceChildren(...nodes) {
    for (const child of this.children) child.parent = null;
    this.children = [];
    this.append(...nodes);
  }
  addEventListener(type, listener) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(listener);
  }
  removeEventListener(type, listener) {
    this.listeners.set(type, (this.listeners.get(type) || []).filter((item) => item !== listener));
  }
  dispatch(type) {
    const event = { type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
    for (const listener of this.listeners.get(type) || []) listener(event);
    return event;
  }
  click() { this.dispatch("click"); }
  focus() { this.ownerDocument.activeElement = this; }
  isConnected() {
    let node = this;
    while (node.parent) node = node.parent;
    return node === this.ownerDocument.body;
  }
}

function walk(node) { return [node, ...(node.children || []).flatMap(walk)]; }
function all(root, predicate) { return walk(root).filter((node) => node instanceof FakeElement && predicate(node)); }
function byClass(root, name) { return all(root, (node) => node.classList.contains(name)); }
function one(root, name) {
  const [match] = byClass(root, name);
  assert.ok(match, `expected .${name}`);
  return match;
}
function byAction(root, action) { return all(root, (node) => node.dataset.action === action)[0] || null; }
function textOf(node) { return node.textContent.replaceAll(/\s+/g, " ").trim(); }

let documentRef;
let previousDocument;
beforeEach(() => {
  previousDocument = globalThis.document;
  const listeners = new Map();
  documentRef = {
    hidden: false,
    activeElement: null,
    createElement: (tag) => new FakeElement(tag, documentRef),
    createTextNode: (text) => new FakeText(text),
    addEventListener: (type, listener) => listeners.set(type, listener),
    removeEventListener: (type) => listeners.delete(type),
    listeners,
  };
  documentRef.body = new FakeElement("body", documentRef);
  globalThis.document = documentRef;
});
afterEach(() => { globalThis.document = previousDocument; });

async function waitFor(condition, message = "condition") {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 2));
  }
  assert.fail(`Timed out waiting for ${message}`);
}

const descriptor = {
  template: {
    id: "f1-release-readiness-review", version: "v1", title: "Release readiness review",
    objective: "Recommend whether one candidate release is ready to publish.",
    inputs: [
      { name: "release_id", type: "string", title: "Candidate release ID", format: "uuid", required: true },
      { name: "dataset_id", type: "string", title: "Dataset ID", required: false, max_length: 150 },
      { name: "reviewer_note", type: "string", title: "Optional context", required: false, max_length: 500 },
    ],
    steps: [], reviewer_checks: [],
    human_review_guidance: "Approve only when every critical and high check passed.",
  },
  input_schema: {}, tools: [{ name: "data.release_inspect.v1", available: true }], source: null,
};

const plan = {
  summary: "Inspect the release, then read the queue.",
  steps: [
    { id: "release", title: "Inspect the candidate release", purpose: "Collect status.", tool: "data.release_inspect.v1", arguments: { release_id: RELEASE_ID } },
    { id: "queue", title: "Read the release queue", purpose: "Context.", tool: "data.releases.v1", arguments: { limit: 10 } },
  ],
  produced_by: { role: "planner", provider: "deterministic", model: "rules", prompt_id: "planner", prompt_version: "v1", prompt_hash: "a".repeat(64), fallback: false },
};
const worker = (round) => ({
  round, summary: `Round ${round} evidence <script>alert(1)</script>`, correction_note: round === 2 ? "Retry the inspection." : null,
  steps: [
    { step_id: "release", status: round === 1 ? "failed" : "completed", findings: ["Inspection result"], evidence_ids: [`ev-release-r${round}`] },
    { step_id: "queue", status: "completed", findings: ["Three releases"], evidence_ids: [`ev-queue-r${round}`] },
  ],
  evidence: [
    { id: `ev-release-r${round}`, step_id: "release", tool_name: "data.release_inspect.v1", outcome: round === 1 ? "timed_out" : "succeeded", excerpt: round === 1 ? {} : { release: { status: "candidate" } }, excerpt_truncated: round === 2, result_digest: "b".repeat(64), transport: "mcp" },
    { id: `ev-queue-r${round}`, step_id: "queue", tool_name: "data.releases.v1", outcome: "succeeded", excerpt: { count: 3 }, result_digest: "c".repeat(64), transport: "mcp" },
  ],
  produced_by: { role: "worker", provider: "deterministic", model: "rules", prompt_id: "worker", prompt_version: "v1", prompt_hash: "d".repeat(64), fallback: true },
});
const review = (round, recommendation) => ({
  round, recommendation, summary: `Round ${round} review`,
  findings: [
    { id: "f-release-found", check_id: "release-found", severity: round === 1 ? "critical" : "info", outcome: round === 1 ? "fail" : "pass", message: round === 1 ? "Failed: release not inspected" : "Passed: release inspected", recommendation: round === 1 ? "Check the release ID." : null, step_ids: ["release"], evidence_ids: [`ev-release-r${round}`] },
    { id: "f-quality", check_id: "quality", severity: "medium", outcome: "fail", message: "Failed: one quality check failed", recommendation: "Explain it.", step_ids: ["release"] },
  ],
  produced_by: { role: "reviewer", provider: "deterministic", model: "rules", prompt_id: "reviewer", prompt_version: "v1", prompt_hash: "e".repeat(64) },
});
const stage = (name, round, status, start, end = null, detail = null) => ({ stage: name, round, status, started_at: `2026-10-09T09:4${start}Z`, completed_at: end ? `2026-10-09T09:4${end}Z` : null, detail });

function makeRun(state, extra = {}) {
  const base = { id: RUN_ID, template_id: "f1-release-readiness-review", template_version: "v1", feature_id: "student-1", state, round: 1, input: { release_id: RELEASE_ID }, requested_by: "matthew", provider_mode: "deterministic", created_at: "2026-10-09T09:41:41Z", updated_at: "2026-10-09T09:41:41Z", plan: null, worker_output: null, review: null, superseded: [], decisions: [], error: null, stages: [stage("planner", 1, "running", "1:41")], available_actions: ["cancel"] };
  if (["working", "reviewing", "awaiting_human"].includes(state)) base.plan = plan;
  if (["reviewing", "awaiting_human"].includes(state)) base.worker_output = worker(1);
  if (state === "awaiting_human") {
    base.review = review(1, "reject");
    base.stages = [stage("planner", 1, "completed", "1:41", "1:52"), stage("worker", 1, "completed", "1:52", "2:03"), stage("reviewer", 1, "completed", "2:03", "2:07"), stage("human", 1, "running", "2:07")];
    base.available_actions = ["approve", "correct", "partial", "reject", "cancel"];
  }
  return { ...base, ...extra };
}

function fakeClient(script = {}) {
  const calls = [];
  const queue = [...(script.runs || [])];
  let last = null;
  const client = {
    calls,
    destroyed: false,
    async getTemplate() { calls.push(["getTemplate"]); if (script.templateError) throw script.templateError; return { body: descriptor, requestId: "r" }; },
    async startRun(input, options) { calls.push(["startRun", input, options]); if (script.startError) throw script.startError; last = script.started || makeRun("planning"); return { body: last, requestId: "r" }; },
    async getRun(id) { calls.push(["getRun", id]); if (queue.length) last = queue.shift(); if (last instanceof Error) { const error = last; last = null; throw error; } return { body: last, requestId: "r" }; },
    async decide(id, body) { calls.push(["decide", id, body]); if (script.decideError) throw script.decideError; last = script.decided(body); return { body: last, requestId: "r" }; },
    async cancel(id, options) { calls.push(["cancel", id, options]); last = makeRun("cancelled", { available_actions: [], stages: [stage("planner", 1, "cancelled", "1:41", "1:42")] }); return { body: last, requestId: "r" }; },
    async getHistory(id, options = {}) {
      calls.push(["getHistory", id, { afterHistory: options.afterHistory || 0, afterAudit: options.afterAudit || 0 }]);
      if (script.historyError) throw script.historyError;
      const recorded = script.history?.(last) || { history: [{ sequence: 1, from_state: null, to_state: "planning", actor: "multi-agent-server", role: "system", reason: "Run accepted", at: "2026-10-09T09:41:41Z", round: 1 }], audit: [{ sequence: 1, event: "run.created", role: "system", actor: "matthew", at: "2026-10-09T09:41:41Z", round: 1 }] };
      const history = recorded.history.filter((entry) => entry.sequence > (options.afterHistory || 0));
      const audit = recorded.audit.filter((entry) => entry.sequence > (options.afterAudit || 0));
      return { body: { run_id: id, state: last?.state, history, audit }, requestId: "r" };
    },
    destroy() { client.destroyed = true; },
  };
  return client;
}

function mount(options) {
  const root = new FakeElement("div", documentRef);
  documentRef.body.append(root);
  const announcements = [];
  const panel = createMultiAgentPanel({ root, announce: (message) => announcements.push(message), pollDelay: (state) => (["planning", "working", "reviewing"].includes(state) ? 1 : null), ...options });
  return { root, panel, announcements };
}

function setValue(control, value) { control.value = value; control.dispatch("input"); }
function choose(root, action) {
  const radio = all(root, (node) => node.tagName === "INPUT" && node.type === "radio" && node.value === action)[0];
  assert.ok(radio, `expected a ${action} radio`);
  // A radio group checks one option at a time; the double has no groups, so do it here.
  for (const other of all(root, (node) => node.type === "radio" && node.name === radio.name)) other.checked = false;
  radio.checked = true;
  radio.dispatch("change");
}
function submit(form) { return form.dispatch("submit"); }

test("the template renders a start form; hidden inputs are submitted and the run is polled to a decision", async () => {
  const client = fakeClient({ runs: [makeRun("working"), makeRun("reviewing"), makeRun("awaiting_human")] });
  const { root, panel, announcements } = mount({ client, initialInput: { release_id: RELEASE_ID, dataset_id: "abs-seifa-2021" }, hiddenInputs: ["release_id"], actor: "matthew" });
  try {
    await waitFor(() => byClass(root, "ps-multi-agent__start").length, "start form");
    assert.equal(textOf(one(root, "ps-multi-agent__title")), "Release readiness review");
    const form = one(root, "ps-multi-agent__start");
    const inputs = all(form, (node) => ["INPUT", "TEXTAREA"].includes(node.tagName));
    assert.deepEqual(inputs.map((node) => node.name), ["dataset_id", "reviewer_note"]);
    assert.equal(inputs[0].value, "abs-seifa-2021");
    assert.equal(inputs[1].tagName, "TEXTAREA");
    assert.match(textOf(one(form, "ps-multi-agent__supplied")), new RegExp(RELEASE_ID));
    assert.equal(submit(form).defaultPrevented, true);

    await waitFor(() => client.calls.some(([name]) => name === "startRun"), "start");
    const [, input, options] = client.calls.find(([name]) => name === "startRun");
    assert.deepEqual(input, { release_id: RELEASE_ID, dataset_id: "abs-seifa-2021" });
    assert.equal(options.requestedBy, "matthew");
    await waitFor(() => byClass(root, "ps-multi-agent__decision").length, "decision form");

    const run = one(root, "ps-multi-agent__run");
    assert.equal(run.dataset.state, "awaiting_human");
    assert.equal(run.getAttribute("aria-busy"), "false");
    assert.deepEqual(byClass(root, "ps-multi-agent__stage").map((node) => node.dataset.status), ["completed", "completed", "completed", "waiting"]);
    assert.equal(byClass(root, "ps-multi-agent__start").length, 0, "the start form hides while a run is open");
    assert.ok(announcements.some((message) => message.startsWith("Review started")));
    assert.ok(announcements.some((message) => message.startsWith("Awaiting your decision")));
    const polls = client.calls.filter(([name]) => name === "getRun").length;
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(client.calls.filter(([name]) => name === "getRun").length, polls, "polling stops at awaiting_human");

    // Worker, Reviewer, provenance and guidance are visible; untrusted text stays text.
    assert.match(textOf(one(root, "ps-multi-agent__worker")), /<script>alert\(1\)<\/script>/);
    assert.deepEqual(byClass(one(root, "ps-multi-agent__worker"), "ps-multi-agent__step").map((node) => node.dataset.stepId), ["release", "queue"]);
    assert.equal(one(root, "ps-multi-agent__recommendation").dataset.recommendation, "reject");
    assert.deepEqual(byClass(one(root, "ps-multi-agent__review"), "ps-multi-agent__finding").map((node) => node.dataset.findingId), ["f-release-found", "f-quality"]);
    assert.ok(byClass(root, "ps-multi-agent__provenance--fallback").length >= 1);
    assert.match(textOf(one(root, "ps-multi-agent__guidance")), /every critical and high check/);
    assert.equal(one(root, "ps-multi-agent__guidance").hidden, true, "guidance waits behind How to decide");
    assert.equal(one(root, "ps-multi-agent__suggest").dataset.recommendation, "reject");
    assert.match(textOf(one(root, "ps-multi-agent__safety")), /never publishes/);
    assert.equal(one(root, "ps-multi-agent__reveal").hidden, true, "only the question shows before a choice");
    assert.match(textOf(one(root, "ps-multi-agent__now")), /^Your turn. The agents have finished and are waiting for you./);
    const radios = all(one(root, "ps-multi-agent__decision"), (node) => node.type === "radio").map((node) => node.value);
    assert.deepEqual(radios, ["approve", "correct", "partial", "reject"]);
  } finally {
    panel.destroy();
  }
});

test("decision validation is accessible, partial needs steps, and a correction starts round 2", async () => {
  const roundTwo = makeRun("working", {
    round: 2, worker_output: null, review: null, superseded: [{ round: 1, worker_output: worker(1), review: review(1, "reject") }],
    decisions: [{ decision: "correct", note: "Retry the inspection.", actor: "matthew", round: 1, decided_at: "2026-10-09T09:42:26Z", resulting_state: "working", accepted_step_ids: [] }],
    available_actions: ["cancel"],
  });
  const awaitingTwo = makeRun("awaiting_human", { round: 2, worker_output: worker(2), review: review(2, "partial"), superseded: roundTwo.superseded, decisions: roundTwo.decisions });
  const client = fakeClient({ runs: [makeRun("awaiting_human"), awaitingTwo], decided: () => roundTwo });
  const { root, panel } = mount({ client, runId: RUN_ID, actor: "" });
  try {
    await waitFor(() => byClass(root, "ps-multi-agent__decision").length, "decision form");
    let form = one(root, "ps-multi-agent__decision");
    submit(form);
    const errors = byClass(form, "ps-multi-agent__field-error").filter((node) => !node.hidden).map(textOf);
    assert.deepEqual(errors, ["Choose what you want to do."], "the hidden fields cannot be wrong yet");
    assert.equal(documentRef.activeElement?.value, "approve", "focus moves to the first invalid control");
    assert.equal(documentRef.activeElement.getAttribute("aria-invalid"), "true");

    choose(root, "approve");
    assert.deepEqual(byClass(form, "ps-multi-agent__field-error").filter((node) => !node.hidden).map(textOf), [], "choosing clears the choice error");
    assert.equal(all(form, (node) => node.type === "radio" && node.getAttribute("aria-invalid") === "true").length, 0);
    assert.equal(one(form, "ps-multi-agent__reveal").hidden, false);
    assert.match(textOf(one(form, "ps-multi-agent__warning")), /1 critical or high check failed/);
    assert.equal(one(form, "ps-multi-agent__warning").hidden, false);
    assert.equal(textOf(byAction(form, "decide")), "Approve");
    choose(root, "partial");
    assert.equal(one(form, "ps-multi-agent__accepted").hidden, false);
    assert.equal(one(form, "ps-multi-agent__warning").hidden, true);
    const actor = all(form, (node) => node.id?.endsWith("-decision-actor"))[0];
    setValue(actor, "matthew");
    submit(form);
    assert.deepEqual(byClass(form, "ps-multi-agent__field-error").filter((node) => !node.hidden).map(textOf), ["Select at least one step to accept.", "Add a note explaining this decision."]);
    assert.equal(client.calls.filter(([name]) => name === "decide").length, 0);

    const step = all(form, (node) => node.type === "checkbox")[0];
    step.checked = true;
    step.dispatch("change");
    assert.equal(textOf(byAction(form, "decide")), "Accept 1 step");
    step.checked = false;
    step.dispatch("change");
    choose(root, "correct");
    assert.equal(textOf(byAction(form, "decide")), "Send back to the agents");
    assert.match(textOf(all(form, (node) => node.tagName === "LABEL" && node.htmlFor?.endsWith("-decision-note"))[0]), /What should the agents check/);
    const note = all(form, (node) => node.tagName === "TEXTAREA")[0];
    setValue(note, "Retry the inspection.");
    submit(form);
    await waitFor(() => client.calls.some(([name]) => name === "decide"), "decision");
    assert.deepEqual(client.calls.find(([name]) => name === "decide")[2], { decision: "correct", note: "Retry the inspection.", actor: "matthew" });

    await waitFor(() => one(root, "ps-multi-agent__run").dataset.state === "awaiting_human" && textOf(one(root, "ps-multi-agent__round")) === "Round 2 of 2", "round 2 decision");
    const superseded = one(root, "ps-multi-agent__superseded");
    assert.match(textOf(superseded.children[0]), /Round 1 \(superseded\)/);
    assert.equal(superseded.open, false);
    assert.match(textOf(one(root, "ps-multi-agent__decisions")), /Send back once.*Round 1 · matthew/);
    assert.match(textOf(one(root, "ps-multi-agent__correction-note")), /Retry the inspection/);
    form = one(root, "ps-multi-agent__decision");
    assert.match(textOf(form), /Final correction/);
    assert.match(textOf(form), /Final round/);
    assert.equal(all(form, (node) => node.id?.endsWith("-decision-actor"))[0].value, "matthew", "the actor is kept for the next decision");
    assert.ok(documentRef.activeElement === one(root, "ps-multi-agent__run-title"), "focus returns to the run heading");
  } finally {
    panel.destroy();
  }
});

test("server Problem Details are shown inline with field errors, code and request ID", async () => {
  const startError = new MultiAgentApiError("invalid", { status: 422, requestId: "req-422", problem: {
    type: "about:blank", title: "Invalid workflow input", status: 422, detail: "The input did not match the template.", code: "invalid_workflow_input", request_id: "req-422",
    errors: [{ field: "input.dataset_id", message: "Unknown dataset", code: "unknown" }],
  } });
  const client = fakeClient({ startError });
  const { root, panel } = mount({ client, initialInput: { release_id: RELEASE_ID, dataset_id: "nope" }, hiddenInputs: ["release_id"] });
  try {
    await waitFor(() => byClass(root, "ps-multi-agent__start").length, "start form");
    const form = one(root, "ps-multi-agent__start");
    submit(form);
    await waitFor(() => byClass(form, "ps-multi-agent__problem").length, "problem");
    const problem = one(form, "ps-multi-agent__problem");
    assert.equal(problem.getAttribute("role"), "alert");
    assert.equal(problem.dataset.code, "invalid_workflow_input");
    assert.match(textOf(problem), /Invalid workflow input.*did not match.*input\.dataset_id: Unknown dataset.*Code invalid_workflow_input · HTTP 422 · Request req-422/);
    const datasetError = byClass(form, "ps-multi-agent__field-error").find((node) => !node.hidden);
    assert.equal(textOf(datasetError), "Unknown dataset");
    const submitButton = byAction(form, "start");
    assert.equal(submitButton.disabled, false, "the form is usable again after an error");
  } finally {
    panel.destroy();
  }
});

test("an invalid page-supplied hidden input is reported instead of silently starting", async () => {
  const client = fakeClient();
  const { root, panel } = mount({ client, initialInput: { release_id: "not-a-uuid" }, hiddenInputs: ["release_id"] });
  try {
    await waitFor(() => byClass(root, "ps-multi-agent__start").length, "start form");
    submit(one(root, "ps-multi-agent__start"));
    assert.match(textOf(one(root, "ps-multi-agent__problem")), /This page supplied an invalid workflow input.*Candidate release ID/);
    assert.equal(client.calls.some(([name]) => name === "startRun"), false);
  } finally {
    panel.destroy();
  }
});

test("a terminal run shows its outcome, loads history once and links the full history", async () => {
  const approved = makeRun("approved", {
    plan, worker_output: worker(1), review: review(1, "approve"), available_actions: [],
    decisions: [{ decision: "approve", note: "", actor: "matthew", round: 1, decided_at: "2026-10-09T09:43:11Z", resulting_state: "approved", accepted_step_ids: [] }],
    stages: [stage("planner", 1, "completed", "1:41", "1:52"), stage("human", 1, "completed", "2:07", "3:11", "approve")],
  });
  const client = fakeClient({ runs: [approved] });
  const { root, panel } = mount({ client, runId: RUN_ID, historyHref: (id) => `/features/data-platform/#/reviews/${id}` });
  try {
    await waitFor(() => byClass(root, "ps-multi-agent__run").length, "run");
    assert.equal(byClass(root, "ps-multi-agent__decision").length, 0);
    assert.equal(byAction(root, "cancel"), null);
    assert.equal(one(root, "ps-multi-agent__badge--confirmed").dataset.state, "approved");
    assert.equal(byAction(root, "history-link").href, `/features/data-platform/#/reviews/${RUN_ID}`);
    await waitFor(() => byClass(root, "ps-multi-agent__transitions").length, "history");
    const history = one(root, "ps-multi-agent__history");
    assert.equal(history.open, false, "drawers start closed");
    history.open = true;
    history.dispatch("toggle");
    assert.match(textOf(one(root, "ps-multi-agent__transitions")), /Start → Planning.*Run accepted/);
    assert.match(textOf(one(root, "ps-multi-agent__audit")), /Run accepted\.run\.created/);
    history.dispatch("toggle");
    assert.equal(client.calls.filter(([name]) => name === "getHistory").length, 1, "a finished run reads its history once");
    assert.match(textOf(one(root, "ps-multi-agent__outcome")), /Approved · matthew, round 1.*did not publish/);
    assert.equal(byAction(root, "replay").tagName, "BUTTON", "a recorded run can be replayed");

    const again = byAction(root, "start-again");
    again.click();
    assert.equal(byClass(root, "ps-multi-agent__start").length, 1);
    assert.equal(textOf(one(root, "ps-multi-agent__form-title")), "Start another review");
  } finally {
    panel.destroy();
  }
});

test("a failed run shows its error; poll failures warn and retry; cancel is confirmed", async () => {
  const failed = makeRun("failed", { error: { code: "planner_output_unavailable", message: "The Planner returned no valid plan", stage: "planner" }, available_actions: [], stages: [stage("planner", 1, "failed", "1:41", "1:45")] });
  const unavailable = new MultiAgentApiError("down", { status: 503, problem: { title: "Unavailable", status: 503, code: "multi_agent_unavailable" } });
  const client = fakeClient({ runs: [makeRun("planning"), unavailable, failed] });
  const { root, panel } = mount({ client, runId: RUN_ID });
  try {
    await waitFor(() => byClass(root, "ps-multi-agent__run").length, "run");
    await waitFor(() => one(root, "ps-multi-agent__run").dataset.state === "failed", "failed state");
    assert.match(textOf(one(root, "ps-multi-agent__problem")), /The workflow failed.*The Planner returned no valid plan.*Stage: Planner.*Code planner_output_unavailable/);
    assert.equal(byClass(root, "ps-multi-agent__poll-warning").length, 0, "a recovered poll clears its warning");
  } finally {
    panel.destroy();
  }

  const second = fakeClient({ runs: [makeRun("planning"), unavailable] });
  const mounted = mount({ client: second, runId: RUN_ID, pollDelay: (state, failures) => (state === "planning" && failures < 1 ? 1 : null) });
  try {
    await waitFor(() => byClass(mounted.root, "ps-multi-agent__poll-warning").length, "poll warning");
    const cancel = byAction(mounted.root, "cancel");
    cancel.click();
    const confirm = byAction(mounted.root, "confirm-cancel");
    assert.ok(documentRef.activeElement === confirm, "focus moves to the confirmation");
    assert.equal(second.calls.some(([name]) => name === "cancel"), false, "the first click only asks for confirmation");
    confirm.click();
    await waitFor(() => one(mounted.root, "ps-multi-agent__run").dataset.state === "cancelled", "cancelled");
    assert.equal(byAction(mounted.root, "cancel"), null);
  } finally {
    mounted.panel.destroy();
  }
});

test("destroy stops polling, aborts the client and ignores late responses", async () => {
  let release;
  const client = fakeClient();
  client.getRun = (id) => { client.calls.push(["getRun", id]); return new Promise((resolve) => { release = resolve; }); };
  const { root, panel } = mount({ client, runId: RUN_ID });
  await waitFor(() => typeof release === "function", "pending run request");
  panel.destroy();
  assert.equal(client.destroyed, true);
  release({ body: makeRun("planning"), requestId: "late" });
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(byClass(root, "ps-multi-agent__run").length, 0);
  assert.equal(client.calls.filter(([name]) => name === "getRun").length, 1);
  assert.equal(documentRef.listeners.has("visibilitychange"), false);
});

test("a template that cannot load shows Problem Details with a retry", async () => {
  const client = fakeClient({ templateError: new MultiAgentApiError("down", { status: 503, requestId: "req-503", problem: { title: "Multi-agent server unavailable", status: 503, code: "multi_agent_unavailable", request_id: "req-503" } }) });
  const { root, panel } = mount({ client });
  try {
    await waitFor(() => byClass(root, "ps-multi-agent__problem").length, "problem");
    assert.match(textOf(one(root, "ps-multi-agent__problem")), /The workflow could not be loaded.*Multi-agent server unavailable.*multi_agent_unavailable.*req-503/);
    assert.ok(byAction(root, "reload-template"));
    assert.equal(byClass(root, "ps-multi-agent__start").length, 0);
  } finally {
    panel.destroy();
  }
});

function recordedHistory(seconds) {
  const at = (value) => new Date(Date.parse("2026-10-09T09:41:41Z") + value * 1000).toISOString();
  const history = [
    { sequence: 1, from_state: null, to_state: "planning", actor: "multi-agent-server", role: "system", reason: "Run accepted", at: at(0), round: 1 },
    { sequence: 2, from_state: "planning", to_state: "working", actor: "planner", role: "planner", reason: "Planned", at: at(11), round: 1 },
    { sequence: 3, from_state: "working", to_state: "reviewing", actor: "worker", role: "worker", reason: "Evidence", at: at(22), round: 1 },
    { sequence: 4, from_state: "reviewing", to_state: "awaiting_human", actor: "reviewer", role: "reviewer", reason: "Reviewed", at: at(26), round: 1 },
    { sequence: 5, from_state: "awaiting_human", to_state: "approved", actor: "matthew", role: "human", reason: "Approved", at: at(90), round: 1 },
  ];
  const audit = [
    { sequence: 1, event: "run.created", role: "system", actor: "matthew", at: at(0), round: 1, detail: {} },
    { sequence: 2, event: "agent.handoff", role: "system", actor: "multi-agent-server", at: at(0), round: 1, detail: { from: "system", to: "planner" } },
    { sequence: 3, event: "model.started", role: "planner", actor: "planner", at: at(0.2), round: 1, detail: { attempt: 1 } },
    { sequence: 4, event: "model.invocation", role: "planner", actor: "planner", at: at(11), round: 1, detail: { attempt: 1, outcome: "succeeded", duration_ms: 10800, model: "gpt-5.6-luna" } },
    { sequence: 5, event: "agent.handoff", role: "planner", actor: "planner", at: at(11), round: 1, detail: { from: "planner", to: "worker" } },
    { sequence: 6, event: "tool.call", role: "worker", actor: "worker", at: at(14), round: 1, detail: { tool_name: "data.release_inspect.v1", outcome: "timed_out", duration_ms: 3000, step_id: "release", evidence_id: "ev-release-r1" } },
    { sequence: 7, event: "tool.call", role: "worker", actor: "worker", at: at(15), round: 1, detail: { tool_name: "data.releases.v1", outcome: "succeeded", duration_ms: 900, step_id: "queue", evidence_id: "ev-queue-r1" } },
    { sequence: 8, event: "worker.completed", role: "worker", actor: "worker", at: at(22), round: 1, detail: {} },
    { sequence: 9, event: "agent.handoff", role: "worker", actor: "worker", at: at(22), round: 1, detail: { from: "worker", to: "reviewer" } },
    { sequence: 10, event: "review.completed", role: "reviewer", actor: "reviewer", at: at(26), round: 1, detail: {} },
    { sequence: 11, event: "agent.handoff", role: "reviewer", actor: "reviewer", at: at(26), round: 1, detail: { from: "reviewer", to: "human" } },
    { sequence: 12, event: "decision.recorded", role: "human", actor: "matthew", at: at(90), round: 1, detail: { decision: "approve", decision_round: 1 } },
  ];
  const until = Date.parse("2026-10-09T09:41:41Z") + seconds * 1000;
  return { history: history.filter((entry) => Date.parse(entry.at) <= until), audit: audit.filter((entry) => Date.parse(entry.at) <= until) };
}

test("while agents work, history is polled after its cursors and drawn as lanes and a now line", async () => {
  const working = makeRun("working", { stages: [stage("planner", 1, "completed", "1:41", "1:52"), { stage: "worker", round: 1, status: "running", started_at: "2026-10-09T09:41:52Z", completed_at: null, detail: null }] });
  const moments = [16, 20];
  const client = fakeClient({ runs: [working, working, working], history: () => recordedHistory(moments.shift() ?? 20) });
  const { root, panel } = mount({ client, runId: RUN_ID, pollDelay: (state, failures) => (state === "working" && client.calls.filter(([name]) => name === "getRun").length < 3 ? 1 : null) });
  try {
    await waitFor(() => client.calls.filter(([name]) => name === "getHistory").length >= 3, "incremental history reads");
    const reads = client.calls.filter(([name]) => name === "getHistory").map(([, , cursors]) => cursors);
    assert.deepEqual(reads[0], { afterHistory: 0, afterAudit: 0 }, "the first read is complete");
    assert.deepEqual(reads[1], { afterHistory: 2, afterAudit: 7 }, "later reads ask only for newer entries");
    await waitFor(() => byClass(root, "ps-multi-agent__pin").length === 2, "tool pins");
    const pins = byClass(root, "ps-multi-agent__pin");
    assert.equal(pins[0].classList.contains("ps-multi-agent__pin--failed"), true, "the timed-out call is marked failed");
    assert.match(pins[0].style.getPropertyValue("--x"), /^\d+(\.\d+)?%$/);
    assert.equal(byClass(root, "ps-multi-agent__model").length, 1, "only returned model calls are drawn solid");
    assert.equal(byClass(root, "ps-multi-agent__baton").length, 1, "the Planner's hand-off to the Worker; the server's start is not drawn");
    assert.deepEqual(byClass(root, "ps-multi-agent__stage").map((node) => node.dataset.status), ["completed", "running", "pending", "pending"]);
    assert.match(textOf(one(root, "ps-multi-agent__now")), /The Worker is writing findings from 2 tool results/);
    assert.match(textOf(one(root, "ps-multi-agent__now")), /✕ data\.release_inspect.*✓ data\.releases/);
    assert.equal(byClass(root, "ps-multi-agent__wait").length, 1, "waiting is striped, never a percentage");
    const evidence = all(root, (node) => node.dataset.disclosure === "drawer-evidence")[0];
    assert.match(textOf(evidence.children[0]), /Worker evidence.*2 tool calls so far/);
    assert.deepEqual(byClass(evidence, "ps-multi-agent__tool-call").map((node) => node.dataset.evidenceId), ["ev-release-r1", "ev-queue-r1"]);
    assert.equal(byAction(root, "replay"), null, "only a finished run offers a replay");
  } finally {
    panel.destroy();
  }
});

test("a recorded run replays to its decision point without sending anything, then returns to the outcome", async () => {
  const approved = makeRun("approved", {
    plan, worker_output: worker(1), review: review(1, "approve"), available_actions: [], completed_at: "2026-10-09T09:43:11Z", updated_at: "2026-10-09T09:43:11Z",
    decisions: [{ decision: "approve", note: "Checked the counts.", actor: "matthew", round: 1, decided_at: "2026-10-09T09:43:11Z", resulting_state: "approved", accepted_step_ids: [] }],
    stages: [stage("planner", 1, "completed", "1:41", "1:52"), stage("worker", 1, "completed", "1:52", "2:03"), stage("reviewer", 1, "completed", "2:03", "2:07"), stage("human", 1, "completed", "2:07", "3:11", "approve")],
  });
  const client = fakeClient({ runs: [approved], history: () => recordedHistory(90) });
  const { root, panel, announcements } = mount({ client, runId: RUN_ID });
  try {
    await waitFor(() => byAction(root, "replay"), "replay controls");
    assert.equal(one(root, "ps-multi-agent__run").dataset.replay, "false", "a recorded run opens at its outcome");
    all(root, (node) => node.dataset.action === "replay-jump")[0].click();
    const run = one(root, "ps-multi-agent__run");
    assert.equal(run.dataset.replay, "true");
    assert.equal(run.dataset.state, "awaiting_human");
    assert.equal(byClass(root, "ps-multi-agent__decision").length, 0, "a replay never shows a live decision form");
    const recorded = one(root, "ps-multi-agent__recorded");
    assert.match(textOf(recorded), /What was decided.*Approve.*matthew, after 1 min 4 s.*Checked the counts/);
    assert.ok(announcements.includes("Replay at the round 1 decision."));
    byAction(root, "replay-next").click();
    assert.ok(announcements.at(-1).length > 0);
    byAction(root, "replay-outcome").click();
    assert.equal(one(root, "ps-multi-agent__run").dataset.replay, "false");
    assert.equal(byClass(root, "ps-multi-agent__outcome").length, 1);
    assert.equal(client.calls.some(([name]) => name === "decide"), false, "nothing is sent from a replay");
    byAction(root, "replay").click();
    await waitFor(() => one(root, "ps-multi-agent__run").dataset.replay === "true", "replay running");
    assert.match(byAction(root, "replay").getAttribute("aria-label"), /Pause/);
    byAction(root, "replay").click();
    assert.match(byAction(root, "replay").getAttribute("aria-label"), /Continue/);
  } finally {
    panel.destroy();
  }
});

test("when history cannot be read the stages still show and the log offers a retry", async () => {
  const unavailable = new MultiAgentApiError("down", { status: 503, problem: { title: "Unavailable", status: 503, code: "multi_agent_unavailable" } });
  const client = fakeClient({ runs: [makeRun("awaiting_human")], historyError: unavailable });
  const { root, panel } = mount({ client, runId: RUN_ID });
  try {
    await waitFor(() => byClass(root, "ps-multi-agent__history-warning").length, "history warning");
    assert.match(textOf(one(root, "ps-multi-agent__history-warning")), /only the stages are shown/);
    assert.deepEqual(byClass(root, "ps-multi-agent__stage").map((node) => node.dataset.status), ["completed", "completed", "completed", "waiting"]);
    assert.equal(byClass(root, "ps-multi-agent__decision").length, 1, "deciding does not depend on the history");
    assert.equal(byClass(root, "ps-multi-agent__pin").length, 0);
    byAction(root, "reload-history").click();
    await waitFor(() => client.calls.filter(([name]) => name === "getHistory").length === 2, "retry");
  } finally {
    panel.destroy();
  }
});

test("under reduced motion a replay steps between recorded moments, and destroy stops it", async () => {
  const previous = globalThis.matchMedia;
  globalThis.matchMedia = (query) => ({ matches: query.includes("reduce") });
  const approved = makeRun("approved", {
    plan, worker_output: worker(1), review: review(1, "approve"), available_actions: [], completed_at: "2026-10-09T09:43:11Z", updated_at: "2026-10-09T09:43:11Z",
    decisions: [{ decision: "approve", note: "", actor: "matthew", round: 1, decided_at: "2026-10-09T09:43:11Z", resulting_state: "approved", accepted_step_ids: [] }],
    stages: [stage("planner", 1, "completed", "1:41", "1:52"), stage("worker", 1, "completed", "1:52", "2:03"), stage("reviewer", 1, "completed", "2:03", "2:07"), stage("human", 1, "completed", "2:07", "3:11", "approve")],
  });
  const client = fakeClient({ runs: [approved], history: () => recordedHistory(90) });
  const { root, panel } = mount({ client, runId: RUN_ID });
  try {
    await waitFor(() => byAction(root, "replay"), "replay controls");
    byAction(root, "replay").click();
    assert.equal(byAction(root, "replay-seek").value, "0", "a replay from the outcome starts at the beginning");
    await waitFor(() => byAction(root, "replay-seek").value !== "0", "the first discrete step");
    const first = Number(byAction(root, "replay-seek").value);
    assert.equal(byClass(root, "ps-multi-agent__segment").length >= 1, true);
    assert.ok(first > 0 && first <= 11000, `the step lands on a recorded moment (${first})`);
    panel.destroy();
    await new Promise((resolve) => setTimeout(resolve, 1200));
    assert.equal(Number(byAction(root, "replay-seek").value), first, "destroy stops the replay clock");
  } finally {
    panel.destroy();
    globalThis.matchMedia = previous;
  }
});
