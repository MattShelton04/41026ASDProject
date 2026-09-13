import assert from "node:assert/strict";
import test from "node:test";
import { createReviewClient, recordedReviewTurn, reviewContextOptions } from "../../frontend/integration/ai-review.js";
import { completedTurnHistory } from "../../../shared/frontend/ai-chat/index.js";
import { propertyActivityUrl } from "../../frontend/integration/activity.js";
import { resolveResearchAreaContext } from "../../../shared/frontend/operations/ai-mode/contexts.js";

test("review handoffs round-trip through the shared app's approved return context", () => {
  for (const baseUrl of ["http://localhost:5200/", "https://example.test/features/data-platform/"]) {
    const returnTo = "/features/data-platform/#ai/577e8221-e393-442f-9e6f-b81505dc24ab";
    const url = new URL(propertyActivityUrl("run", { baseUrl, returnTo }));
    assert.equal(resolveResearchAreaContext(url.searchParams).returnTo, returnTo);
    assert.equal(url.origin, baseUrl.startsWith("http://localhost") ? "http://localhost:5100" : "https://example.test");
  }
});

test("recorded reviews retain typed findings, steps and explicit context for follow-ups", () => {
  const turn = recordedReviewTurn({
    run: { id: "review", status: "succeeded", objective: "release_id: candidate. predecessor_release_id: accepted. Use only these exact identifiers; never send placeholders to tools. Compare the datasets.", trusted_identifiers: [{ kind: "release_id", value: "candidate" }, { kind: "release_id", value: "accepted" }], final_result: { summary: "Checks passed", findings: [{ text: "Counts match" }] } },
    steps: [{ phase: "act" }],
  });
  assert.equal(turn.message, "Compare the datasets.");
  assert.deepEqual(turn.context, { route: "releases/detail", release_id: "candidate" });
  assert.equal(turn.canCancel, false);
  assert.equal(turn.run.steps.length, 1);
  const history = completedTurnHistory([turn]);
  assert.match(history[1].content, /Counts match/);
  assert.doesNotMatch(history[1].content, /object Object/);
});

test("assistant history extracts the user question and never trusts identifiers in its prose", () => {
  const turn = recordedReviewTurn({ id: "review", objective: 'Conversational assistant turn.\nCurrent user question: "Explain release_id: invented"\nValidated page context:\nrelease_id: invented', trusted_identifiers: [{ kind: "run_id", value: "real-update" }], tool_allowlist: ["data.run_explain.v1"] });
  assert.equal(turn.message, "Explain release_id: invented");
  assert.deepEqual(turn.context, { route: "runs/detail", ingestion_run_id: "real-update" });
  assert.deepEqual(recordedReviewTurn({ objective: "release_id: untrusted" }).context, {});
});

test("recent review choices exclude settled releases and retain lookup beyond the inventory", () => {
  const options = reviewContextOptions(["candidate", "rejected", "accepted", "superseded", "draft"].map((status) => ({ id: status, status, dataset_id: "Dataset", release_version: "1" })));
  assert.deepEqual(options.map((item) => item.id), ["candidate", "rejected", "release"]);
  assert.equal(options[2].parameter.searchParameter, "query");
});

test("legacy reads use agent history while new turns and cancellation use the shared client", async () => {
  const calls = [];
  const client = Object.fromEntries(["getTurn", "getEvents", "createTurn", "cancelTurn", "destroy"].map((name) => [name, (...args) => { calls.push([name, ...args]); return { body: { id: "new" } }; }]));
  const review = createReviewClient({ client, request: async (path) => { calls.push(["request", path]); }, recordedTurn: { run: { id: "old" } } });
  await review.getTurn("old");
  await review.getEvents("old", 7);
  await review.getTurn("new");
  await review.createTurn({ message: "Follow up" });
  await review.cancelTurn("new");
  review.destroy();
  assert.deepEqual(calls, [["request", "agent-runs/old"], ["request", "agent-runs/old/events?after=7&limit=100"], ["getTurn", "new"], ["createTurn", { message: "Follow up" }], ["cancelTurn", "new"], ["destroy"]]);
});
