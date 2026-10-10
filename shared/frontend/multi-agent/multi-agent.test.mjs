import assert from "node:assert/strict";
import test from "node:test";

import { MultiAgentApiError, createMultiAgentClient } from "./client.js";
import {
  DEFAULT_MULTI_AGENT_LABELS, mergeLabels, shortRunId, workflowStatus,
} from "./definitions.js";
import { nextWorkflowPollDelay } from "./polling.js";
import {
  availableDecisions, canCancel, evidenceExcerpt, fieldProblems, formatDuration, groupFindings,
  historyView, problemView, provenanceLabel, runPresentationKey, stageTimeline, startFields,
  validateDecision, validateStartInput, workerStepViews,
} from "./projections.js";

const RUN_ID = "c17c66cc-6b40-4685-909a-440401ae8ec7";
const RELEASE_ID = "cb188a6e-613f-4f4e-b7b0-b827dd573869";

// Contract-shaped fragments modelled on a recorded Feature 1 export.
const plan = {
  summary: "Inspect the release, then read the queue.",
  evidence_needed: ["Release status and quality results."],
  steps: [
    { id: "release", index: 1, title: "Inspect the candidate release", purpose: "Collect status.", tool: "data.release_inspect.v1", arguments: { release_id: RELEASE_ID }, required: true },
    { id: "queue", index: 2, title: "Read the release queue", purpose: "See other releases.", tool: "data.releases.v1", arguments: { dataset_id: "abs-seifa-2021", limit: 10 }, required: true },
  ],
  produced_by: { role: "planner", provider: "openai", model: "gpt-5.6-luna", prompt_id: "planner", prompt_version: "v1", prompt_hash: "a".repeat(64), invocations: 1, fallback: false },
};
const workerOutput = {
  round: 1,
  summary: "One step timed out.",
  correction_note: null,
  steps: [
    { step_id: "release", status: "failed", findings: ["The inspection timed out."], evidence_ids: ["ev-release-r1"] },
    { step_id: "queue", status: "completed", findings: ["Three releases are queued."], evidence_ids: ["ev-queue-r1"] },
  ],
  evidence: [
    { id: "ev-release-r1", step_id: "release", tool_name: "data.release_inspect.v1", outcome: "timed_out", excerpt: {}, excerpt_truncated: false, error_code: "mcp_timeout", result_digest: "b".repeat(64), transport: "mcp" },
    { id: "ev-queue-r1", step_id: "queue", tool_name: "data.releases.v1", outcome: "succeeded", excerpt: { count: 3 }, excerpt_truncated: false, result_digest: "c".repeat(64), transport: "mcp" },
  ],
};

test("workflow vocabulary is overridable one level deep without losing defaults", () => {
  const labels = mergeLabels({ start: "Review release", states: { awaiting_human: { label: "Ready for you" } } });
  assert.equal(labels.start, "Review release");
  assert.equal(workflowStatus("awaiting_human", labels).label, "Ready for you");
  assert.equal(workflowStatus("awaiting_human", labels).tone, "partial");
  assert.equal(workflowStatus("approved", labels).label, "Approved");
  assert.equal(workflowStatus("future_state").label, "Future state");
  assert.equal(shortRunId(RUN_ID), "c17c66cc…");
  assert.equal(DEFAULT_MULTI_AGENT_LABELS.states.failed.tone, "danger");
});

