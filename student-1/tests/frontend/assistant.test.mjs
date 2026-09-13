import assert from "node:assert/strict";
import test from "node:test";
import { assistantContextFromHash, searchAssistantContext } from "../../frontend/integration/assistant.js";

const propertyRef = "2c8a15ce-2f3d-9c88-a648-c28b2da0de38";
test("canonical hash-derived property UUIDs and readable labels survive navigation", () => {
  assert.deepEqual(assistantContextFromHash(`#assistant?route=properties/detail&property_ref=${propertyRef}&display_label=Auburn+Street`), {
    route: "properties/detail", property_ref: propertyRef, display_label: "Auburn Street",
  });
  assert.deepEqual(assistantContextFromHash("#assistant?route=properties/detail&query=Auburn+Street"), { route: "properties/detail", query: "Auburn Street" });
  assert.deepEqual(assistantContextFromHash("#assistant?route=properties/detail&property_ref=broken&query=Auburn"), {});
});

test("record search preserves all ambiguous matches and their exact IDs", async () => {
  const calls = [];
  const controller = new AbortController();
  const results = await searchAssistantContext("property", "Auburn Street", { signal: controller.signal, fetcher: async (url, options) => {
    calls.push({ url, options });
    return { ok: true, status: 200, headers: new Headers(), json: async () => ({ items: [
      { property_ref: propertyRef, address_display: "10A Auburn Street" },
      { property_ref: "35a4f52f-7b17-1dca-5f4b-0e927a974c28", address_display: "10 Auburn Street" },
    ] }) };
  } });
  assert.match(calls[0].url, /properties\/search\?q=Auburn%20Street&state=NSW&limit=8/);
  assert.equal(results.items.length, 2);
  assert.equal(results.items[0].context.property_ref, propertyRef);
  assert.equal(results.items[0].label, "10A Auburn Street");
});
