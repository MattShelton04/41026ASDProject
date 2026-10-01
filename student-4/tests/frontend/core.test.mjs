import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  API_BASE,
  buildReviewPayload,
  buildUpdatePayload,
  dispositionLabel,
  evidenceBadgeClass,
  evidenceStateLabel,
  extractQuestions,
  formatType,
  mapLayerDefinitions,
  parseRoute,
  problemMessage,
  statusBadgeClass,
  statusLabel,
  summariseReview,
  toggleChecklist,
} from "../../frontend/app.js";

test("status labels map known and unknown values", () => {
  assert.equal(statusLabel("draft"), "Draft");
  assert.equal(statusLabel("in_review"), "In review");
  assert.equal(statusLabel("mystery"), "Unknown");
});

test("disposition labels map known and unknown values", () => {
  assert.equal(dispositionLabel("do_not_proceed"), "Do not proceed");
  assert.equal(dispositionLabel("mystery"), "Unknown");
});

test("evidence state labels map the four supported states", () => {
  assert.equal(evidenceStateLabel("confirmed"), "Confirmed");
  assert.equal(evidenceStateLabel("partial_coverage"), "Partial coverage");
  assert.equal(evidenceStateLabel("mystery"), "Unknown");
});

test("summariseReview composes a readable single line", () => {
  const line = summariseReview({
    title: "Review 1",
    address_display: "11 Example Street, Sydney NSW 2000",
    status: "completed",
  });
  assert.equal(line, "Review 1 - 11 Example Street, Sydney NSW 2000 (Completed)");
});

test("API base is a same-origin versioned path", () => {
  assert.equal(API_BASE, "/api/due-diligence/v1");
});

test("status badge class maps to shared evidence modifiers", () => {
  assert.equal(statusBadgeClass("completed"), "ps-badge--confirmed");
  assert.equal(statusBadgeClass("in_review"), "ps-badge--info");
  assert.equal(statusBadgeClass("draft"), "ps-badge--planned");
  assert.equal(statusBadgeClass("archived"), "");
  assert.equal(statusBadgeClass("mystery"), "");
});

test("evidence badge class maps evidence states to shared modifiers", () => {
  assert.equal(evidenceBadgeClass("confirmed"), "ps-badge--confirmed");
  assert.equal(evidenceBadgeClass("partial_coverage"), "ps-badge--partial");
  assert.equal(evidenceBadgeClass("non_intersection"), "ps-badge--info");
  assert.equal(evidenceBadgeClass("unavailable"), "");
  assert.equal(evidenceBadgeClass("mystery"), "");
});

test("formatType turns snake_case into a readable label", () => {
  assert.equal(formatType("floor_space_ratio"), "Floor space ratio");
  assert.equal(formatType("building_order"), "Building order");
  assert.equal(formatType("zoning"), "Zoning");
  assert.equal(formatType(""), "");
});

test("parseRoute distinguishes the list and detail routes", () => {
  assert.deepEqual(parseRoute("#site-reviews"), { name: "list" });
  assert.deepEqual(parseRoute(""), { name: "list" });
  assert.deepEqual(parseRoute("#other"), { name: "list" });
  assert.deepEqual(parseRoute("#site-reviews/a0000000-0000-0000-0000-000000000001"), {
    name: "detail",
    id: "a0000000-0000-0000-0000-000000000001",
  });
});

test("buildReviewPayload trims fields and keeps a checklist", () => {
  const payload = buildReviewPayload({
    propertyRef: " a0 ",
    addressDisplay: " 11 Example Street ",
    title: "  My review ",
    status: "in_review",
    disposition: "proceed",
    notes: "  note ",
  });
  assert.equal(payload.property_ref, "a0");
  assert.equal(payload.address_display, "11 Example Street");
  assert.equal(payload.title, "My review");
  assert.equal(payload.status, "in_review");
  assert.equal(payload.disposition, "proceed");
  assert.equal(payload.notes, "note");
  assert.ok(Array.isArray(payload.checklist) && payload.checklist.length >= 1);
});

test("buildReviewPayload applies safe defaults", () => {
  const payload = buildReviewPayload({ propertyRef: "a0", addressDisplay: "x", title: "t" });
  assert.equal(payload.status, "draft");
  assert.equal(payload.disposition, "undecided");
  assert.equal(payload.notes, "");
  assert.deepEqual(payload.checklist[0], {
    item: "Confirm zoning permits the intended use",
    done: false,
  });
});

