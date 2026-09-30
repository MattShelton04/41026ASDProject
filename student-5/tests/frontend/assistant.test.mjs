import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { createBuyerAssistant, CASE_SUMMARY_MESSAGE, setSummaryVisibility } from "../../frontend/assistant.js";
import { createAssistantClient, answerSections, evidenceSteps } from "../../frontend/ai-chat/index.js";

test("summary shortcut is hidden without an open case", () => {
  const button = {};
  setSummaryVisibility(button, false);
  assert.deepEqual(button, {hidden: true, disabled: true});
  setSummaryVisibility(button, true);
  assert.deepEqual(button, {hidden: false, disabled: false});
  setSummaryVisibility(button, false);
  assert.deepEqual(button, {hidden: true, disabled: true});
});

test("summary shortcut and typed summary submit the same case-scoped request", async () => {
  const requests = [];
  const label = {};
  let state;
  let submitted;
  const client = createAssistantClient({
    apiRoot: "/api/buyer-workspaces/v1/assistant",
    fetcher: async (url, options) => {
      requests.push({ url, body: JSON.parse(options.body) });
      return { ok: true, status: 202, headers: new Headers(), json: async () => ({ run: { id: "run-1" } }) };
    },
  });
  const scope = { disabled: false, value: "guidance", dispatchEvent(event) { assert.equal(event.type, "change"); state.scope = this.value; } };
  const form = { requestSubmit() { submitted = client.createTurn(state); } };
  const root = { querySelector(selector) { return selector === "form" ? form : scope; } };
  const assistant = createBuyerAssistant(root, (options) => {
    state = { scope: options.initialScope, context: options.context, history: [] };
    return { controller: {
      destroy() {},
      setContext(context) { state.context = context; },
      setDraft(message) { state.message = message; },
    } };
  }, label);
  assistant.select(null);
  assert.equal(assistant.summarise(), false);
  assistant.select({ id: "case-a", name: "<Selected buyer>" });
  assert.equal(label.textContent, "Selected case: <Selected buyer>");
  state.scope = "guidance";
  state.history = [{ role: "user", content: "Earlier question" }, { role: "assistant", content: "Earlier answer" }];
  assert.equal(assistant.summarise(), true);
  await submitted;
  await client.createTurn({ ...state, message: CASE_SUMMARY_MESSAGE });
  assert.deepEqual(requests[0], requests[1]);
  assert.equal(requests[0].url, "/api/buyer-workspaces/v1/assistant/turns");
  assert.equal(requests[0].body.scope, "case");
  assert.equal(requests[0].body.context.buyer_case_id, "case-a");
  assert.equal(requests[0].body.history.length, 2);
  scope.disabled = true;
  assert.equal(assistant.summarise(), false);
  assert.equal(requests.length, 2);
  assistant.select({ id: "case-b", name: "Second buyer" });
  scope.disabled = false;
  assistant.summarise();
  await submitted;
  assert.equal(requests[2].body.context.buyer_case_id, "case-b");
  assert.deepEqual(requests[2].body.history, []);
  assistant.select(null);
  assert.equal(assistant.summarise(), false);
  assert.match(label.textContent, /No case selected/);
  client.destroy();
});

test("page selection determines the single scope and isolates conversations on case changes", () => {
  const calls = [];
  let destroyed = 0;
  const assistant = createBuyerAssistant({}, (options) => {
    calls.push(options);
    return { controller: { destroy() { destroyed += 1; }, setContext() {} } };
  });
  assistant.select(null);
  assert.equal(calls[0].apiRoot, "/api/buyer-workspaces/v1/assistant");
  assert.equal(calls[0].initialScope, "guidance");
  assert.deepEqual(calls[0].context, {});
  assert.deepEqual(calls[0].scopes.map((scope) => scope.id), ["guidance"]);
  assistant.select({ id: "case-a", name: "First buyer" });
  assert.equal(calls[1].initialScope, "case");
  assert.deepEqual(calls[1].scopes.map((scope) => scope.id), ["case"]);
  assert.match(calls[1].scopes[0].label, /records and workspace guidance/);
  assert.deepEqual(calls[1].context, { buyer_case_id: "case-a", display_label: "First buyer" });
  assistant.select({ id: "case-a", name: "First buyer" });
  assert.equal(calls.length, 2);
  assistant.select({ id: "case-b", name: "Second buyer" });
  assert.equal(destroyed, 2);
  assert.equal(calls[2].context.buyer_case_id, "case-b");
  assert.equal(calls[2].initialScope, "case");
  assistant.select(null);
  assert.deepEqual(calls[3].context, {});
  assert.equal(calls[3].initialScope, "guidance");
  assert.deepEqual(calls[3].scopes.map((scope) => scope.id), ["guidance"]);
  assistant.destroy();
  assert.equal(destroyed, 4);
});

