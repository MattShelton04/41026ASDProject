import assert from "node:assert/strict";
import test from "node:test";
import { recordedToolChecks, activityPresentation } from "./activity.js";
import { evidenceSteps } from "./formats.js";
import { assistantContextFromInput, normalizeAssistantContexts } from "./definitions.js";

test("parallel source checks match results by call ID, including reordered results", () => {
  const run = { status: "adapting", steps: [{ id: "step", phase: "act", status: "succeeded", input: {
    tool_calls: [{ id: "a", tool_name: "example.count.v1" }, { id: "b", tool_name: "context.retrieve.v1" }],
    actions: [{ purpose: "Count records" }, { purpose: "Find guidance" }],
  }, output: { tool_results: [
    { call_id: "b", outcome: "failed", content: {} },
    { call_id: "a", outcome: "succeeded", content: { count: 42 }, duration_ms: 12 },
  ] } }] };
  const checks = recordedToolChecks(run, { "example.count.v1": "Count addresses" });
  assert.equal(checks[0].label, "Count addresses");
  assert.equal(checks[0].result.content.count, 42);
  assert.equal(checks[1].status, "failed");
  assert.equal(activityPresentation(run).done, 1);
  assert.equal(evidenceSteps(run).length, 2);
});

test("elapsed time never fabricates successful source checks", () => {
  const run = { status: "acting", created_at: "2000-01-01T00:00:00Z", steps: [{ status: "running", input: {
    tool_call: { id: "slow", tool_name: "example.lookup.v1" },
  } }] };
  assert.equal(activityPresentation(run).done, 0);
  assert.equal(recordedToolChecks(run)[0].status, "running");
  assert.equal(activityPresentation({ status: "cancelled" }).active, false);
});

test("context input separates readable search text from an exact reference", () => {
  const [definition] = normalizeAssistantContexts([{ id: "record", label: "Record", context: { route: "record" }, parameter: {
    name: "id", label: "Name or ID", pattern: "[0-9a-f-]{36}", searchParameter: "query",
  } }]);
  assert.deepEqual(assistantContextFromInput(definition, "  Sutherland  "), { route: "record", query: "Sutherland" });
  assert.deepEqual(assistantContextFromInput(definition, "2c8a15ce-2f3d-9c88-a648-c28b2da0de38"), { route: "record", id: "2c8a15ce-2f3d-9c88-a648-c28b2da0de38" });
});
