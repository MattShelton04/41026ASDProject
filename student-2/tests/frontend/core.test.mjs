import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync("student-2/frontend/index.html", "utf8");
const app = readFileSync("student-2/frontend/app.js", "utf8");
const fragment = readFileSync("student-2/frontend/integration/research-area.html", "utf8");

test("market page exposes CRUD, evidence and AI regions", () => {
  for (const marker of ["case-list", "case-form", "volume-chart", "sales-body", "assistant-form"]) {
    assert.match(page, new RegExp(`id="${marker}"`));
  }
  assert.match(page, /not a valuation or buying recommendation/i);
  assert.match(page, /Selected property/);
  assert.match(page, /The service checks the reference when you save/);
  assert.doesNotMatch(page, /property reference|UUID/i);
});

test("browser code uses the owned API and all CRUD verbs", () => {
  assert.match(app, /\/api\/market-intelligence\/v1/);
  for (const verb of ["POST", "PUT", "DELETE"]) assert.match(app, new RegExp(`method: "${verb}"`));
  assert.match(app, /\/assistant\/turns/);
  assert.match(app, /redactInternalIdentifiers/);
  assert.match(app, /form-property-choice/);
});

test("research area fragment replaces the planned sales row", () => {
  assert.match(fragment, /data-feature-id="sales-market"/);
  assert.match(fragment, /data-feature-state="available"/);
  assert.match(fragment, /\/features\/market-intelligence\/#market-cases/);
});
