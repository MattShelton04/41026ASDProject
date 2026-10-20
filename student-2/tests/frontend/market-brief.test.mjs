import assert from "node:assert/strict";
import test from "node:test";

import {
  addressClaimsMarketBrief,
  forgetMarketBrief,
  marketBriefEnabled,
  MARKET_BRIEF_CAPABILITIES_PATH,
  MARKET_BRIEF_MEMORY_LIMIT,
  MARKET_BRIEF_STORAGE_KEY,
  marketBriefCaseId,
  marketBriefHash,
  marketBriefRunId,
  rememberedMarketBrief,
  rememberMarketBrief,
  resumableMarketBrief,
} from "../../frontend/integration/market-brief.js";

const CASE_ID = "60000000-0000-4000-8000-000000000001";
const OTHER_CASE_ID = "60000000-0000-4000-8000-000000000002";
const RUN_ID = "68c410ca-cdd9-4268-bbaa-30de64d0b50c";

function memoryStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    values,
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => { values.set(key, String(value)); },
  };
}

function brokenStorage() {
  return {
    getItem() { throw new Error("storage is blocked"); },
    setItem() { throw new Error("storage is blocked"); },
  };
}

test("only a well-formed run identifier is read from the address", () => {
  assert.equal(marketBriefRunId(`#market-cases?brief=${RUN_ID}`), RUN_ID);
  assert.equal(marketBriefRunId(`#market-cases?brief=${RUN_ID.toUpperCase()}`), RUN_ID);
  assert.equal(marketBriefRunId(`#market-cases?other=1&brief=${RUN_ID}`), RUN_ID);
  // Anything that is not a run identifier is ignored rather than sent to the server.
  assert.equal(marketBriefRunId("#market-cases?brief=../../etc/passwd"), null);
  assert.equal(marketBriefRunId("#market-cases?brief="), null);
  assert.equal(marketBriefRunId("#market-cases"), null);
  assert.equal(marketBriefRunId(""), null);
  assert.equal(marketBriefRunId(), null);
});

test("the address names the run, and drops it when there is none", () => {
  assert.equal(marketBriefHash(RUN_ID), `#market-cases?brief=${RUN_ID}`);
  assert.equal(marketBriefHash(RUN_ID.toUpperCase()), `#market-cases?brief=${RUN_ID}`);
  assert.equal(marketBriefHash(null), "#market-cases");
  assert.equal(marketBriefHash("not-a-run"), "#market-cases");
  assert.equal(marketBriefHash(), "#market-cases");
});

test("the latest brief for each case is remembered, bounded and tolerant of broken storage", () => {
  const storage = memoryStorage();
  assert.equal(rememberedMarketBrief(CASE_ID, storage), null);

  rememberMarketBrief(CASE_ID, RUN_ID.toUpperCase(), storage);
  assert.equal(rememberedMarketBrief(CASE_ID, storage), RUN_ID);

  // A value that is not a run identifier never replaces a good one.
  rememberMarketBrief(CASE_ID, "not-a-run", storage);
  assert.equal(rememberedMarketBrief(CASE_ID, storage), RUN_ID);

  for (let index = 0; index < MARKET_BRIEF_MEMORY_LIMIT + 5; index += 1) {
    rememberMarketBrief(`case-${index}`, RUN_ID, storage);
  }
  const kept = JSON.parse(storage.getItem(MARKET_BRIEF_STORAGE_KEY));
  assert.equal(Object.keys(kept).length, MARKET_BRIEF_MEMORY_LIMIT);
  // Insertion order is recency order, so the oldest cases are the ones dropped.
  assert.ok(!(CASE_ID in kept));

  // Storage is a convenience: a browser that refuses it must not break the page.
  assert.doesNotThrow(() => rememberMarketBrief(CASE_ID, RUN_ID, brokenStorage()));
  assert.equal(rememberedMarketBrief(CASE_ID, brokenStorage()), null);
});

test("forgetting only drops the run it was asked about", () => {
  const storage = memoryStorage();
  rememberMarketBrief(CASE_ID, RUN_ID, storage);
  forgetMarketBrief(CASE_ID, "68c410ca-0000-0000-0000-000000000000", storage);
  assert.equal(rememberedMarketBrief(CASE_ID, storage), RUN_ID);
  forgetMarketBrief(CASE_ID, RUN_ID, storage);
  assert.equal(rememberedMarketBrief(CASE_ID, storage), null);
});

test("a remembered brief is reopened only when the server still has it for this case", async () => {
  const storage = memoryStorage();
  rememberMarketBrief(CASE_ID, RUN_ID, storage);
  const request = async () => ({ input: { market_case_id: CASE_ID } });
  assert.equal(await resumableMarketBrief(CASE_ID, { request, storage }), RUN_ID);
});

