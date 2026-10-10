import assert from "node:assert/strict";
import test from "node:test";

import {
  HUMAN_WAIT_AXIS_MS, MIN_AXIS_MS, advanceReplay, blockingFailures, buildTimeline, checkName, decisionLabel,
  emptyHistory, eventSentence, eventTimes, formatClock, laneView, mergeHistory, nowView, relayView, snapshotAt,
} from "./timeline.js";

const RUN_ID = "c17c66cc-6b40-4685-909a-440401ae8ec7";
const T0 = Date.parse("2026-10-09T09:41:41.000Z");
const at = (seconds) => new Date(T0 + seconds * 1000).toISOString();
const s = (seconds) => seconds * 1000;

// Shaped like the recorded two-round Feature 1 export (c17c66cc): a tool timeout in round 1,
// a correction, an invalid model output retried in round 2, then a partial acceptance.
const plan = {
  summary: "Inspect the release, then read the queue.",
  steps: [
    { id: "release", title: "Inspect the candidate release", tool: "data.release_inspect.v1", arguments: {} },
    { id: "queue", title: "Read the release queue", tool: "data.releases.v1", arguments: {} },
  ],
};
const review = (round, recommendation, failed) => ({
  round, recommendation, summary: `Round ${round} review`,
  findings: [
    { id: `f-release-${round}`, check_id: "release-found", severity: failed ? "critical" : "info", outcome: failed ? "fail" : "pass", message: failed ? "The release was not inspected." : "Inspected.", source: "check" },
    { id: `f-model-${round}`, check_id: null, severity: "medium", outcome: "fail", message: "Completeness is unverified.", source: "model" },
  ],
});
const worker = (round) => ({ round, steps: [], evidence: [], correction_note: round === 2 ? "Retry the inspection." : null });
const stage = (name, round, start, end, status = "completed", detail = null) => ({ stage: name, round, status, started_at: at(start), completed_at: end === null ? null : at(end), detail });
const run = {
  id: RUN_ID, state: "partially_accepted", round: 2, created_at: at(0), updated_at: at(90), completed_at: at(90), plan,
  worker_output: worker(2), review: review(2, "partial", false), superseded: [{ round: 1, worker_output: worker(1), review: review(1, "correct", true) }],
  decisions: [
    { decision: "correct", note: "Retry the inspection.", actor: "matthew", round: 1, decided_at: at(45), accepted_step_ids: [] },
    { decision: "partial", note: "Accept the inspection only.", actor: "matthew", round: 2, decided_at: at(90), accepted_step_ids: ["release"] },
  ],
  stages: [
    stage("planner", 1, 0, 11), stage("worker", 1, 11, 21.5), stage("reviewer", 1, 21.5, 25.5), stage("human", 1, 25.5, 45, "completed", "correct"),
    stage("worker", 2, 45, 61), stage("reviewer", 2, 61, 68), stage("human", 2, 68, 90, "completed", "partial"),
  ],
  available_actions: [],
};
let sequence = 0;
const transition = (from, to, seconds, round, role) => ({ sequence: ++sequence, from_state: from, to_state: to, at: at(seconds), round, role, actor: role, reason: `${from || "start"} to ${to}` });
const history = [
  transition(null, "planning", 0, 1, "system"), transition("planning", "working", 11, 1, "planner"),
  transition("working", "reviewing", 21.5, 1, "worker"), transition("reviewing", "awaiting_human", 25.5, 1, "reviewer"),
  transition("awaiting_human", "working", 45, 2, "human"), transition("working", "reviewing", 61, 2, "worker"),
  transition("reviewing", "awaiting_human", 68, 2, "reviewer"), transition("awaiting_human", "partially_accepted", 90, 2, "human"),
];
sequence = 0;
const event = (name, seconds, round, role, detail = {}) => ({ sequence: ++sequence, event: name, at: at(seconds), round, role, actor: role, detail });
const audit = [
  event("run.created", 0, 1, "system"), event("agent.handoff", 0, 1, "system", { from: "system", to: "planner" }),
  event("model.started", 0.3, 1, "planner", { attempt: 1 }), event("model.invocation", 11, 1, "planner", { attempt: 1, outcome: "succeeded", duration_ms: 10700, model: "gpt-5.6-luna" }),
  event("plan.created", 11, 1, "planner", { steps: plan.steps }), event("agent.handoff", 11, 1, "planner", { from: "planner", to: "worker", steps: 2 }),
  event("tool.call", 14, 1, "worker", { tool_name: "data.release_inspect.v1", outcome: "timed_out", duration_ms: 3000, step_id: "release" }),
  event("tool.call", 15.2, 1, "worker", { tool_name: "data.releases.v1", outcome: "succeeded", duration_ms: 1000, step_id: "queue" }),
  event("model.started", 15.3, 1, "worker", { attempt: 1 }), event("model.invocation", 21.5, 1, "worker", { attempt: 1, outcome: "succeeded", duration_ms: 6200 }),
  event("worker.completed", 21.5, 1, "worker", { evidence_ids: ["a", "b"] }), event("agent.handoff", 21.5, 1, "worker", { from: "worker", to: "reviewer" }),
  event("model.invocation", 25.5, 1, "reviewer", { attempt: 1, outcome: "succeeded", duration_ms: 3900 }), event("review.completed", 25.5, 1, "reviewer", { findings: 2 }),
  event("agent.handoff", 25.5, 1, "reviewer", { from: "reviewer", to: "human" }),
  event("decision.recorded", 45, 2, "human", { decision: "correct", decision_round: 1 }), event("agent.handoff", 45, 2, "human", { from: "human", to: "worker", correction_note: "Retry the inspection." }),
  event("tool.call", 46, 2, "worker", { tool_name: "data.release_inspect.v1", outcome: "succeeded", duration_ms: 670, step_id: "release" }),
  event("tool.call", 46.3, 2, "worker", { tool_name: "data.releases.v1", outcome: "succeeded", duration_ms: 80, step_id: "queue" }),
  event("model.started", 46.4, 2, "worker", { attempt: 1 }), event("model.invocation", 55.3, 2, "worker", { attempt: 1, outcome: "invalid_output", duration_ms: 8900 }),
  event("model.started", 55.4, 2, "worker", { attempt: 2 }), event("model.invocation", 61, 2, "worker", { attempt: 2, outcome: "succeeded", duration_ms: 5600 }),
  event("worker.completed", 61, 2, "worker", { evidence_ids: ["c", "d"] }), event("agent.handoff", 61, 2, "worker", { from: "worker", to: "reviewer" }),
  event("model.invocation", 68, 2, "reviewer", { attempt: 1, outcome: "succeeded", duration_ms: 7000 }), event("review.completed", 68, 2, "reviewer", { findings: 2 }),
  event("agent.handoff", 68, 2, "reviewer", { from: "reviewer", to: "human" }),
  event("decision.recorded", 90, 2, "human", { decision: "partial", decision_round: 2 }),
];
const recorded = mergeHistory(emptyHistory(RUN_ID), { run_id: RUN_ID, history, audit });

