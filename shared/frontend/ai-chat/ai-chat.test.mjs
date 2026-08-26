import assert from "node:assert/strict";
import test from "node:test";

import { createAssistantClient } from "./client.js";
import {
  assistantStatus, defaultSuggestions, findAssistantScope, normalizeAssistantScopes,
} from "./definitions.js";
import { answerSections, evidenceSteps, normalizeTurnDetail, shortRunId } from "./formats.js";
import { mergeAssistantEvents, nextAssistantPollDelay, restoreEventCursor } from "./polling.js";

function response(body, status = 200) {
  return { ok: status >= 200 && status < 300, status, headers: { get: () => "request-test" }, json: async () => body };
}

test("assistant scope semantics are injected and validated by the shared package", () => {
  const scopes = normalizeAssistantScopes([
    { id: "global", label: "Whole app", description: "Every available area." },
    { id: "feature-x", label: "Feature X", description: "Feature-owned tools." },
  ]);
  assert.equal(findAssistantScope("feature-x", scopes).label, "Feature X");
  assert.equal(findAssistantScope("unknown", scopes).id, "global");
  assert.equal(normalizeAssistantScopes([{ id: "bad" }])[0].id, "application");
  assert.match(assistantStatus("acting").detail, /allowlisted/);
  assert.equal(defaultSuggestions().length, 2);
});

test("structured answers prefer user-facing sections and omit nested opaque state", () => {
  const sections = answerSections({
    summary: "Accepted data remains live.",
    findings: ["Candidate checks passed", "Publication is pending"],
    recommended_next_step: "Review the candidate.",
    confidence: "bounded",
    nested_private_state: { hidden: true },
  });
  assert.deepEqual(sections.map((item) => item.label), ["Answer", "Key findings", "Useful next step", "Confidence"]);
  assert.equal(shortRunId("12345678-0000-0000-0000-000000000000"), "12345678…");
});

test("run details and evidence normalize without a private-reasoning field", () => {
  const detail = normalizeTurnDetail({
    run: { id: "run-1", status: "succeeded" },
    steps: [{ phase: "act", status: "succeeded", input: { tool_call: { tool_name: "feature.search.v1" } }, output: { tool_result: { outcome: "succeeded", evidence_references: ["entity:1"] } } }],
  });
  const evidence = evidenceSteps(detail);
  assert.equal(detail.steps.length, 1);
  assert.equal(evidence[0].label, "Feature.search.v1");
  assert.deepEqual(evidence[0].references, ["entity:1"]);
  assert.equal(Object.hasOwn(evidence[0], "reasoning"), false);
});

test("event cursors merge duplicate pages and terminal polling stops", () => {
  assert.equal(restoreEventCursor("bad"), 0);
  const merged = mergeAssistantEvents([{ id: 1, value: "old" }], [{ id: 1, value: "new" }, { id: 2 }]);
  assert.deepEqual(merged.items, [{ id: 1, value: "new" }, { id: 2 }]);
  assert.equal(merged.cursor, 2);
  assert.equal(nextAssistantPollDelay("planning"), 850);
  assert.equal(nextAssistantPollDelay("planning", 0, true), 5000);
  assert.equal(nextAssistantPollDelay("succeeded"), null);
});

test("assistant client uses the wrapper-supplied same-origin API root", async () => {
  const calls = [];
  const client = createAssistantClient({
    apiRoot: "/api/feature-x/v1/assistant",
    fetcher: async (url, options) => { calls.push({ url, options }); return response({ id: "run-1", status: "queued" }, 202); },
  });
  await client.createTurn({ message: "What can this do?", scope: "feature", context: {} });
  assert.equal(calls[0].url, "/api/feature-x/v1/assistant/turns");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(JSON.parse(calls[0].options.body).scope, "feature");
});

test("component source preserves disclosure/focus state and surfaces polling warnings", async () => {
  const source = await import("node:fs").then(({ readFileSync }) => readFileSync(new URL("./controller.js", import.meta.url), "utf8"));
  const components = await import("node:fs").then(({ readFileSync }) => readFileSync(new URL("./components.js", import.meta.url), "utf8"));
  assert.match(source, /disclosureState/);
  assert.match(source, /transcriptFocusKey/);
  assert.match(components, /pollWarning/);
  assert.match(components, /retry automatically/);
  assert.match(source, /turn\.run\.status !== previousStatus/);
  assert.match(source, /turn\.cancelWarning = error;\s+renderTranscript\(\)/);
  assert.match(components, /Cancellation could not be requested/);
});