test("problemMessage maps known error codes", () => {
  assert.equal(
    problemMessage({ code: "unknown_property" }, 422),
    "That property is not verified in Feature 1.",
  );
  assert.equal(problemMessage({ code: "invalid_site_review", detail: "bad title" }, 422), "bad title");
  assert.match(problemMessage({}, 500), /status 500/);
});

test("buildUpdatePayload trims text and defaults status/disposition", () => {
  const payload = buildUpdatePayload({
    title: "  Edited ",
    status: "completed",
    disposition: "hold",
    notes: " n ",
  });
  assert.deepEqual(payload, { title: "Edited", status: "completed", disposition: "hold", notes: "n" });
  const defaults = buildUpdatePayload({ title: "t" });
  assert.equal(defaults.status, "draft");
  assert.equal(defaults.disposition, "undecided");
  assert.equal(defaults.notes, "");
});

test("toggleChecklist flips one item without mutating the input", () => {
  const original = [
    { item: "a", done: false },
    { item: "b", done: false },
  ];
  const updated = toggleChecklist(original, 1, true);
  assert.equal(updated[1].done, true);
  assert.equal(updated[0].done, false);
  assert.equal(original[1].done, false);
  assert.deepEqual(toggleChecklist(null, 0, true), []);
});

test("mapLayerDefinitions builds a point layer plus a polygon layer per hazard", () => {
  const mapData = {
    property: { type: "FeatureCollection", features: [{ type: "Feature" }] },
    layers: [
      {
        id: "flood",
        label: "Flood planning area",
        data: { type: "FeatureCollection", features: [] },
      },
    ],
  };
  const defs = mapLayerDefinitions(mapData);
  assert.equal(defs.length, 2);
  assert.equal(defs[0].id, "property");
  assert.equal(defs[0].kind, "point");
  assert.equal(defs[1].id, "flood");
  assert.equal(defs[1].kind, "polygon");
  assert.deepEqual(mapLayerDefinitions({}), []);
});

test("extractQuestions prefers an explicit questions array", () => {
  assert.deepEqual(
    extractQuestions({ questions: ["Confirm zoning?", { question: "Check flood?" }, "  "] }),
    ["Confirm zoning?", "Check flood?"],
  );
});

test("extractQuestions uses default.v7 findings plus the recommended next step", () => {
  const result = {
    findings: ["Verify the unavailable bushfire mapping.", "Confirm the partial building height."],
    recommended_next_step: "Engage a qualified planner before proceeding.",
  };
  assert.deepEqual(extractQuestions(result), [
    "Verify the unavailable bushfire mapping.",
    "Confirm the partial building height.",
    "Engage a qualified planner before proceeding.",
  ]);
});

test("extractQuestions falls back to question-like lines in text", () => {
  const result = {
    summary: "1. Confirm the zoning permits your use?\n- Is the property flood affected?\nNot a question.",
  };
  assert.deepEqual(extractQuestions(result), [
    "Confirm the zoning permits your use?",
    "Is the property flood affected?",
  ]);
  assert.deepEqual(extractQuestions(null), []);
});

test("malformed percent escapes fall back to the review list", () => {
  assert.deepEqual(parseRoute("#site-reviews/%E0%A4%A"), {name: "list"});
});

test("default checklists are not shared mutable state between reviews", () => {
  const first = buildReviewPayload({title: "first"});
  first.checklist[0].done = true;
  assert.equal(buildReviewPayload({title: "second"}).checklist[0].done, false);
});

const appSource = readFileSync("student-4/frontend/app.js", "utf8");
const pageSource = readFileSync("student-4/frontend/index.html", "utf8");

test("the review detail view mounts the shared grounded assistant scoped to the review", () => {
  assert.match(appSource, /createFeatureAssistant/);
  assert.match(appSource, /from "\.\/ai-chat\/index\.js"/);
  assert.match(appSource, /apiRoot: `\$\{API_BASE\}\/assistant`/);
  assert.match(appSource, /featureKey: "student-4-due-diligence"/);
  // The selected review must reach the turn as context, or every answer is unscoped.
  assert.match(appSource, /setContext\(/);
  assert.match(appSource, /site_review_id: review\.id/);
});

test("the due-diligence page serves the shared grounded renderer styles", () => {
  // Criterion 4 is marked on citations and confidence, which the shared renderer owns.
  assert.match(pageSource, /ai-chat\/styles\.css/);
});