test("history pages merge by sequence and keep a cursor for each numbering", () => {
  const first = mergeHistory(emptyHistory(RUN_ID), { run_id: RUN_ID, history: history.slice(0, 2), audit: audit.slice(0, 3) });
  assert.deepEqual([first.afterHistory, first.afterAudit], [2, 3]);
  const next = mergeHistory(first, { run_id: RUN_ID, history: [history[1], history[2]], audit: [audit[4], audit[3], { sequence: "x" }] });
  assert.deepEqual(next.history.map((entry) => entry.sequence), [1, 2, 3], "repeats are dropped and order is by sequence");
  assert.deepEqual(next.audit.map((entry) => entry.sequence), [1, 2, 3, 4, 5]);
  assert.deepEqual([next.afterHistory, next.afterAudit], [3, 5]);
  const other = mergeHistory(next, { run_id: "another-run", history: [history[0]], audit: [] });
  assert.deepEqual([other.runId, other.history.length, other.afterAudit], ["another-run", 1, 0], "a different run starts again");
});

test("snapshots show only what was recorded by each moment", () => {
  const model = buildTimeline(run, recorded);
  assert.equal(model.end, s(90));
  assert.deepEqual(model.decisionPoints.map((point) => [point.round, point.at, point.decidedAt, point.decision.decision]), [[1, s(25.5), s(45), "correct"], [2, s(68), s(90), "partial"]]);

  // The human stage opens 1 ms before its transition is written; the point waits for both.
  const skewed = buildTimeline({ ...run, stages: run.stages.map((item) => (item.stage === "human" && item.round === 1 ? { ...item, started_at: new Date(T0 + s(25.5) - 1).toISOString() } : item)) }, recorded);
  assert.equal(skewed.decisionPoints[0].at, s(25.5));
  assert.equal(snapshotAt(skewed, skewed.decisionPoints[0].at).state, "awaiting_human");
  assert.equal(snapshotAt(skewed, skewed.decisionPoints[0].at).rounds[1].review.recommendation, "correct");

  const planning = snapshotAt(model, s(5));
  assert.equal(planning.state, "planning");
  assert.equal(planning.plan, null, "the plan is not shown before the Planner hands off");
  assert.deepEqual(planning.stages.map((item) => [item.stage, item.status]), [["planner", "running"]]);
  assert.equal(nowView(model, planning).text, "The Planner is choosing read-only steps · waiting on the model");

  const calling = snapshotAt(model, s(14.5));
  assert.equal(calling.state, "working");
  assert.equal(calling.plan, plan);
  assert.equal(calling.rounds[1].toolCalls.length, 1);
  assert.equal(calling.rounds[1].worker, null, "findings arrive with worker.completed, not before");
  assert.equal(nowView(model, calling).text, "The Worker is calling tools (1 of 2 done)");
  assert.deepEqual(nowView(model, calling).tools.map((tool) => [tool.tool, tool.ok]), [["data.release_inspect", false]]);

  const writing = snapshotAt(model, s(18));
  assert.equal(nowView(model, writing).text, "The Worker is writing findings from 2 tool results · waiting on the model");
  assert.equal(nowView(model, writing).sinceMs, s(7));

  const waiting = snapshotAt(model, s(30));
  assert.equal(waiting.state, "awaiting_human");
  assert.equal(waiting.full, false);
  assert.equal(waiting.rounds[1].review.recommendation, "correct");
  assert.deepEqual(waiting.actions, ["approve", "correct", "partial", "reject", "cancel"]);
  assert.equal(waiting.decisions.length, 0);
  assert.equal(nowView(model, waiting).text, "Waiting for a person to decide.");
  assert.equal(waiting.stages.at(-1).status, "waiting");

  const retry = snapshotAt(model, s(56));
  assert.equal(retry.round, 2);
  assert.equal(retry.rounds[2].correctionNote, "Retry the inspection.");
  assert.equal(retry.rounds[1].review.recommendation, "correct", "round 1 stays available for comparison");
  assert.equal(nowView(model, retry).text, "The Worker is writing findings from 2 tool results · waiting on the model (attempt 2)");

  const end = snapshotAt(model);
  assert.equal(end.full, true);
  assert.equal(end.state, "partially_accepted");
  assert.equal(end.decisions.length, 2);
  assert.equal(end.rounds[2].review, run.review);
  assert.equal(nowView(model, end).tone, "done");
});