test("the stage timeline keeps recorded stages and shows the stages a round has yet to reach", () => {
  const planning = stageTimeline({ state: "planning", round: 1, stages: [
    { stage: "planner", round: 1, status: "running", started_at: "2026-10-09T09:41:41Z" },
  ] });
  assert.deepEqual(planning.map((item) => `${item.stage}:${item.status}`), ["planner:running", "worker:pending", "reviewer:pending", "human:pending"]);

  const awaiting = stageTimeline({ state: "awaiting_human", round: 1, stages: [
    { stage: "planner", round: 1, status: "completed", started_at: "2026-10-09T09:41:41.000Z", completed_at: "2026-10-09T09:41:52.500Z" },
    { stage: "worker", round: 1, status: "completed", started_at: "2026-10-09T09:41:52.500Z", completed_at: "2026-10-09T09:42:03Z" },
    { stage: "reviewer", round: 1, status: "completed", started_at: "2026-10-09T09:42:03Z", completed_at: "2026-10-09T09:42:07Z" },
    { stage: "human", round: 1, status: "running", started_at: "2026-10-09T09:42:07Z" },
  ] });
  assert.equal(awaiting.length, 4);
  assert.equal(awaiting[3].status, "waiting");
  assert.equal(awaiting[3].statusLabel, "Waiting for a person");
  assert.equal(awaiting[0].durationMs, 11500);
  assert.deepEqual([formatDuration(awaiting[0].durationMs), formatDuration(1200), formatDuration(650), formatDuration(125000), formatDuration(55_475_000)], ["12 s", "1.2 s", "650 ms", "2 min 5 s", "15 h 24 min"]);

  const roundTwo = stageTimeline({ state: "working", round: 2, stages: [
    ...awaiting.slice(0, 3).map((item) => ({ stage: item.stage, round: 1, status: "completed", started_at: item.startedAt, completed_at: item.completedAt })),
    { stage: "human", round: 1, status: "completed", detail: "correct", started_at: "2026-10-09T09:42:07Z", completed_at: "2026-10-09T09:42:26Z" },
    { stage: "worker", round: 2, status: "running", started_at: "2026-10-09T09:42:26Z" },
  ] });
  // Round 2 re-runs the Worker and Reviewer only; the plan is kept.
  assert.deepEqual(roundTwo.slice(4).map((item) => `${item.round}:${item.stage}:${item.status}`), ["2:worker:running", "2:reviewer:pending", "2:human:pending"]);
  assert.equal(roundTwo[3].detail, "Correct");

  const failed = stageTimeline({ state: "failed", round: 1, stages: [{ stage: "planner", round: 1, status: "failed", started_at: "2026-10-09T09:41:41Z", completed_at: "2026-10-09T09:41:42Z" }] });
  assert.deepEqual(failed.map((item) => item.status), ["failed"]);
});

test("decision controls map only the server's available actions and name the final correction", () => {
  const roundOne = { round: 1, available_actions: ["approve", "correct", "partial", "reject", "cancel", "unknown"] };
  assert.deepEqual(availableDecisions(roundOne).map((option) => option.action), ["approve", "correct", "partial", "reject"]);
  assert.equal(availableDecisions(roundOne)[1].label, "Request a correction");
  assert.equal(availableDecisions({ ...roundOne, round: 2 })[1].label, "Record a final correction");
  assert.equal(canCancel(roundOne), true);
  assert.deepEqual(availableDecisions({ round: 1, available_actions: ["cancel"] }), []);
  assert.equal(canCancel({ available_actions: [] }), false);
  assert.deepEqual(availableDecisions(null), []);
});