test("selected-case task questions propagate the default case scope to the public API", async () => {
  const calls = [];
  let selectedOptions;
  const assistant = createBuyerAssistant({}, (options) => {
    selectedOptions = options;
    return { controller: { destroy() {} } };
  });
  assistant.select({ id: "case-a", name: "First buyer" });
  const client = createAssistantClient({
    apiRoot: "/api/buyer-workspaces/v1/assistant",
    fetcher: async (url, options) => {
      calls.push({ url, options });
      return { ok: true, status: 202, headers: new Headers(), json: async () => ({ run: { id: "run-1" } }) };
    },
  });
  await client.createTurn({ message: "What are this case's outstanding tasks?", scope: selectedOptions.initialScope, context: selectedOptions.context, history: [] });
  await client.getTurn("run-1");
  await client.getEvents("run-1", 3);
  await client.cancelTurn("run-1");
  assert.deepEqual(calls.map((call) => call.url), [
    "/api/buyer-workspaces/v1/assistant/turns",
    "/api/buyer-workspaces/v1/assistant/turns/run-1",
    "/api/buyer-workspaces/v1/assistant/turns/run-1/events?after=3&limit=100",
    "/api/buyer-workspaces/v1/assistant/turns/run-1/cancel",
  ]);
  assert.equal(JSON.parse(calls[0].options.body).context.buyer_case_id, "case-a");
  assert.equal(JSON.parse(calls[0].options.body).scope, "case");
  assert.doesNotMatch(JSON.stringify(calls), /owner_ref|Internal-Token|AI-Token/);
  client.destroy();
  assistant.destroy();
});

test("unified renderer preserves grounded and legacy answers", () => {
  const answer = { summary: "Review the shortlist.", findings: [{ text: "Guidance", kind: "guidance", citation_ids: ["c1"], tool_call_ids: [] }], next_step: "Check your records.", confidence: "low", confidence_reason: "Conflicting evidence", evidence_gaps: ["Identity unverified"], grounding_status: "ready", corpus_version: "a".repeat(64), citations: [{ citation_id: "c1", title: "Buyer guidance", source_uri: "https://example.org/guide" }] };
  assert.ok(answerSections(answer).length > 0);
  assert.ok(answerSections({ summary: "Legacy summary", findings: ["Check records"] }).length > 0);
  assert.deepEqual(evidenceSteps({ steps: [{ phase: "act", status: "succeeded", input: { tool_call: { tool_name: "buyer.capabilities.v1" } }, output: { tool_result: { outcome: "succeeded", evidence_references: [] } } }] })[0].references, []);
});

test("shared assistant surfaces dependency outages without inventing an answer", async () => {
  const client = createAssistantClient({ apiRoot: "/api/buyer-workspaces/v1/assistant", fetcher: async () => ({ ok: false, status: 503, headers: new Headers(), json: async () => ({ title: "Assistant unavailable", status: 503 }) }) });
  await assert.rejects(client.createTurn({ message: "Explain guidance", scope: "guidance", context: {} }), (error) => error.status === 503);
  client.destroy();
});

test("Student 5 mounts the shared accessible source renderer and shared stylesheet", () => {
  const html = readFileSync(new URL("../../frontend/index.html", import.meta.url), "utf8");
  const source = readFileSync(new URL("../../frontend/assistant.js", import.meta.url), "utf8");
  assert.match(html, /id="buyer-assistant"/);
  assert.match(html, /ai-chat\/styles.css/);
  assert.match(source, /createFeatureAssistant/);
  const css = readFileSync(new URL("../../frontend/styles.css", import.meta.url), "utf8");
  assert.match(css, /#buyer-assistant \.ps-ai-chat__settings\s*\{\s*display: none;/);
  assert.match(html, /Inspect MCP tools and RAG retrieval in Sources &amp; activity/);
  assert.doesNotMatch(html, /Choose Case records/);
  assert.equal((html.match(/id="buyer-assistant"/g) || []).length, 1);
  assert.match(html, /id="assistant-selected-case" role="status" aria-live="polite"/);
  assert.match(html, /id="summarise-case" hidden disabled>Summarise this case/);
  const app = readFileSync(new URL("../../frontend/app.js", import.meta.url), "utf8");
  assert.doesNotMatch(app + source, /mountGroundedSummary|data-summary-run|data-generate-summary|api\.summaries/);
});
