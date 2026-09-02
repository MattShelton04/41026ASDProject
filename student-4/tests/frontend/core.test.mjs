import assert from "node:assert/strict";
import { test } from "node:test";

import {
  API_BASE,
  dispositionLabel,
  evidenceBadgeClass,
  evidenceStateLabel,
  formatType,
  parseRoute,
  statusBadgeClass,
  statusLabel,
  summariseReview,
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
