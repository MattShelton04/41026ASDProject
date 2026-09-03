import assert from "node:assert/strict";
import { test } from "node:test";

import {
  API_BASE,
  ApiProblem,
  buildCasePayload,
  buildNotePayload,
  buildPropertyPayload,
  buildTaskPayload,
  createBuyerCaseApi,
  escapeHtml,
  formatBudget,
  mergePreferences,
  navigateForFollowUp,
  parseRoute,
  preferenceStringsFromText,
  projectPreferenceLists,
  renderNoteItems,
  renderEvidence,
  renderPropertyItems,
  renderSummaryRun,
  renderTaskItems,
  statusLabel,
  summaryWorkflowView,
  targetSuburbsFromText,
  uiStateForError,
  validateCaseInput,
} from "../../frontend/app.js";

function jsonResponse(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

test("API base is a same-origin versioned public path", () => {
  assert.equal(API_BASE, "/api/buyer-workspaces/v1");
});

test("target suburb text becomes unique NSW state/locality objects", () => {
  assert.deepEqual(targetSuburbsFromText(" Mascot\nNEWTOWN, mascot "), [
    { state: "NSW", locality: "MASCOT" },
    { state: "NSW", locality: "NEWTOWN" },
  ]);
});

test("buyer case payload defaults active and includes update version", () => {
  const created = buildCasePayload({
    name: " First home ",
    budgetMin: "700000",
    budgetMax: "900000",
    suburbs: "Mascot",
    status: "active",
  });
  assert.equal(created.payload.name, "First home");
  assert.equal(created.payload.status, "active");
  assert.deepEqual(created.payload.target_suburbs, [{ state: "NSW", locality: "MASCOT" }]);
  const updated = buildCasePayload({ name: "Case", budgetMin: "", budgetMax: "", suburbs: "", status: "paused" }, 4);
  assert.equal(updated.payload.version, 4);
});

test("preferences are bounded, deduplicated, projected and round-trip unknown keys", () => {
  assert.deepEqual(preferenceStringsFromText(" apartment \nApartment, terrace"), [
    "apartment",
    "terrace",
  ]);
  const existing = {
    dwelling_types: ["apartment"],
    priorities: ["transport"],
    accessibility: { step_free: true },
  };
  const merged = mergePreferences(existing, ["terrace"], ["planning evidence"]);
  assert.deepEqual(merged, {
    dwelling_types: ["terrace"],
    priorities: ["planning evidence"],
    accessibility: { step_free: true },
  });
  assert.deepEqual(projectPreferenceLists(merged), {
    dwellingTypes: ["terrace"],
    priorities: ["planning evidence"],
  });
  const built = buildCasePayload(
    {
      name: "Case",
      budgetMin: "",
      budgetMax: "",
      suburbs: "",
      dwellingTypes: " terrace \nTerrace",
      priorities: " planning evidence ",
      status: "active",
    },
    2,
    existing,
  );
  assert.equal(built.payload.version, 2);
  assert.deepEqual(built.payload.preferences.accessibility, { step_free: true });
  assert.deepEqual(built.payload.preferences.dwelling_types, ["terrace"]);
});

test("preference validation rejects excessive counts and lengths", () => {
  const tooMany = Array.from({ length: 21 }, (_, index) => `priority-${index}`).join("\n");
  const countResult = validateCaseInput({ name: "Case", status: "active", priorities: tooMany });
  assert.match(countResult.errors.preferences, /at most 20/);
  const lengthResult = validateCaseInput({ name: "Case", status: "active", dwellingTypes: "x".repeat(101) });
  assert.match(lengthResult.errors.preferences, /at most 100/);
});

test("client-side validation covers invalid name and budget", () => {
  const value = validateCaseInput({
    name: "",
    budgetMin: "900000",
    budgetMax: "800000",
    suburbs: "Mascot",
    status: "active",
  });
  assert.equal(value.errors.name, "Enter a case name.");
  assert.match(value.errors.budget, /cannot be less/);
  assert.equal(buildCasePayload({ name: "", status: "active" }).payload, null);
});

test("public API client performs list, create, read, update and delete", async () => {
  const calls = [];
  const fakeFetch = async (url, options) => {
    calls.push({ url, options });
    if (options.method === "GET" && url.includes("?")) return jsonResponse(200, { items: [] });
    if (options.method === "DELETE") return jsonResponse(200, { deleted: "case-1" });
    return jsonResponse(options.method === "POST" ? 201 : 200, { id: "case-1", version: 1 });
  };
  const api = createBuyerCaseApi(fakeFetch);
  await api.list();
  await api.create({ name: "Case", status: "active" });
  await api.read("case-1");
  await api.update("case-1", { version: 1, status: "paused" });
  await api.delete("case-1");
  assert.deepEqual(calls.map((call) => call.options.method), ["GET", "POST", "GET", "PUT", "DELETE"]);
  assert.equal(JSON.parse(calls[1].options.body).name, "Case");
  assert.equal(JSON.parse(calls[3].options.body).version, 1);
  assert.equal(Object.keys(calls[0].options.headers).includes("X-PropertyScope-Internal-Token"), false);
});

test("API problems map to conflict and invalid UI states", async () => {
  const conflictApi = createBuyerCaseApi(async () => jsonResponse(409, { code: "version_conflict", detail: "Refresh" }));
  await assert.rejects(conflictApi.update("case-1", { version: 1 }), (error) => {
    assert.equal(error instanceof ApiProblem, true);
    assert.equal(error.status, 409);
    assert.equal(uiStateForError(error), "conflict");
    return true;
  });
  assert.equal(uiStateForError(new ApiProblem(422, "validation_failed", "Invalid")), "invalid");
});

test("network failures map to the unavailable UI state", async () => {
  const api = createBuyerCaseApi(async () => {
    throw new Error("network detail");
  });
  await assert.rejects(api.list(), (error) => {
    assert.equal(error.message.includes("network detail"), false);
    assert.equal(uiStateForError(error), "unavailable");
    return true;
  });
});

test("routes, labels, formatting and escaping are deterministic", () => {
  assert.deepEqual(parseRoute("#buyer-cases/case-1"), { name: "detail", id: "case-1" });
  assert.deepEqual(parseRoute("#other"), { name: "list" });
  assert.deepEqual(parseRoute("#buyer-cases/%"), { name: "list" });
  assert.equal(statusLabel("active"), "Active");
  assert.equal(statusLabel("other"), "Unknown");
  assert.match(formatBudget(700000, 900000), /700,000/);
  assert.equal(escapeHtml('<script>"x"</script>'), "&lt;script&gt;&quot;x&quot;&lt;/script&gt;");
});

test("mutation follow-up navigation performs exactly one read", async () => {
  async function exercise(currentHash, targetHash) {
    let reads = 0;
    let navigations = 0;
    const outcome = await navigateForFollowUp(
      targetHash,
      currentHash,
      () => {
        navigations += 1;
        reads += 1;
      },
      async () => {
        reads += 1;
      },
    );
    return { outcome, reads, navigations };
  }
  assert.deepEqual(await exercise("#buyer-cases", "#buyer-cases/new-case"), {
    outcome: "navigated",
    reads: 1,
    navigations: 1,
  });
  assert.deepEqual(await exercise("#buyer-cases/case-1", "#buyer-cases/case-1"), {
    outcome: "reloaded",
    reads: 1,
    navigations: 0,
  });
  assert.deepEqual(await exercise("#buyer-cases/case-1", "#buyer-cases"), {
    outcome: "navigated",
    reads: 1,
    navigations: 1,
  });
});

test("property, note and task payloads validate Release 0 fields", () => {
  const property = buildPropertyPayload({
    propertyRef: "a0000000-0000-0000-0000-000000000001",
    propertyLabel: " Candidate ", journeyStage: "Offer Considered", rating: "5", priority: "high",
  });
  assert.deepEqual(property.payload, {
    property_ref: "a0000000-0000-0000-0000-000000000001",
    property_label: "Candidate", journey_stage: "Offer Considered", rating: 5, priority: "high",
  });
  assert.equal(buildPropertyPayload({ propertyRef: "bad", rating: "6" }).payload, null);
  assert.deepEqual(buildNotePayload({ content: "  Check strata  ", propertyId: "property-1" }, 2).payload, {
    case_property_id: "property-1", content: "Check strata", version: 2,
  });
  assert.equal(buildNotePayload({ content: " " }).payload, null);
  assert.deepEqual(buildTaskPayload({ title: " Inspect ", dueDate: "2026-09-10", completed: true }, 3).payload, {
    case_property_id: null, title: "Inspect", due_date: "2026-09-10", completed: true, version: 3,
  });
  assert.equal(buildTaskPayload({ title: "" }).payload, null);
});

test("child resource API covers CRUD through public routes", async () => {
  const calls = [];
  const api = createBuyerCaseApi(async (url, options) => {
    calls.push({ url, method: options.method });
    return jsonResponse(options.method === "POST" ? 201 : 200, options.method === "GET" && url.includes("?") ? { items: [] } : {});
  });
  for (const resource of [api.properties, api.notes, api.tasks]) {
    await resource.list("case-1");
    await resource.create("case-1", {});
    await resource.read("case-1", "item-1");
    await resource.update("case-1", "item-1", { version: 1 });
    await resource.delete("case-1", "item-1");
  }
  assert.deepEqual(calls.map((call) => call.method), [
    "GET", "POST", "GET", "PUT", "DELETE",
    "GET", "POST", "GET", "PUT", "DELETE",
    "GET", "POST", "GET", "PUT", "DELETE",
  ]);
  assert.equal(calls.every((call) => call.url.startsWith(`${API_BASE}/buyer-cases/case-1/`)), true);
});

test("evidence and summary APIs stay behind the Student 5 public boundary", async () => {
  const calls = [];
  const api = createBuyerCaseApi(async (url, options) => {
    calls.push({ url, options });
    return jsonResponse(options.method === "POST" ? 202 : 200, {});
  });
  await api.evidence("case-1");
  await api.summaries.create("case-1", "summary-key-123");
  await api.summaries.read("case-1", "run-1");
  assert.deepEqual(calls.map((item) => item.options.method), ["GET", "POST", "GET"]);
  assert.equal(calls[1].options.headers["Idempotency-Key"], "summary-key-123");
  assert.equal(calls.every((item) => item.url.startsWith(`${API_BASE}/buyer-cases/case-1/`)), true);
});

test("bounded evidence renderer exposes all states and limitations safely", () => {
  const html = renderEvidence({
    sections: {
      feature_1: { state: "complete", items: [{ property_ref: "property-1", state: "complete", address_display: "<Address>" }] },
      feature_2: { state: "partial", items: [] },
      feature_3: { state: "unavailable", items: [], limitations: ["No public API"] },
      feature_4: { state: "conflicting", items: [{ property_ref: "property-1", state: "needs_verification" }] },
    },
    evidence_references: ["feature_1:property_ref:property-1"],
    limitations: ["Bounded to 10 properties"],
  });
  for (const label of ["Complete", "Partial", "Unavailable", "Conflicting", "Needs verification"]) {
    assert.match(html, new RegExp(label));
  }
  assert.match(html, /&lt;Address&gt;/);
  assert.match(html, /Bounded to 10 properties/);
  assert.match(html, /feature_1:property_ref:property-1/);
  assert.match(html, /<code>property-1<\/code>: Complete/);
  for (const mojibake of ["â", "€", "�"]) assert.doesNotMatch(html, new RegExp(mojibake));
});

test("AI summary renderer preserves its user-facing result without phase cards", () => {
  const rawReference = "buyer.evidence.collect.v1:feature_1:property_ref:b5000000-0000-4000-8000-000000000001:succeeded";
  const html = renderSummaryRun({
    status: "succeeded",
    phases: ["plan", "act", "observe", "adapt"].map((name) => ({ name, status: "succeeded" })),
    summary: "Review <evidence>",
    suggested_next_actions: ["Book inspection"],
    evidence_used: [
      { label: "Buyer case and shortlist", status: "Retrieved", detail: "1 shortlisted property" },
      { label: "Case notes", status: "Retrieved", detail: "1 note" },
      { label: "Case tasks", status: "Retrieved", detail: "2 tasks (1 completed, 1 incomplete)" },
      { label: "Property discovery", status: "Complete" },
      { label: "Sales research", status: "Conflicting; verification required" },
      { label: "Suburb analytics", status: "Unavailable" },
      { label: "Due diligence", status: "Partial" },
    ],
    evidence_references: [rawReference],
    limitations: ["Feature 3 unavailable"],
  });
  assert.match(html, /Case summary generated successfully\./);
  assert.doesNotMatch(html, /AI processing details/);
  assert.doesNotMatch(html, /run-phases|data-phase/);
  assert.match(html, /Review &lt;evidence&gt;/);
  const primaryEvidence = html.slice(html.indexOf("<h4>Evidence used</h4>"), html.indexOf('<details class="technical-audit"'));
  for (const label of ["Buyer case and shortlist", "Case notes", "Case tasks", "Property discovery", "Sales research", "Suburb analytics", "Due diligence"]) {
    assert.match(primaryEvidence, new RegExp(label));
  }
  assert.match(primaryEvidence, /Buyer case and shortlist<\/strong>: Retrieved; 1 shortlisted property/);
  assert.match(primaryEvidence, /Case tasks<\/strong>: Retrieved; 2 tasks \(1 completed, 1 incomplete\)/);
  assert.match(primaryEvidence, /Sales research<\/strong>: Conflicting; verification required/);
  assert.match(primaryEvidence, /Due diligence<\/strong>: Partial/);
  for (const mojibake of ["â", "€", "�"]) assert.doesNotMatch(html, new RegExp(mojibake));
  assert.doesNotMatch(primaryEvidence, /buyer\.evidence|feature_1|b5000000/);
  assert.match(html, /<details class="technical-audit"><summary>Technical audit references<\/summary>/);
  assert.doesNotMatch(html, /<details class="technical-audit" open/);
  assert.match(html, new RegExp(rawReference.replaceAll(".", "\\.")));
  assert.match(html, /Feature 3 unavailable/);
});

test("AI workflow presents a compact accessible idle status", () => {
  const view = summaryWorkflowView(null);
  const html = renderSummaryRun(null, view);
  assert.deepEqual(view, { statusText: "Ready to generate a case summary." });
  assert.match(html, /role="status" aria-live="polite" data-workflow-status>Ready to generate a case summary\.<\/p>/);
  assert.doesNotMatch(html, /AI processing details|run-phases|data-phase/);
});

test("AI workflow uses one concise processing status for every phase", () => {
  for (const status of ["queued", "planning", "acting", "observing", "adapting", "review_required"]) {
    const run = { status, phases: [{ name: "adapt", status: "running" }] };
    assert.equal(summaryWorkflowView(run).statusText, "Generating case summary");
  }
});

test("successful workflow status is concise", () => {
  const view = summaryWorkflowView({ status: "succeeded", phases: [] });
  assert.equal(view.statusText, "Case summary generated successfully.");
});

test("failed workflow status identifies the failed phase without rendering phase cards", () => {
  const run = {
    status: "failed",
    phases: [
      { name: "plan", status: "succeeded" },
      { name: "act", status: "succeeded" },
      { name: "observe", status: "succeeded" },
      { name: "adapt", status: "failed" },
    ],
    error: "Generation stopped safely.",
  };
  const view = summaryWorkflowView(run);
  const html = renderSummaryRun(run, view);
  assert.equal(view.statusText, "The case summary could not be generated: Adapt failed.");
  assert.match(html, /role="status" aria-live="polite"/);
  assert.doesNotMatch(html, /AI processing details|run-phases|data-phase/);
});

test("workspace renderers show journey, ratings, associations and completion controls safely", () => {
  const propertyHtml = renderPropertyItems([{
    id: "property-1", property_ref: "f1000000-0000-4000-8000-000000000001",
    property_label: "<Candidate>", journey_stage: "Reviewing", priority: "high", rating: 4,
    property_validation_state: "pending",
  }]);
  assert.match(propertyHtml, /Reviewing/);
  assert.match(propertyHtml, /4\/5/);
  assert.match(propertyHtml, /&lt;Candidate&gt;/);
  assert.match(renderNoteItems([{ id: "note-1", content: "Observe", case_property_id: "property-1" }], () => "Candidate"), /Related to: Candidate/);
  const taskHtml = renderTaskItems([{ id: "task-1", title: "Call agent", due_date: "2026-09-10", completed: true, case_property_id: null }]);
  assert.match(taskHtml, /Mark incomplete/);
  assert.match(taskHtml, /is-complete/);
});