test("waits for a person are shortened on the axis and mapped back exactly", () => {
  const model = buildTimeline(run, recorded);
  assert.deepEqual(model.squeezes.map((item) => [item.real, item.axis]), [[s(19.5), HUMAN_WAIT_AXIS_MS], [s(22), HUMAN_WAIT_AXIS_MS]]);
  assert.equal(model.toAxis(s(25.5)), s(25.5));
  assert.equal(model.toAxis(s(45)), s(25.5) + HUMAN_WAIT_AXIS_MS);
  assert.equal(Math.round(model.axisEnd), s(90) - (s(19.5) - HUMAN_WAIT_AXIS_MS) - (s(22) - HUMAN_WAIT_AXIS_MS));
  for (const real of [0, s(10), s(30), s(44.9), s(50), s(80), s(90)]) assert.ok(Math.abs(model.toReal(model.toAxis(real)) - real) < 1, `round trip at ${real}`);
  assert.equal(formatClock(model.axisEnd), "0:55");
});

test("lanes place stages, model calls, tool pins and hand-offs on one growing axis", () => {
  const model = buildTimeline(run, recorded);
  const view = laneView(model, snapshotAt(model));
  assert.deepEqual(view.lanes.map((lane) => [lane.role, lane.status]), [["planner", "completed"], ["worker", "completed"], ["reviewer", "completed"], ["human", "completed"]]);
  const workerLane = view.lanes[1];
  assert.deepEqual(workerLane.tools.map((tool) => tool.failed), [true, false, false, false]);
  assert.deepEqual(workerLane.models.map((call) => call.retry), [false, true, false]);
  for (const lane of view.lanes) {
    for (const item of [...lane.segments, ...lane.models, ...lane.tools]) {
      assert.ok(item.x >= 0 && item.x <= 100 && (item.width ?? 0) >= 0 && item.x + (item.width ?? 0) <= 100.01, `${item.key} stays inside the drawing`);
    }
  }
  assert.ok(view.lanes[3].segments.every((segment) => segment.shortened), "both waits are marked as shortened");
  assert.deepEqual(view.batons.map((baton) => [baton.from, baton.to, baton.correction]), [[0, 1, false], [1, 2, false], [2, 3, false], [3, 1, true], [1, 2, false], [2, 3, false]]);
  assert.equal(view.roundMark.round, 2);
  assert.equal(view.playhead, null, "a finished run has no playhead");
  assert.equal(view.lanes[3].detail, "partial");

  const early = laneView(model, snapshotAt(model, s(3)));
  assert.ok(early.playhead > 0 && early.playhead < 100, "the axis leaves headroom after now");
  assert.equal(early.lanes[0].segments[0].width, early.playhead, "the running stage ends at now; nothing later is drawn");
  assert.equal(early.lanes[1].segments.length, 0);
});