test("decision validation mirrors the server's note, actor and partial-step rules", () => {
  const run = { round: 1, available_actions: ["approve", "correct", "partial", "reject", "cancel"], plan };
  assert.deepEqual(validateDecision({ decision: "approve", note: "", actor: " Matthew " }, run).body, { decision: "approve", note: "", actor: "Matthew" });
  assert.equal(validateDecision({ decision: "reject", note: "  ", actor: "Matthew" }, run).errors.note, "Add a note explaining this decision.");
  assert.match(validateDecision({ decision: "correct", note: "Recheck", actor: "" }, run).errors.actor, /Enter the name/);
  assert.match(validateDecision({ decision: "correct", note: "Recheck", actor: "a\u0007b" }, run).errors.actor, /control characters/);
  assert.match(validateDecision({ decision: "approve", note: "x".repeat(2001), actor: "A" }, run).errors.note, /2000/);
  assert.match(validateDecision({ decision: "partial", note: "Some", actor: "A", acceptedStepIds: [] }, run).errors.accepted_step_ids, /at least one/);
  assert.match(validateDecision({ decision: "partial", note: "Some", actor: "A", acceptedStepIds: ["ghost"] }, run).errors.accepted_step_ids, /this run's plan/);
  const partial = validateDecision({ decision: "partial", note: "Queue only", actor: "A", acceptedStepIds: ["queue", "queue"] }, run);
  assert.deepEqual(partial.body, { decision: "partial", note: "Queue only", actor: "A", accepted_step_ids: ["queue"] });
  assert.match(validateDecision({ decision: "approve", actor: "A" }, { ...run, available_actions: ["cancel"] }).errors.decision, /not waiting/);
  assert.match(validateDecision({ decision: "", actor: "A" }, run).errors.decision, /Choose one/);
});

test("template inputs become typed fields; hidden inputs are kept and validated", () => {
  const descriptor = { template: { inputs: [
    { name: "release_id", type: "string", title: "Candidate release ID", format: "uuid", required: true },
    { name: "dataset_id", type: "string", title: "Dataset", required: false, max_length: 150 },
    { name: "reviewer_note", type: "string", title: "Context", required: false, max_length: 500 },
    { name: "limit", type: "integer", title: "Limit", required: false, minimum: 1, maximum: 50 },
    { name: "ratio", type: "number", title: "Ratio", required: false },
    { name: "strict", type: "boolean", title: "Strict", required: false },
    { name: "mode", type: "string", title: "Mode", enum: ["quick", "full"], required: false },
    { name: "as_of", type: "string", title: "As of", format: "date", required: false },
  ] } };
  const fields = startFields(descriptor, { hiddenInputs: ["release_id"], initialInput: { release_id: RELEASE_ID, dataset_id: "abs" } });
  const byName = Object.fromEntries(fields.map((field) => [field.name, field]));
  assert.equal(byName.release_id.hidden, true);
  assert.equal(byName.release_id.initialValue, RELEASE_ID);
  assert.match(byName.release_id.pattern, /\[0-9a-fA-F\]\{8\}/);
  assert.equal(byName.dataset_id.control, "text");
  assert.equal(byName.reviewer_note.control, "textarea");
  assert.equal(byName.limit.control, "number");
  assert.equal(byName.strict.control, "checkbox");
  assert.equal(byName.mode.control, "select");
  assert.equal(byName.as_of.control, "date");

  const ok = validateStartInput(fields, { release_id: RELEASE_ID, dataset_id: " abs ", reviewer_note: "", limit: "10", ratio: "0.5", strict: true, mode: "full", as_of: "2026-10-01" });
  assert.deepEqual(ok, { valid: true, errors: {}, input: { release_id: RELEASE_ID, dataset_id: "abs", limit: 10, ratio: 0.5, strict: true, mode: "full", as_of: "2026-10-01" } });

  const bad = validateStartInput(fields, { release_id: "not-a-uuid", dataset_id: "x".repeat(151), limit: "1.5", ratio: "abc", mode: "other", as_of: "01/10/2026" });
  assert.match(bad.errors.release_id, /UUID/);
  assert.match(bad.errors.dataset_id, /150 characters/);
  assert.equal(bad.errors.limit, "Enter a whole number.");
  assert.equal(bad.errors.ratio, "Enter a number.");
  assert.match(bad.errors.mode, /listed values/);
  assert.match(bad.errors.as_of, /YYYY-MM-DD/);
  assert.equal(validateStartInput(fields, { limit: "60" }).errors.limit, "Enter 50 or less.");
  assert.equal(validateStartInput(fields, {}).errors.release_id, "Candidate release ID is required.");
  assert.equal(validateStartInput(fields, { release_id: RELEASE_ID }).input.strict, false);
});

test("findings are grouped failed-first by severity, with passes kept separately", () => {
  const groups = groupFindings([
    { id: "f-a", severity: "info", outcome: "pass", message: "Passed" },
    { id: "f-b", severity: "medium", outcome: "fail", message: "Medium" },
    { id: "f-c", severity: "critical", outcome: "fail", message: "Critical" },
    { id: "f-d", severity: "high", outcome: "not_evaluated", message: "Skipped" },
    { id: "f-e", severity: "medium", outcome: "fail", message: "Medium 2" },
  ]);
  assert.deepEqual(groups.failed.map((finding) => finding.id), ["f-c", "f-b", "f-e"]);
  assert.deepEqual(groups.failedBySeverity, { critical: 1, medium: 2 });
  assert.deepEqual(groups.passed.map((finding) => finding.id), ["f-a"]);
  assert.deepEqual(groups.notEvaluated.map((finding) => finding.id), ["f-d"]);
  assert.equal(groupFindings(undefined).total, 0);
});

test("worker steps join plan, results and evidence; excerpts are bounded", () => {
  const views = workerStepViews(plan, workerOutput);
  assert.deepEqual(views.map((view) => [view.step.id, view.status, view.evidence.map((record) => record.id)]), [
    ["release", "failed", ["ev-release-r1"]],
    ["queue", "completed", ["ev-queue-r1"]],
  ]);
  const orphan = workerStepViews(plan, { ...workerOutput, steps: [...workerOutput.steps, { step_id: "extra", status: "skipped", findings: [] }] });
  assert.equal(orphan.at(-1).step.id, "extra");
  assert.deepEqual(workerStepViews(plan, null).map((view) => view.status), ["pending", "pending"]);

  assert.deepEqual(evidenceExcerpt(workerOutput.evidence[0]), { text: "", truncated: false });
  assert.equal(evidenceExcerpt(workerOutput.evidence[1]).text, '{\n  "count": 3\n}');
  const long = evidenceExcerpt({ excerpt: { value: "x".repeat(50) }, excerpt_truncated: false }, 20);
  assert.equal(long.truncated, true);
  assert.ok(long.text.endsWith("…"));
  assert.equal(evidenceExcerpt({ excerpt: { a: 1 }, excerpt_truncated: true }).truncated, true);
  assert.equal(provenanceLabel(plan.produced_by), "openai · gpt-5.6-luna · prompt planner v1");
  assert.match(provenanceLabel({ provider: "deterministic", model: "rules", invocations: 2, fallback: true }), /2 invocations · deterministic fallback/);
});

test("Problem Details keep title, detail, code, request ID and field issues", () => {
  const error = new MultiAgentApiError("Invalid", { status: 422, requestId: "req-1", problem: {
    type: "about:blank", title: "Invalid workflow input", status: 422, detail: "release_id is not a UUID", code: "invalid_workflow_input", request_id: "req-1",
    errors: [{ field: "input.release_id", message: "Not a UUID", code: "format" }, { field: "body.note", message: "Too long", code: "max_length" }],
  } });
  const view = problemView(error);
  assert.equal(view.title, "Invalid workflow input");
  assert.equal(view.code, "invalid_workflow_input");
  assert.equal(view.requestId, "req-1");
  assert.equal(view.errors.length, 2);
  assert.deepEqual(fieldProblems(view, ["release_id", "note"]), { release_id: "Not a UUID", note: "Too long" });
  const unavailable = problemView(new MultiAgentApiError("The review service could not be reached.", { status: 503 }));
  assert.equal(unavailable.title, "The multi-agent service is unavailable");
  assert.equal(unavailable.detail, "The review service could not be reached.");
});

test("history lists transitions and counts audit event kinds", () => {
  const view = historyView({ run_id: RUN_ID, state: "approved", history: [
    { sequence: 1, from_state: null, to_state: "planning", actor: "multi-agent-server", role: "system", reason: "Run accepted", at: "2026-10-09T09:41:41Z", round: 1 },
    { sequence: 2, from_state: "planning", to_state: "working", actor: "planner", role: "planner", reason: "Planned", at: "2026-10-09T09:41:52Z", round: 1 },
  ], audit: [
    { sequence: 1, event: "run.created", role: "system", actor: "matthew", at: "2026-10-09T09:41:41Z", round: 1 },
    { sequence: 2, event: "tool.call", role: "worker", actor: "worker", at: "2026-10-09T09:41:55Z", round: 1 },
    { sequence: 3, event: "tool.call", role: "worker", actor: "worker", at: "2026-10-09T09:41:56Z", round: 1 },
  ] });
  assert.deepEqual(view.transitions.map((entry) => `${entry.from}->${entry.to}`), ["null->planning", "planning->working"]);
  assert.deepEqual(view.eventCounts, { "run.created": 1, "tool.call": 2 });
  assert.deepEqual(historyView(null), { transitions: [], audit: [], eventCounts: {} });
});

test("polling runs only while agents work, backs off on failure and slows when hidden", () => {
  assert.equal(nextWorkflowPollDelay("planning"), 1000);
  assert.equal(nextWorkflowPollDelay("working"), 1500);
  assert.equal(nextWorkflowPollDelay("reviewing", 2), 4000);
  assert.equal(nextWorkflowPollDelay("working", 10), 15000);
  assert.equal(nextWorkflowPollDelay("planning", 0, true), 5000);
  assert.equal(nextWorkflowPollDelay("working", 3, true), 48000);
  for (const state of ["awaiting_human", "approved", "partially_accepted", "rejected", "corrected", "failed", "cancelled", "", "unknown"]) {
    assert.equal(nextWorkflowPollDelay(state), null, state);
  }
});

test("identical polls keep their presentation key; visible changes do not", () => {
  const run = { id: RUN_ID, state: "working", updated_at: "one", stages: [] };
  assert.equal(runPresentationKey(run), runPresentationKey({ ...run, updated_at: "two" }));
  assert.notEqual(runPresentationKey(run), runPresentationKey({ ...run, state: "reviewing" }));
});

function response(body, { status = 200, requestId = "request-test" } = {}) {
  return { ok: status >= 200 && status < 300, status, headers: { get: () => requestId }, json: async () => body };
}

test("the client calls only the feature proxy routes with bounded JSON requests", async () => {
  const calls = [];
  const fetcher = async (url, options) => {
    calls.push({ url, method: options.method || "GET", body: options.body ? JSON.parse(options.body) : undefined, headers: options.headers });
    return response({ id: RUN_ID, state: "planning" }, { status: url.endsWith("/release-reviews") ? 202 : 200 });
  };
  const client = createMultiAgentClient({ fetcher, apiRoot: "/api/data-platform/v1/release-reviews/" });
  await client.getTemplate();
  await client.listRuns({ limit: 5, state: "awaiting_human" });
  const started = await client.startRun({ release_id: RELEASE_ID }, { requestedBy: "matthew" });
  await client.getRun("run/../x");
  await client.decide(RUN_ID, { decision: "approve", note: "", actor: "matthew" });
  await client.cancel(RUN_ID, { actor: "matthew" });
  await client.getHistory(RUN_ID);
  assert.equal(started.requestId, "request-test");
  assert.deepEqual(calls.map((call) => `${call.method} ${call.url}`), [
    "GET /api/data-platform/v1/release-reviews/template",
    "GET /api/data-platform/v1/release-reviews?limit=5&state=awaiting_human",
    "POST /api/data-platform/v1/release-reviews",
    "GET /api/data-platform/v1/release-reviews/run%2F..%2Fx",
    `POST /api/data-platform/v1/release-reviews/${RUN_ID}/decision`,
    `POST /api/data-platform/v1/release-reviews/${RUN_ID}/cancel`,
    `GET /api/data-platform/v1/release-reviews/${RUN_ID}/history`,
  ]);
  assert.deepEqual(calls[2].body, { input: { release_id: RELEASE_ID }, requested_by: "matthew" });
  assert.deepEqual(calls[4].body, { decision: "approve", note: "", actor: "matthew" });
  assert.deepEqual(calls[5].body, { actor: "matthew" });
  assert.ok(calls.every((call) => call.headers["X-Request-ID"]));
  assert.throws(() => client.getRun(""), /run ID is required/);
  assert.throws(() => createMultiAgentClient({ fetcher }), /apiRoot/);
});

test("client errors are Problem Details and destroy aborts in-flight requests", async () => {
  const problem = { title: "Multi-agent server unavailable", status: 503, code: "multi_agent_unavailable", request_id: "req-9", detail: "Connection refused" };
  const failing = createMultiAgentClient({ apiRoot: "/x", fetcher: async () => response(problem, { status: 503, requestId: "req-9" }) });
  await assert.rejects(failing.getTemplate(), (error) => error instanceof MultiAgentApiError && error.code === "multi_agent_unavailable" && error.requestId === "req-9" && error.status === 503);

  let observedAbort = false;
  const hanging = (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => {
      observedAbort = true;
      const error = new Error("route changed");
      error.name = "AbortError";
      reject(error);
    }, { once: true });
  });
  const client = createMultiAgentClient({ fetcher: hanging, apiRoot: "/x" });
  const pending = client.getRun(RUN_ID);
  client.destroy();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(observedAbort, true);

  const caller = new AbortController();
  const second = createMultiAgentClient({ fetcher: hanging, apiRoot: "/x" });
  const call = second.getHistory(RUN_ID, { signal: caller.signal });
  caller.abort();
  await assert.rejects(call, { name: "AbortError" });
});