test("a run the server no longer has is forgotten rather than opened as an error", async () => {
  const storage = memoryStorage();
  rememberMarketBrief(CASE_ID, RUN_ID, storage);
  const request = async () => { throw Object.assign(new Error("gone"), { status: 404 }); };
  assert.equal(await resumableMarketBrief(CASE_ID, { request, storage }), null);
  // The proxy answers 404 for another feature's run too, so the memory must not be retried.
  assert.equal(rememberedMarketBrief(CASE_ID, storage), null);
});

test("a run recorded against another case is forgotten, not opened here", async () => {
  const storage = memoryStorage();
  rememberMarketBrief(CASE_ID, RUN_ID, storage);
  const request = async () => ({ input: { market_case_id: OTHER_CASE_ID } });
  assert.equal(await resumableMarketBrief(CASE_ID, { request, storage }), null);
  assert.equal(rememberedMarketBrief(CASE_ID, storage), null);
});

test("a server that cannot answer keeps the memory for next time", async () => {
  const storage = memoryStorage();
  rememberMarketBrief(CASE_ID, RUN_ID, storage);
  const request = async () => { throw Object.assign(new Error("boom"), { status: 503 }); };
  assert.equal(await resumableMarketBrief(CASE_ID, { request, storage }), null);
  assert.equal(rememberedMarketBrief(CASE_ID, storage), RUN_ID);
});

test("a cancelled lookup is not mistaken for a missing run", async () => {
  const storage = memoryStorage();
  rememberMarketBrief(CASE_ID, RUN_ID, storage);
  const request = async () => { throw Object.assign(new Error("aborted"), { name: "AbortError" }); };
  await assert.rejects(() => resumableMarketBrief(CASE_ID, { request, storage }), /aborted/);
  assert.equal(rememberedMarketBrief(CASE_ID, storage), RUN_ID);
});

test("the run named in the address wins over the remembered one", async () => {
  const storage = memoryStorage();
  const addressed = "58936cad-384f-47f5-8aa4-220f16bce1f0";
  rememberMarketBrief(CASE_ID, RUN_ID, storage);
  const request = async () => ({ input: { market_case_id: CASE_ID } });
  const resumed = await resumableMarketBrief(CASE_ID, { request, preferredRunId: addressed, storage });
  assert.equal(resumed, addressed);
});

test("a link resolves to the case its run was recorded against", async () => {
  const request = async (path) => {
    assert.ok(path.endsWith(RUN_ID), `looked up ${path}`);
    return { input: { market_case_id: CASE_ID } };
  };
  assert.equal(await marketBriefCaseId(RUN_ID, { request }), CASE_ID);
  // A link that names nothing usable never reaches the server.
  let called = false;
  const spy = async () => { called = true; return {}; };
  assert.equal(await marketBriefCaseId("not-a-run", { request: spy }), null);
  assert.equal(called, false);
});

test("an unknown run in a link opens the page instead of reporting an error", async () => {
  const request = async () => { throw Object.assign(new Error("gone"), { status: 404 }); };
  assert.equal(await marketBriefCaseId(RUN_ID, { request }), null);
});

test("an address that claims a brief is recognised even when the value is unusable", () => {
  // The page clears such a value: an address naming a run nobody can open misreports the screen.
  assert.equal(addressClaimsMarketBrief(`#market-cases?brief=${RUN_ID}`), true);
  assert.equal(addressClaimsMarketBrief("#market-cases?brief=not-a-run"), true);
  assert.equal(addressClaimsMarketBrief("#market-cases?brief="), true);
  assert.equal(addressClaimsMarketBrief("#market-cases"), false);
  assert.equal(addressClaimsMarketBrief(""), false);
  assert.equal(addressClaimsMarketBrief(), false);
});

test("briefs are treated as disabled unless the feature clearly says otherwise", async () => {
  // The Multi-Agent Server is a host process, so a Compose-only stack has none to reach. The
  // page asks this instead of mounting a panel whose first request could only answer 503.
  const asked = [];
  const answering = (body) => async (path) => { asked.push(path); return body; };

  assert.equal(await marketBriefEnabled({ request: answering({ market_brief: { enabled: true } }) }), true);
  assert.equal(asked[0], MARKET_BRIEF_CAPABILITIES_PATH);

  assert.equal(await marketBriefEnabled({ request: answering({ market_brief: { enabled: false } }) }), false);
  // A deployment too old to publish the route, or any other refusal, is disabled too.
  assert.equal(await marketBriefEnabled({
    request: async () => { throw Object.assign(new Error("gone"), { status: 404 }); },
  }), false);
  assert.equal(await marketBriefEnabled({ request: answering({}) }), false);
  // Truthy-but-not-true must not count as enabled.
  assert.equal(await marketBriefEnabled({ request: answering({ market_brief: { enabled: "yes" } }) }), false);
});

test("a cancelled capability lookup is not mistaken for a disabled deployment", async () => {
  await assert.rejects(() => marketBriefEnabled({
    request: async () => { throw Object.assign(new Error("aborted"), { name: "AbortError" }); },
  }), /aborted/);
});