test("an open run extends to now and an open wait for a person is shortened as it grows", () => {
  const open = { ...run, state: "awaiting_human", round: 1, completed_at: null, updated_at: at(25.5), decisions: [], superseded: [], worker_output: worker(1), review: review(1, "correct", true), available_actions: ["approve", "correct", "partial", "reject", "cancel"], stages: [...run.stages.slice(0, 3), stage("human", 1, 25.5, null, "running")] };
  const model = buildTimeline(open, mergeHistory(emptyHistory(RUN_ID), { run_id: RUN_ID, history: history.slice(0, 4), audit: audit.slice(0, 15) }), { now: T0 + s(125.5) });
  assert.equal(model.end, s(125.5));
  assert.deepEqual(model.squeezes.map((item) => [item.real, item.axis]), [[s(100), HUMAN_WAIT_AXIS_MS]]);
  const snapshot = snapshotAt(model);
  assert.equal(snapshot.full, true);
  assert.equal(snapshot.stages.at(-1).status, "waiting");
  const now = nowView(model, snapshot);
  assert.equal(now.tone, "you");
  assert.equal(now.sinceMs, s(100));
  const lanes = laneView(model, snapshot);
  assert.ok(lanes.playhead > 90 && lanes.playhead < 100);
  assert.equal(lanes.lanes[3].elapsedMs, s(100));

  // One second into a fresh run the axis still spans MIN_AXIS_MS, so the first stage is short.
  const fresh = { ...open, state: "planning", updated_at: at(0), stages: [stage("planner", 1, 0, null, "running")] };
  const freshModel = buildTimeline(fresh, null, { now: T0 + 1000 });
  const freshLanes = laneView(freshModel, snapshotAt(freshModel));
  assert.equal(freshLanes.playhead, Math.round((1000 / MIN_AXIS_MS) * 10000) / 100);
  assert.equal(freshLanes.lanes[0].segments[0].width, freshLanes.playhead);
  assert.equal(nowView(freshModel, snapshotAt(freshModel)).text, "The Planner is choosing read-only steps", "no history: no claim about the model");
});

