import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync("student-2/frontend/index.html", "utf8");
const app = readFileSync("student-2/frontend/app.js", "utf8");
const fragment = readFileSync("student-2/frontend/integration/research-area.html", "utf8");

test("market page exposes CRUD, evidence and AI regions", () => {
  for (const marker of ["case-list", "case-form", "volume-chart", "sales-body", "assistant-root"]) {
    assert.match(page, new RegExp(`id="${marker}"`));
  }
  // Criterion 4 is marked on citations and confidence, which the shared renderer owns.
  assert.match(page, /ai-chat\/styles\.css/);
  assert.match(page, /not a valuation or buying recommendation/i);
  assert.match(page, /Selected property/);
  assert.match(page, /The service checks the reference when you save/);
  assert.doesNotMatch(page, /property reference|UUID/i);
});

test("browser code uses the owned API and all CRUD verbs", () => {
  assert.match(app, /\/api\/market-intelligence\/v1/);
  for (const verb of ["POST", "PUT", "DELETE"]) assert.match(app, new RegExp(`method: "${verb}"`));
  assert.match(app, /form-property-choice/);
});

test("the assistant is the shared grounded renderer, scoped to the selected case", () => {
  assert.match(app, /createFeatureAssistant/);
  assert.match(app, /from "\.\/ai-chat\/index\.js"/);
  assert.match(app, /apiRoot: `\$\{API\}\/assistant`/);
  assert.match(app, /featureKey: "student-2-market-intelligence"/);
  // The selected case must reach the turn as context, or every answer is unscoped.
  assert.match(app, /setContext\(/);
  assert.match(app, /market_case_id: item\.id/);
});

test("research area fragment replaces the planned sales row", () => {
  assert.match(fragment, /data-feature-id="sales-market"/);
  assert.match(fragment, /data-feature-state="available"/);
  assert.match(fragment, /\/features\/market-intelligence\/#market-cases/);
});

test("the assistant is withheld until a market case is bound", () => {
  // An unscoped turn is rejected as a missing case_id, which reads as a fault to the user.
  assert.match(page, /id="assistant-root" hidden/);
  assert.match(page, /id="assistant-requires-case"/);
  assert.match(app, /byId\("assistant-root"\)\.hidden = !item/);
  // Creating the assistant lazily is what removes the load-order race with loadCases().
  assert.match(app, /if \(!state\.assistant\) initialiseAssistant\(\)/);
  assert.doesNotMatch(app, /^initialiseAssistant\(\);$/m);
});
