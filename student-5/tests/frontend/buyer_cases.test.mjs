import assert from "node:assert/strict";
import { test } from "node:test";

import {
  API_BASE,
  ApiProblem,
  buildCasePayload,
  createBuyerCaseApi,
  escapeHtml,
  formatBudget,
  mergePreferences,
  navigateForFollowUp,
  parseRoute,
  preferenceStringsFromText,
  projectPreferenceLists,
  statusLabel,
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