test("the relay strip follows the baton and shows the correction loop", () => {
  const model = buildTimeline(run, recorded);
  assert.deepEqual(relayView(snapshotAt(model, s(30))), {
    stations: [
      { role: "planner", status: "completed", elapsedMs: null, durationMs: s(11), detail: null },
      { role: "worker", status: "completed", elapsedMs: null, durationMs: s(10.5), detail: null },
      { role: "reviewer", status: "completed", elapsedMs: null, durationMs: s(4), detail: null },
      { role: "human", status: "waiting", elapsedMs: s(4.5), durationMs: null, detail: null },
    ],
    baton: 3, loop: false,
  });
  const second = relayView(snapshotAt(model, s(50)));
  assert.equal(second.baton, 1);
  assert.equal(second.loop, true);
  assert.equal(second.stations[1].elapsedMs, s(5));
  assert.equal(relayView(snapshotAt(model)).baton, 3);
});

test("a replay plays agent time, shortens waits and stops once at each decision", () => {
  const model = buildTimeline(run, recorded);
  const paused = new Set();
  let step = advanceReplay(model, 0, s(40), paused);
  assert.deepEqual([step.t, step.point?.round, step.ended], [s(25.5), 1, false]);
  paused.add(1);
  step = advanceReplay(model, step.t, HUMAN_WAIT_AXIS_MS / 2, paused);
  assert.ok(Math.abs(step.t - (s(25.5) + s(19.5) / 2)) < 1, "half the shortened wait is half the real wait");
  step = advanceReplay(model, step.t, s(60), paused);
  assert.deepEqual([step.t, step.point?.round], [s(68), 2]);
  paused.add(2);
  step = advanceReplay(model, step.t, s(600), paused);
  assert.deepEqual([step.t, step.point, step.ended], [s(90), null, true]);
  const times = eventTimes(model);
  assert.equal(times[0], 0);
  assert.equal(times.at(-1), s(90));
  assert.deepEqual(times, [...new Set(times)].sort((left, right) => left - right));
});

test("events become plain sentences and decisions use the plain-language labels", () => {
  const model = buildTimeline(run, recorded);
  const sentences = model.events.filter((item) => item.kind !== "transition").map((item) => eventSentence(item));
  assert.ok(sentences.includes("Hand-off from Reviewer to Person."));
  assert.ok(sentences.includes("Worker called data.release_inspect.v1: timed out in 3.0 s."));
  assert.ok(sentences.includes("Worker model call invalid output after 8.9 s."));
  assert.ok(sentences.includes("Worker model call started (attempt 2)."));
  assert.ok(sentences.includes("worker decided: Send back once.") === false);
  assert.ok(sentences.includes("human decided: Send back once."));
  assert.ok(sentences.includes("human decided: Accept some steps."));
  assert.equal(decisionLabel("correct", 2), "Final correction");
  assert.equal(blockingFailures(review(1, "correct", true)), 1);
  assert.equal(blockingFailures(review(2, "partial", false)), 0);
  assert.equal(checkName(review(1, "correct", true).findings[0]), "Release found");
  assert.equal(checkName(review(1, "correct", true).findings[1]), "Reviewer: Completeness is unverified.");
});
