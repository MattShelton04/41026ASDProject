import assert from "node:assert/strict";
import test from "node:test";

import { evidenceState, formatCurrency, listItems, routeName } from "../frontend/model.js";

test("unknown routes fall back to readiness", () => {
  assert.equal(routeName("#buyer"), "buyer");
  assert.equal(routeName("#not-a-route"), "readiness");
});

test("list envelopes and direct arrays are accepted", () => {
  assert.deepEqual(listItems({ items: [{ id: 1 }] }), [{ id: 1 }]);
  assert.deepEqual(listItems([{ id: 2 }]), [{ id: 2 }]);
  assert.deepEqual(listItems(null), []);
});

test("evidence projection fails unknown states closed", () => {
  assert.equal(evidenceState({ state: "complete" }), "complete");
  assert.equal(evidenceState({ status: "needs_verification" }), "needs_verification");
  assert.equal(evidenceState({ state: "healthy" }), "unavailable");
});

test("currency formatting does not invent missing values", () => {
  assert.match(formatCurrency(1250000), /1,250,000/);
  assert.equal(formatCurrency(null), "Unavailable");
  assert.equal(formatCurrency(undefined), "Unavailable");
});
